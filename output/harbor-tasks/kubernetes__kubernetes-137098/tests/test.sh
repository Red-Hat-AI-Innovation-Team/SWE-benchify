#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/stats/cri_stats_provider_test.go b/pkg/kubelet/stats/cri_stats_provider_test.go
index b1deca169c154..eda49127a32b3 100644
--- a/pkg/kubelet/stats/cri_stats_provider_test.go
+++ b/pkg/kubelet/stats/cri_stats_provider_test.go
@@ -688,6 +688,7 @@ func TestCRIListPodCPUAndMemoryStats(t *testing.T) {
 	c0 := containerStatsMap[cName0]
 	assert.Equal(container0.CreatedAt, c0.StartTime.UnixNano())
 	checkCRICPUAndMemoryStats(assert, c0, infos[container0.ContainerStatus.Id].Stats[0])
+	checkSwapStats(t, cName0, seedContainer0, infos[container0.ContainerStatus.Id], c0.Swap)
 	assert.Nil(c0.Rootfs)
 	assert.Nil(c0.Logs)
 	assert.Nil(c0.Accelerators)
@@ -696,6 +697,7 @@ func TestCRIListPodCPUAndMemoryStats(t *testing.T) {
 	c1 := containerStatsMap[cName1]
 	assert.Equal(container1.CreatedAt, c1.StartTime.UnixNano())
 	checkCRICPUAndMemoryStats(assert, c1, infos[container1.ContainerStatus.Id].Stats[0])
+	checkSwapStats(t, cName1, seedContainer1, infos[container1.ContainerStatus.Id], c1.Swap)
 	assert.Nil(c1.Rootfs)
 	assert.Nil(c1.Logs)
 	assert.Nil(c1.Accelerators)
@@ -715,6 +717,7 @@ func TestCRIListPodCPUAndMemoryStats(t *testing.T) {
 	assert.Equal(cName2, c2.Name)
 	assert.Equal(container2.CreatedAt, c2.StartTime.UnixNano())
 	checkCRICPUAndMemoryStats(assert, c2, infos[container2.ContainerStatus.Id].Stats[0])
+	checkSwapStats(t, cName2, seedContainer2, infos[container2.ContainerStatus.Id], c2.Swap)
 	assert.Nil(c2.Rootfs)
 	assert.Nil(c2.Logs)
 	assert.Nil(c2.Accelerators)
@@ -734,6 +737,7 @@ func TestCRIListPodCPUAndMemoryStats(t *testing.T) {
 	assert.Equal(cName3, c3.Name)
 	assert.Equal(container4.CreatedAt, c3.StartTime.UnixNano())
 	checkCRICPUAndMemoryStats(assert, c3, infos[container4.ContainerStatus.Id].Stats[0])
+	checkSwapStats(t, cName3, seedContainer3, infos[container4.ContainerStatus.Id], c3.Swap)
 	assert.Nil(c2.Rootfs)
 	assert.Nil(c2.Logs)
 	assert.Nil(c2.Accelerators)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/stats/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestCRIListPodCPUAndMemoryStats"]

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
