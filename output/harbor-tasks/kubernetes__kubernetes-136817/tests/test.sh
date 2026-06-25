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

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestAttemptToDeleteItemDeleteObjectNotFound", "TestAttemptToDeleteItemDeleteObjectNotFoundWaitingForDependents"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
