#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/garbagecollector/garbagecollector_test.go b/pkg/controller/garbagecollector/garbagecollector_test.go
index 8663e6c24a868..2b164fd17cfca 100644
--- a/pkg/controller/garbagecollector/garbagecollector_test.go
+++ b/pkg/controller/garbagecollector/garbagecollector_test.go
@@ -18,6 +18,7 @@ package garbagecollector
 
 import (
 	"context"
+	goerrors "errors"
 	"fmt"
 	"net/http"
 	"net/http/httptest"
@@ -255,6 +256,126 @@ func serilizeOrDie(t *testing.T, object interface{}) []byte {
 	return data
 }
 
+func TestAttemptToDeleteItemDeleteObjectNotFound(t *testing.T) {
+	pod := getPod("ExternallyDeletedPod", []metav1.OwnerReference{
+		{
+			Kind:       "ReplicationController",
+			Name:       "owner1",
+			UID:        "123",
+			APIVersion: "v1",
+		},
+	})
+	testHandler := &fakeActionHandler{
+		response: map[string]FakeResponse{
+			"GET" + "/api/v1/namespaces/ns1/replicationcontrollers/owner1": {
+				404,
+				[]byte{},
+			},
+			"GET" + "/api/v1/namespaces/ns1/pods/ExternallyDeletedPod": {
+				200,
+				serilizeOrDie(t, pod),
+			},
+			"DELETE" + "/api/v1/namespaces/ns1/pods/ExternallyDeletedPod": {
+				404,
+				[]byte{},
+			},
+		},
+	}
+	srv, clientConfig := testServerAndClientConfig(testHandler.ServeHTTP)
+	defer srv.Close()
+
+	gc := setupGC(t, clientConfig)
+	defer close(gc.stop)
+
+	item := &node{
+		identity: objectReference{
+			OwnerReference: metav1.OwnerReference{
+				Kind:       pod.Kind,
+				APIVersion: pod.APIVersion,
+				Name:       pod.Name,
+				UID:        pod.UID,
+			},
+			Namespace: pod.Namespace,
+		},
+		owners: nil,
+	}
+
+	err := gc.attemptToDeleteItem(context.TODO(), item)
+	if !goerrors.Is(err, enqueuedVirtualDeleteEventErr) {
+		t.Errorf("expected enqueuedVirtualDeleteEventErr, got: %v", err)
+	}
+	if gc.dependencyGraphBuilder.graphChanges.Len() == 0 {
+		t.Errorf("expected a virtual delete event to be enqueued in graphChanges, but the queue is empty")
+	}
+}
+
+func TestAttemptToDeleteItemDeleteObjectNotFoundWaitingForDependents(t *testing.T) {
+	pod := getPod("ExternallyDeletedPodFG", []metav1.OwnerReference{
+		{
+			Kind:               "ReplicationController",
+			Name:               "owner1",
+			UID:                "123",
+			APIVersion:         "v1",
+			BlockOwnerDeletion: func() *bool { b := true; return &b }(),
+		},
+	})
+	owner := &v1.ReplicationController{
+		TypeMeta: metav1.TypeMeta{
+			Kind:       "ReplicationController",
+			APIVersion: "v1",
+		},
+		ObjectMeta: metav1.ObjectMeta{
+			Name:              "owner1",
+			Namespace:         "ns1",
+			UID:               "123",
+			DeletionTimestamp: func() *metav1.Time { t := metav1.Now(); return &t }(),
+			Finalizers:        []string{metav1.FinalizerDeleteDependents},
+		},
+	}
+	testHandler := &fakeActionHandler{
+		response: map[string]FakeResponse{
+			"GET" + "/api/v1/namespaces/ns1/replicationcontrollers/owner1": {
+				200,
+				serilizeOrDie(t, owner),
+			},
+			"GET" + "/api/v1/namespaces/ns1/pods/ExternallyDeletedPodFG": {
+				200,
+				serilizeOrDie(t, pod),
+			},
+			"DELETE" + "/api/v1/namespaces/ns1/pods/ExternallyDeletedPodFG": {
+				404,
+				[]byte{},
+			},
+		},
+	}
+	srv, clientConfig := testServerAndClientConfig(testHandler.ServeHTTP)
+	defer srv.Close()
+
+	gc := setupGC(t, clientConfig)
+	defer close(gc.stop)
+
+	item := &node{
+		identity: objectReference{
+			OwnerReference: metav1.OwnerReference{
+				Kind:       pod.Kind,
+				APIVersion: pod.APIVersion,
+				Name:       pod.Name,
+				UID:        pod.UID,
+			},
+			Namespace: pod.Namespace,
+		},
+		owners: nil,
+	}
+
+	err := gc.attemptToDeleteItem(context.TODO(), item)
+	if !goerrors.Is(err, enqueuedVirtualDeleteEventErr) {
+		t.Errorf("expected enqueuedVirtualDeleteEventErr, got: %v", err)
+	}
+	if gc.dependencyGraphBuilder.graphChanges.Len() == 0 {
+		t.Errorf("expected a virtual delete event to be enqueued in graphChanges, but the queue is empty")
+	}
+}
+
 // test the attemptToDeleteItem function making the expected actions.
 func TestAttemptToDeleteItem(t *testing.T) {
 	pod := getPod("ToBeDeletedPod", []metav1.OwnerReference{
diff --git a/test/e2e/apimachinery/etcd_failure.go b/test/e2e/apimachinery/etcd_failure.go
index 5d0b39b13cf7f..8c26abcc9da5b 100644
--- a/test/e2e/apimachinery/etcd_failure.go
+++ b/test/e2e/apimachinery/etcd_failure.go
@@ -115,10 +115,6 @@ func masterExec(ctx context.Context, f *framework.Framework, cmd string) {
 
 	host := ips[0] + ":22"
 	result, err := e2essh.SSH(ctx, cmd, host, framework.TestContext.Provider)
-	framework.ExpectNoError(err)
-	e2essh.LogResult(result)
-
-	result, err = e2essh.SSH(ctx, cmd, host, framework.TestContext.Provider)
 	framework.ExpectNoError(err, "failed to SSH to host %s on provider %s and run command: %q", host, framework.TestContext.Provider, cmd)
 	if result.Code != 0 {
 		e2essh.LogResult(result)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/controller/garbagecollector/... ./test/e2e/apimachinery/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestAttemptToDeleteItemDeleteObjectNotFound", "TestAttemptToDeleteItemDeleteObjectNotFoundWaitingForDependents"]
passed = set()
with open("/tmp/test_output.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action == "pass":
            passed.add(test)
            # Also add the bare test name (no subtest suffix)
            passed.add(test.split("/")[0])

all_pass = all(
    t in passed or t.split("/")[0] in passed
    for t in f2p
)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if t not in passed and t.split("/")[0] not in passed]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
