#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/libpod/state_test.go b/libpod/state_test.go
index 982ad326d53..e2ba6a0be19 100644
--- a/libpod/state_test.go
+++ b/libpod/state_test.go
@@ -2430,3 +2430,17 @@ func TestGetContainerConfigNonExistentIDFails(t *testing.T) {
 		assert.Error(t, err)
 	})
 }
+
+func TestRemoveVolumeNotInDB(t *testing.T) {
+	runForAllStates(t, func(t *testing.T, state State, _ lock.Manager) {
+		v := &Volume{
+			config: &VolumeConfig{
+				Name: "Test",
+			},
+			valid: true,
+		}
+		err := state.RemoveVolume(v)
+		require.Error(t, err)
+		require.ErrorIs(t, err, define.ErrNoSuchVolume)
+	})
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./libpod/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestRemoveVolumeNotInDB"]
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
