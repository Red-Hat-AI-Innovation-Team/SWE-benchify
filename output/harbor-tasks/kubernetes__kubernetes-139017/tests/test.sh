#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
index b6a3e608d20f4..7c8a0ba21344f 100644
--- a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
+++ b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
@@ -4456,6 +4456,19 @@ func Test_computesScore(t *testing.T) {
 			allocations: nodeAllocation{},
 			expectErr:   true,
 		},
+		"mix-of-allocated-and-unallocated-claims": {
+			claims: []*resourceapi.ResourceClaim{
+				allocatedClaim,
+				pendingClaim2,
+			},
+			allocations: nodeAllocation{
+				allocationResults: []resourceapi.AllocationResult{
+					*allocationResult2,
+				},
+			},
+			expectedScore: 0,
+			expectErr:     false,
+		},
 		"single-request-only-subrequest-allocated": {
 			claims: []*resourceapi.ResourceClaim{
 				st.MakeResourceClaim().
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/scheduler/framework/plugins/dynamicresources/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["Test_computesScore"]
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
