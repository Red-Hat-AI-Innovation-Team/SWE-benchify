#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go b/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
index ac2e88c761411..cba79c0bc9aad 100644
--- a/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
+++ b/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
@@ -1291,7 +1291,7 @@ func Test_Run_OneVolumeDetachOnUnhealthyNodeWithForceDetachOnUnmountDisabled(t *
 	testForceDetachMetric(t, int(initialForceDetachCountTimeout), metrics.ForceDetachReasonTimeout)
 }
 
-func Test_ReportMultiAttachError(t *testing.T) {
+func Test_ReportWaitingOnDetach(t *testing.T) {
 	type nodeWithPods struct {
 		name     k8stypes.NodeName
 		podNames []string
@@ -1306,7 +1306,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 			[]nodeWithPods{
 				{"node1", []string{"ns1/pod1"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already exclusively attached to one node and can'"'"'t be attached to another"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already exclusively attached to one node, waiting on detach before it can be attached to another node"},
 		},
 		{
 			"pods in the same namespace use the volume",
@@ -1314,7 +1314,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node1", []string{"ns1/pod1"}},
 				{"node2", []string{"ns1/pod2"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by pod(s) pod2"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by pod(s) pod2"},
 		},
 		{
 			"pods in another namespace use the volume",
@@ -1322,7 +1322,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node1", []string{"ns1/pod1"}},
 				{"node2", []string{"ns2/pod2"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by 1 pod(s) in different namespaces"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by 1 pod(s) in different namespaces"},
 		},
 		{
 			"pods both in the same and another namespace use the volume",
@@ -1331,7 +1331,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node2", []string{"ns2/pod2"}},
 				{"node3", []string{"ns1/pod3"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by pod(s) pod3 and 1 pod(s) in different namespaces"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by pod(s) pod3 and 1 pod(s) in different namespaces"},
 		},
 	}
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["Test_ReportWaitingOnDetach"]

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
