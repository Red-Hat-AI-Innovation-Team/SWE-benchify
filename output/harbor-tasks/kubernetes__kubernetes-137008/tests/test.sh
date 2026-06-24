#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/podcertificate/podcertificatemanager_test.go b/pkg/kubelet/podcertificate/podcertificatemanager_test.go
index 4d9469a2f1696..7dca0cab4f236 100644
--- a/pkg/kubelet/podcertificate/podcertificatemanager_test.go
+++ b/pkg/kubelet/podcertificate/podcertificatemanager_test.go
@@ -182,6 +182,19 @@ func TestTransitionInitialToWait(t *testing.T) {
 	if diff := cmp.Diff(gotPCRClone, wantPCR); diff != "" {
 		t.Fatalf("PodCertificateManager created a bad PCR; diff (-got +want)\n%s", diff)
 	}
+
+	// Verify OwnerReferences are set correctly for garbage collection.
+	wantOwnerRefs := []metav1.OwnerReference{
+		{
+			APIVersion: "v1",
+			Kind:       "Pod",
+			Name:       workloadPod.ObjectMeta.Name,
+			UID:        workloadPod.ObjectMeta.UID,
+		},
+	}
+	if diff := cmp.Diff(gotPCR.ObjectMeta.OwnerReferences, wantOwnerRefs); diff != "" {
+		t.Fatalf("PodCertificateRequest has incorrect OwnerReferences; diff (-got +want)\n%s", diff)
+	}
 }
 
 func TestPCRDeletedWhileWaiting(t *testing.T) {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/podcertificate/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestTransitionInitialToWait"]
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
