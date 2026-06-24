#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/podautoscaler/replica_calculator_test.go b/pkg/controller/podautoscaler/replica_calculator_test.go
index fc164f7c6ab95..6a9fade24af7b 100644
--- a/pkg/controller/podautoscaler/replica_calculator_test.go
+++ b/pkg/controller/podautoscaler/replica_calculator_test.go
@@ -2430,3 +2430,30 @@ func TestCalculateRequests(t *testing.T) {
 		})
 	}
 }
+func TestCalculatePodRequestsFromContainers_NonExistentContainer(t *testing.T) {
+	pod := &v1.Pod{
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      "test-pod",
+			Namespace: testNamespace,
+		},
+		Spec: v1.PodSpec{
+			Containers: []v1.Container{
+				{
+					Name: "container1",
+					Resources: v1.ResourceRequirements{
+						Requests: v1.ResourceList{
+							v1.ResourceCPU: resource.MustParse("100m"),
+						},
+					},
+				},
+			},
+		},
+	}
+
+	request, err := calculatePodRequestsFromContainers(pod, "non-existent-container", v1.ResourceCPU)
+
+	require.Error(t, err, "expected error for non-existent container")
+	expectedErr := "container non-existent-container not found in Pod test-pod"
+	assert.Equal(t, expectedErr, err.Error(), "error message should match expected format")
+	assert.Equal(t, int64(0), request, "request should be 0 when container does not exist")
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/controller/podautoscaler/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestCalculatePodRequestsFromContainers_NonExistentContainer"]
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
