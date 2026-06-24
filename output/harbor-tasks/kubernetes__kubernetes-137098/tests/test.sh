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

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestCRIListPodCPUAndMemoryStats"]
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
