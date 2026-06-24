#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux_test.go b/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux_test.go
index 85ef3aeb9f454..68849a380f1f1 100644
--- a/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux_test.go
+++ b/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux_test.go
@@ -278,7 +278,7 @@ func TestManager(t *testing.T) {
 			overrideSystemInhibitDelay:       time.Duration(5 * time.Second),
 			expectedDidOverrideInhibitDelay:  true,
 			expectedPodToGracePeriodOverride: map[string]int64{"normal-pod-nil-grace-period": 5, "critical-pod-nil-grace-period": 0},
-			expectedError:                    fmt.Errorf("unable to update logind InhibitDelayMaxSec to 30s (ShutdownGracePeriod), current value of InhibitDelayMaxSec (5s) is less than requested ShutdownGracePeriod"),
+			expectedError:                    fmt.Errorf("node shutdown manager was timed out after 5 attempts waiting for logind InhibitDelayMaxSec to update to 30s (ShutdownGracePeriod), current value is 5s"),
 		},
 		{
 			desc:                            "override unsuccessful, zero time",
@@ -287,7 +287,7 @@ func TestManager(t *testing.T) {
 			shutdownGracePeriodCriticalPods: time.Duration(5 * time.Second),
 			systemInhibitDelay:              time.Duration(0 * time.Second),
 			overrideSystemInhibitDelay:      time.Duration(0 * time.Second),
-			expectedError:                   fmt.Errorf("unable to update logind InhibitDelayMaxSec to 5s (ShutdownGracePeriod), current value of InhibitDelayMaxSec (0s) is less than requested ShutdownGracePeriod"),
+			expectedError:                   fmt.Errorf("node shutdown manager was timed out after 5 attempts waiting for logind InhibitDelayMaxSec to update to 5s (ShutdownGracePeriod), current value is 0s"),
 		},
 		{
 			desc:                             "no override, all time to critical pods",
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/nodeshutdown/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestManager"]
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
