#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/kuberuntime/kuberuntime_manager_test.go b/pkg/kubelet/kuberuntime/kuberuntime_manager_test.go
index 118590b7f9dd7..4dc328bb4998b 100644
--- a/pkg/kubelet/kuberuntime/kuberuntime_manager_test.go
+++ b/pkg/kubelet/kuberuntime/kuberuntime_manager_test.go
@@ -2110,6 +2110,11 @@ func TestComputePodActionsWithInitAndEphemeralContainers(t *testing.T) {
 }
 
 func TestComputePodActionsWithContainerRestartRules(t *testing.T) {
+	// Make sure existing test cases pass with feature enabled
+	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.ContainerRestartRules, true)
+	TestComputePodActions(t)
+	TestComputePodActionsWithInitContainers(t)
+
 	var (
 		containerRestartPolicyAlways    = v1.ContainerRestartPolicyAlways
 		containerRestartPolicyOnFailure = v1.ContainerRestartPolicyOnFailure
@@ -2231,7 +2236,6 @@ func TestComputePodActionsWithContainerRestartRules(t *testing.T) {
 			},
 		},
 	} {
-		featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.ContainerRestartRules, true)
 		pod, status := makeBasePodAndStatus()
 		if test.mutatePodFn != nil {
 			test.mutatePodFn(pod)
diff --git a/test/e2e/node/pods.go b/test/e2e/node/pods.go
index 94171ea245f9b..dd8528bcf741f 100644
--- a/test/e2e/node/pods.go
+++ b/test/e2e/node/pods.go
@@ -718,7 +718,7 @@ var _ = SIGDescribe("Pods Extended (pod generation)", feature.PodObservedGenerat
 	})
 })
 
-var _ = SIGDescribe("Pod Extended (container restart policy)", feature.ContainerRestartRules, framework.WithFeatureGate(features.ContainerRestartRules), func() {
+var _ = SIGDescribe("Pod Extended (container restart policy)", framework.WithFeatureGate(features.ContainerRestartRules), func() {
 	f := framework.NewDefaultFramework("pods")
 	f.NamespacePodSecurityLevel = admissionapi.LevelBaseline
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/kuberuntime/... ./test/e2e/node/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestComputePodActionsWithContainerRestartRules"]
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
