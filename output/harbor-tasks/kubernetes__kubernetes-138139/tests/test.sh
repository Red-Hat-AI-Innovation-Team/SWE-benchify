#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/kuberuntime/kuberuntime_container_linux_test.go b/pkg/kubelet/kuberuntime/kuberuntime_container_linux_test.go
index f28e487aecd9d..fcafa1f91df8e 100644
--- a/pkg/kubelet/kuberuntime/kuberuntime_container_linux_test.go
+++ b/pkg/kubelet/kuberuntime/kuberuntime_container_linux_test.go
@@ -613,6 +613,26 @@ func TestGenerateContainerConfigWithMemoryQoSEnforced(t *testing.T) {
 			},
 		},
 	}
+
+	// BestEffort: no memory request or limit (kubernetes/kubernetes#137685).
+	pod3 := &v1.Pod{
+		ObjectMeta: metav1.ObjectMeta{
+			UID:       "87654321",
+			Name:      "besteffort",
+			Namespace: "new",
+		},
+		Spec: v1.PodSpec{
+			Containers: []v1.Container{
+				{
+					Name:            "foo",
+					Image:           "busybox",
+					ImagePullPolicy: v1.PullIfNotPresent,
+					Command:         []string{"testCommand"},
+					WorkingDir:      "testWorkingDir",
+				},
+			},
+		},
+	}
 	pageSize := int64(os.Getpagesize())
 	memoryNodeAllocatable := resource.MustParse(fakeNodeAllocatableMemory)
 	pod1MemoryHigh := int64(math.Floor(
@@ -621,6 +641,8 @@ func TestGenerateContainerConfigWithMemoryQoSEnforced(t *testing.T) {
 	pod2MemoryHigh := int64(math.Floor(
 		float64(podRequestMemory.Value())+
 			(float64(memoryNodeAllocatable.Value())-float64(podRequestMemory.Value()))*float64(m.memoryThrottlingFactor))/float64(pageSize)) * pageSize
+	pod3MemoryHigh := int64(math.Floor(
+		float64(memoryNodeAllocatable.Value())*float64(m.memoryThrottlingFactor))/float64(pageSize)) * pageSize
 
 	type expectedResult struct {
 		containerConfig *runtimeapi.LinuxContainerConfig
@@ -629,6 +651,7 @@ func TestGenerateContainerConfigWithMemoryQoSEnforced(t *testing.T) {
 	}
 	l1, _ := m.generateLinuxContainerConfig(tCtx, &pod1.Spec.Containers[0], pod1, new(int64), "", nil, true)
 	l2, _ := m.generateLinuxContainerConfig(tCtx, &pod2.Spec.Containers[0], pod2, new(int64), "", nil, true)
+	l3, _ := m.generateLinuxContainerConfig(tCtx, &pod3.Spec.Containers[0], pod3, new(int64), "", nil, true)
 	tests := []struct {
 		name     string
 		pod      *v1.Pod
@@ -652,6 +675,15 @@ func TestGenerateContainerConfigWithMemoryQoSEnforced(t *testing.T) {
 				int64(pod2MemoryHigh),
 			},
 		},
+		{
+			name: "BestEffortUsesNodeAllocatableForMemoryHigh",
+			pod:  pod3,
+			expected: &expectedResult{
+				l3,
+				0,
+				int64(pod3MemoryHigh),
+			},
+		},
 	}
 
 	for _, test := range tests {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/kuberuntime/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestGenerateContainerConfigWithMemoryQoSEnforced"]
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
