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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestComputePodActionsWithContainerRestartRules"]

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
