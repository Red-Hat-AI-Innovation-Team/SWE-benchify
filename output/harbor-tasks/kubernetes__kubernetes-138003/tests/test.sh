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
go test -json -count=1 ./pkg/registry/core/pod/storage/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestEviction"]
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
