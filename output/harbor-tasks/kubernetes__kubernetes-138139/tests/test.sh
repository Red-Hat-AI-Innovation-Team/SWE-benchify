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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestGenerateContainerConfigWithMemoryQoSEnforced"]

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
