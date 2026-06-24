#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/prober/prober_manager_test.go b/pkg/kubelet/prober/prober_manager_test.go
index 2bb0c7faf6f3d..c7744d0892fae 100644
--- a/pkg/kubelet/prober/prober_manager_test.go
+++ b/pkg/kubelet/prober/prober_manager_test.go
@@ -133,6 +133,57 @@ func TestAddRemovePods(t *testing.T) {
 	}
 }
 
+func TestAddPodContinuesAfterExistingWorker(t *testing.T) {
+	ctx := ktesting.Init(t)
+
+	pod := v1.Pod{
+		ObjectMeta: metav1.ObjectMeta{
+			UID: "test_pod",
+		},
+		Spec: v1.PodSpec{
+			Containers: []v1.Container{
+				{
+					Name:           "container_a",
+					ReadinessProbe: defaultProbe,
+				},
+				{
+					Name:           "container_b",
+					ReadinessProbe: defaultProbe,
+				},
+			},
+		},
+	}
+
+	m := newTestManager()
+	defer cleanup(t, m)
+
+	// First AddPod: registers workers for both containers.
+	m.AddPod(ctx, &pod)
+	if err := expectProbes(m, []probeKey{
+		{"test_pod", "container_a", readiness},
+		{"test_pod", "container_b", readiness},
+	}); err != nil {
+		t.Fatalf("after first AddPod: %v", err)
+	}
+
+	// Simulate container_b'"'"'s worker being removed while container_a'"'"'s is still present.
+	m.workerLock.Lock()
+	delete(m.workers, probeKey{"test_pod", "container_b", readiness})
+	m.workerLock.Unlock()
+
+	// Second AddPod: should re-register container_b'"'"'s missing worker.
+	// Previously, hitting container_a'"'"'s existing worker caused an early return,
+	// so container_b was never re-registered.
+	m.AddPod(ctx, &pod)
+
+	if err := expectProbes(m, []probeKey{
+		{"test_pod", "container_a", readiness},
+		{"test_pod", "container_b", readiness},
+	}); err != nil {
+		t.Errorf("container_b worker was not re-registered after second AddPod: %v", err)
+	}
+}
+
 func TestAddRemovePodsWithRestartableInitContainer(t *testing.T) {
 	m := newTestManager()
 	defer cleanup(t, m)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/prober/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestAddPodContinuesAfterExistingWorker"]
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
