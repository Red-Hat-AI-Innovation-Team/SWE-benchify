#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection_test.go b/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection_test.go
index 211f11df0aa0e..eff461770dd1a 100644
--- a/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection_test.go
+++ b/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection_test.go
@@ -557,7 +557,7 @@ func testReleaseLease(t *testing.T, objectType string) {
 					verb:       "get",
 					objectType: objectType,
 					reaction: func(action fakeclient.Action) (handled bool, ret runtime.Object, err error) {
-						return true, nil, errors.NewNotFound(action.(fakeclient.GetAction).GetResource().GroupResource(), action.(fakeclient.GetAction).GetName())
+						return true, createLockObject(t, objectType, action.GetNamespace(), action.(fakeclient.GetAction).GetName(), &rl.LeaderElectionRecord{HolderIdentity: "baz"}), nil
 					},
 				},
 				{
@@ -574,6 +574,13 @@ func testReleaseLease(t *testing.T, objectType string) {
 						return true, action.(fakeclient.UpdateAction).GetObject(), nil
 					},
 				},
+				{
+					verb:       "get",
+					objectType: objectType,
+					reaction: func(action fakeclient.Action) (handled bool, ret runtime.Object, err error) {
+						return true, nil, errors.NewNotFound(action.(fakeclient.GetAction).GetResource().GroupResource(), action.(fakeclient.GetAction).GetName())
+					},
+				},
 			},
 			expectSuccess: true,
 			outHolder:     "",
@@ -677,6 +684,59 @@ func TestReleaseLeaseLeases(t *testing.T) {
 	testReleaseLease(t, "leases")
 }
 
+// TestReleaseMethodCallsGet test release method calls Get
+func TestReleaseMethodCallsGet(t *testing.T) {
+	objectType := "leases"
+	getCalled := false
+
+	lockMeta := metav1.ObjectMeta{Namespace: "foo", Name: "bar"}
+	recorder := record.NewFakeRecorder(100)
+	resourceLockConfig := rl.ResourceLockConfig{
+		Identity:      "baz",
+		EventRecorder: recorder,
+	}
+	c := &fake.Clientset{}
+	c.AddReactor("get", objectType, func(action fakeclient.Action) (bool, runtime.Object, error) {
+		// flag to check if Get is called
+		getCalled = true
+		return true, createLockObject(t, objectType, action.GetNamespace(), action.(fakeclient.GetAction).GetName(), &rl.LeaderElectionRecord{
+			HolderIdentity:       "baz",
+			LeaseDurationSeconds: 10,
+		}), nil
+	})
+	c.AddReactor("update", objectType, func(action fakeclient.Action) (bool, runtime.Object, error) {
+		return true, action.(fakeclient.UpdateAction).GetObject(), nil
+	})
+
+	lock := &rl.LeaseLock{
+		LeaseMeta:  lockMeta,
+		LockConfig: resourceLockConfig,
+		Client:     c.CoordinationV1(),
+	}
+	lec := LeaderElectionConfig{
+		Lock:          lock,
+		LeaseDuration: 10 * time.Second,
+		Callbacks: LeaderCallbacks{
+			OnNewLeader: func(l string) {},
+		},
+	}
+	observedRawRecord := GetRawRecordOrDie(t, objectType, rl.LeaderElectionRecord{HolderIdentity: "baz"})
+	le := &LeaderElector{
+		config:            lec,
+		observedRecord:    rl.LeaderElectionRecord{HolderIdentity: "baz"},
+		observedRawRecord: observedRawRecord,
+		observedTime:      time.Now(),
+		clock:             clock.RealClock{},
+		metrics:           globalMetricsFactory.newLeaderMetrics(),
+	}
+
+	le.release()
+
+	if !getCalled {
+		t.Errorf("release method does not call Get")
+	}
+}
+
 func TestReleaseOnCancellation_Leases(t *testing.T) {
 	testReleaseOnCancellation(t, "leases")
 }
@@ -791,9 +851,11 @@ func testReleaseOnCancellation(t *testing.T, objectType string) {
 						if lockObj != nil {
 							// Third and more get (first create, second renew) should return our canceled error
 							// FakeClient doesn'"'"'t do anything with the context so we'"'"'re doing this ourselves
-							if gets >= 3 {
-								close(onRenewCalled)
-								<-onRenewResume
+							if gets >= 4 {
+								if gets == 4 {
+									close(onRenewCalled)
+									<-onRenewResume
+								}
 								return true, nil, context.Canceled
 							}
 							return true, lockObj, nil
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/client-go/tools/leaderelection/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestReleaseLeaseLeases", "TestReleaseMethodCallsGet"]
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
