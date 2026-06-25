#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/registry/core/pod/storage/eviction_test.go b/pkg/registry/core/pod/storage/eviction_test.go
index 4cbdcfede7905..61b11edb865ee 100644
--- a/pkg/registry/core/pod/storage/eviction_test.go
+++ b/pkg/registry/core/pod/storage/eviction_test.go
@@ -258,6 +258,7 @@ func TestEviction(t *testing.T) {
 		expectError         string
 		podPhase            api.PodPhase
 		podName             string
+		expectedCause       metav1.CauseType
 		expectedDeleteCount int
 		podTerminating      bool
 		prc                 *api.PodCondition
@@ -549,6 +550,39 @@ func TestEviction(t *testing.T) {
 				Status: api.ConditionTrue,
 			},
 		},
+		{
+			name: "matching pdbs with negative disruptions allowed, pod running",
+			pdbs: []runtime.Object{&policyv1.PodDisruptionBudget{
+				ObjectMeta: metav1.ObjectMeta{Name: "foo", Namespace: "default"},
+				Spec:       policyv1.PodDisruptionBudgetSpec{Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"a": "true"}}},
+				Status:     policyv1.PodDisruptionBudgetStatus{DisruptionsAllowed: -1},
+			}},
+			eviction:            &policy.Eviction{ObjectMeta: metav1.ObjectMeta{Name: "t-neg", Namespace: "default"}, DeleteOptions: metav1.NewDeleteOptions(0)},
+			expectError:         `poddisruptionbudget.policy "foo" is forbidden: pdb disruptions allowed is negative: Forbidden: The disruption budget foo does not allow evicting pods currently: pdb disruptions allowed is negative`,
+			podPhase:            api.PodRunning,
+			podName:             "t-neg",
+			expectedDeleteCount: 0,
+			expectedCause:       policyv1.DisruptionBudgetCause,
+			policies:            []*policyv1.UnhealthyPodEvictionPolicyType{nil, unhealthyPolicyPtr(policyv1.IfHealthyBudget)},
+		},
+		{
+			name: "matching pdbs with too many disrupted pods, pod running",
+			pdbs: []runtime.Object{&policyv1.PodDisruptionBudget{
+				ObjectMeta: metav1.ObjectMeta{Name: "foo", Namespace: "default"},
+				Spec:       policyv1.PodDisruptionBudgetSpec{Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"a": "true"}}},
+				Status: policyv1.PodDisruptionBudgetStatus{
+					DisruptionsAllowed: 1,
+					DisruptedPods:      makeDisruptedPods(MaxDisruptedPodSize + 1),
+				},
+			}},
+			eviction:            &policy.Eviction{ObjectMeta: metav1.ObjectMeta{Name: "t-big", Namespace: "default"}, DeleteOptions: metav1.NewDeleteOptions(0)},
+			expectError:         `poddisruptionbudget.policy "foo" is forbidden: DisruptedPods map too big - too many evictions not confirmed by PDB controller: Forbidden: The disruption budget foo does not allow evicting pods currently: too many pending evictions not confirmed by PDB controller`,
+			podPhase:            api.PodRunning,
+			podName:             "t-big",
+			expectedDeleteCount: 0,
+			expectedCause:       policyv1.DisruptionBudgetCause,
+			policies:            []*policyv1.UnhealthyPodEvictionPolicyType{nil, unhealthyPolicyPtr(policyv1.IfHealthyBudget)},
+		},
 		{
 			name: "the error includes the reason when the condition.Status is False",
 			pdbs: []runtime.Object{&policyv1.PodDisruptionBudget{
@@ -639,6 +673,11 @@ func TestEviction(t *testing.T) {
 				if tc.expectedDeleteCount != ms.deleteCount {
 					t.Errorf("expected delete count=%v, got %v; name %v", tc.expectedDeleteCount, ms.deleteCount, pod.Name)
 				}
+				if tc.expectedCause != "" {
+					if !apierrors.HasStatusCause(err, tc.expectedCause) {
+						t.Errorf("expected cause %v not found in error %v", tc.expectedCause, err)
+					}
+				}
 			})
 		}
 	}
@@ -1040,3 +1079,11 @@ func errToString(err error) string {
 	}
 	return result
 }
+
+func makeDisruptedPods(n int) map[string]metav1.Time {
+	pods := make(map[string]metav1.Time, n)
+	for i := range n {
+		pods[fmt.Sprintf("pod-%d", i)] = metav1.Now()
+	}
+	return pods
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestEviction"]

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
