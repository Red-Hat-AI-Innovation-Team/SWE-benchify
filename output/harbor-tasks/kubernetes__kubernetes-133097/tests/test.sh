#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/registry/core/pod/storage/eviction_test.go b/pkg/registry/core/pod/storage/eviction_test.go
index a9d398ff7cd22..4cbdcfede7905 100644
--- a/pkg/registry/core/pod/storage/eviction_test.go
+++ b/pkg/registry/core/pod/storage/eviction_test.go
@@ -45,7 +45,7 @@ import (
 	"k8s.io/utils/ptr"
 )
 
-func TestEviction(t *testing.T) {
+func TestEvictionWithETCD(t *testing.T) {
 	testcases := []struct {
 		name     string
 		pdbs     []runtime.Object
@@ -248,7 +248,7 @@ func TestEviction(t *testing.T) {
 	}
 }
 
-func TestEvictionIgnorePDB(t *testing.T) {
+func TestEviction(t *testing.T) {
 	testcases := []struct {
 		name     string
 		pdbs     []runtime.Object
@@ -521,6 +521,64 @@ func TestEvictionIgnorePDB(t *testing.T) {
 				Status: api.ConditionTrue,
 			},
 		},
+		{
+			name: "the error is about sync failure when the condition reason is SyncFailedReason",
+			pdbs: []runtime.Object{&policyv1.PodDisruptionBudget{
+				ObjectMeta: metav1.ObjectMeta{Name: "foo", Namespace: "default"},
+				Spec:       policyv1.PodDisruptionBudgetSpec{Selector: &metav1.LabelSelector{}},
+				Status: policyv1.PodDisruptionBudgetStatus{
+					DisruptionsAllowed: 0,
+					Conditions: []metav1.Condition{
+						{
+							Type:    policyv1.DisruptionAllowedCondition,
+							Status:  metav1.ConditionFalse,
+							Reason:  policyv1.SyncFailedReason,
+							Message: "hoge",
+						},
+					},
+				},
+			}},
+			eviction:            &policy.Eviction{ObjectMeta: metav1.ObjectMeta{Name: "t12", Namespace: "default"}, DeleteOptions: metav1.NewDeleteOptions(0)},
+			expectError:         "Cannot evict pod as it would violate the pod'"'"'s disruption budget.: TooManyRequests: The disruption budget foo does not allow evicting pods currently because it failed sync: hoge",
+			podName:             "t12",
+			expectedDeleteCount: 0,
+			podTerminating:      false,
+			podPhase:            api.PodRunning,
+			prc: &api.PodCondition{
+				Type:   api.PodReady,
+				Status: api.ConditionTrue,
+			},
+		},
+		{
+			name: "the error includes the reason when the condition.Status is False",
+			pdbs: []runtime.Object{&policyv1.PodDisruptionBudget{
+				ObjectMeta: metav1.ObjectMeta{Name: "foo", Namespace: "default"},
+				Spec:       policyv1.PodDisruptionBudgetSpec{Selector: &metav1.LabelSelector{}},
+				Status: policyv1.PodDisruptionBudgetStatus{
+					DisruptionsAllowed: 0,
+					CurrentHealthy:     4,
+					DesiredHealthy:     3,
+					Conditions: []metav1.Condition{
+						{
+							Type:    policyv1.DisruptionAllowedCondition,
+							Status:  metav1.ConditionFalse,
+							Reason:  "bar-reason",
+							Message: "hoge",
+						},
+					},
+				},
+			}},
+			eviction:            &policy.Eviction{ObjectMeta: metav1.ObjectMeta{Name: "t12", Namespace: "default"}, DeleteOptions: metav1.NewDeleteOptions(0)},
+			expectError:         "Cannot evict pod as it would violate the pod'"'"'s disruption budget.: TooManyRequests: The disruption budget foo does not allow evicting pods currently (bar-reason): hoge",
+			podName:             "t12",
+			expectedDeleteCount: 0,
+			podTerminating:      false,
+			podPhase:            api.PodRunning,
+			prc: &api.PodCondition{
+				Type:   api.PodReady,
+				Status: api.ConditionTrue,
+			},
+		},
 	}
 
 	for _, unhealthyPodEvictionPolicy := range []*policyv1.UnhealthyPodEvictionPolicyType{unhealthyPolicyPtr(policyv1.AlwaysAllow), nil, unhealthyPolicyPtr(policyv1.IfHealthyBudget)} {
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

def parse_junit_xml(text):
    # Minimal XML parser for JUnit format (no lxml dependency)
    results = {}
    for m in re.finditer(r'<testcase[^>]*name="([^"]*)"[^>]*classname="([^"]*)"[^>]*(/?>)', text):
        name, classname, close = m.groups()
        test_id = f"{classname}.{name}"
        # Check for failure/error child elements
        if close == "/>":
            results[test_id] = "passed"
        else:
            # Find the matching </testcase> and check contents
            start = m.end()
            end = text.find("</testcase>", start)
            block = text[start:end] if end != -1 else ""
            if "<failure" in block or "<error" in block:
                results[test_id] = "failed"
            elif "<skipped" in block:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results

def parse_cargo_test(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            test_id = m.group(1)
            status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_tap(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"(ok|not ok)\s+\d+\s*-?\s*(.*)", line)
        if m:
            status = "passed" if m.group(1) == "ok" else "failed"
            desc = m.group(2).strip()
            if "# SKIP" in desc:
                status = "skipped"
                desc = desc.split("# SKIP")[0].strip()
            results[desc] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
    "junit-xml": parse_junit_xml,
    "cargo-test": parse_cargo_test,
    "tap": parse_tap,
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
