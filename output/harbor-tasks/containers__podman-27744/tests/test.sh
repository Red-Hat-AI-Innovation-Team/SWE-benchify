#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/libpod/container_healthcheck_test.go b/libpod/container_healthcheck_test.go
new file mode 100644
index 00000000000..7f02e970edf
--- /dev/null
+++ b/libpod/container_healthcheck_test.go
@@ -0,0 +1,36 @@
+//go:build !remote
+
+package libpod
+
+import (
+	"testing"
+
+	"github.com/stretchr/testify/assert"
+	manifest "go.podman.io/image/v5/manifest"
+)
+
+func TestHasHealthCheckCases(t *testing.T) {
+	ctr := &Container{config: &ContainerConfig{}}
+
+	// nil HealthCheckConfig -> false
+	ctr.config.HealthCheckConfig = nil
+	assert.False(t, ctr.HasHealthCheck(), "nil HealthCheckConfig should not be considered a healthcheck")
+
+	// Test == nil -> false
+	ctr.config.HealthCheckConfig = &manifest.Schema2HealthConfig{Test: nil}
+	assert.False(t, ctr.HasHealthCheck(), "nil Test slice should not be considered a healthcheck")
+
+	// empty slice -> false
+	ctr.config.HealthCheckConfig = &manifest.Schema2HealthConfig{Test: []string{}}
+	assert.False(t, ctr.HasHealthCheck(), "empty Test slice should not be considered a healthcheck")
+
+	// NONE sentinel -> false (case-insensitive)
+	ctr.config.HealthCheckConfig = &manifest.Schema2HealthConfig{Test: []string{"NONE"}}
+	assert.False(t, ctr.HasHealthCheck(), "[\"NONE\"] sentinel should not be considered a healthcheck")
+	ctr.config.HealthCheckConfig = &manifest.Schema2HealthConfig{Test: []string{"none"}}
+	assert.False(t, ctr.HasHealthCheck(), "[\"none\"] sentinel should not be considered a healthcheck")
+
+	// valid CMD form -> true
+	ctr.config.HealthCheckConfig = &manifest.Schema2HealthConfig{Test: []string{"CMD-SHELL", "echo hi"}}
+	assert.True(t, ctr.HasHealthCheck(), "non-empty Test with command should be considered a healthcheck")
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./libpod/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestHasHealthCheckCases"]
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
