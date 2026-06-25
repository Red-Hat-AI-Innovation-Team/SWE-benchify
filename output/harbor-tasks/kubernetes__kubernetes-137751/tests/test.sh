#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/cm/cpumanager/state/state_checkpoint_test.go b/pkg/kubelet/cm/cpumanager/state/state_checkpoint_test.go
index 95f79eadb2709..75be69562f592 100644
--- a/pkg/kubelet/cm/cpumanager/state/state_checkpoint_test.go
+++ b/pkg/kubelet/cm/cpumanager/state/state_checkpoint_test.go
@@ -17,6 +17,7 @@ limitations under the License.
 package state
 
 import (
+	"encoding/json"
 	"os"
 	"reflect"
 	"strings"
@@ -27,6 +28,7 @@ import (
 	featuregatetesting "k8s.io/component-base/featuregate/testing"
 	"k8s.io/kubernetes/pkg/features"
 	"k8s.io/kubernetes/pkg/kubelet/checkpointmanager"
+	"k8s.io/kubernetes/pkg/kubelet/checkpointmanager/checksum"
 	"k8s.io/kubernetes/pkg/kubelet/cm/containermap"
 	testutil "k8s.io/kubernetes/pkg/kubelet/cm/cpumanager/state/testing"
 	"k8s.io/kubernetes/test/utils/ktesting"
@@ -637,3 +639,53 @@ func AssertStateEqual(t *testing.T, sf State, sm State) {
 		t.Errorf("State CPU assignments mismatch. Have %s, want %s", cpuassignmentSf, cpuassignmentSm)
 	}
 }
+
+func TestCPUManagerCheckpointV2_MarshalCheckpoint_ForwardCompatibility(t *testing.T) {
+	// 1. Create a V2 checkpoint using the struct defined in the current codebase (1.36+)
+	currentCheckpoint := &CPUManagerCheckpointV2{
+		PolicyName:    "none",
+		DefaultCPUSet: "1-3",
+		Entries:       make(map[string]map[string]string),
+	}
+
+	// Marshal it using the logic that forces the "CPUManagerCheckpoint" name
+	data, err := currentCheckpoint.MarshalCheckpoint()
+	if err != nil {
+		t.Fatalf("Failed to marshal checkpoint: %v", err)
+	}
+
+	// 2. Unmarshal the raw JSON to extract the checksum that was actually written to the file
+	var result map[string]interface{}
+	if err := json.Unmarshal(data, &result); err != nil {
+		t.Fatalf("Failed to unmarshal JSON: %v", err)
+	}
+
+	actualChecksumFloat, ok := result["checksum"].(float64)
+	if !ok {
+		t.Fatalf("Checksum field missing or invalid type")
+	}
+	writtenChecksum := checksum.Checksum(uint64(actualChecksumFloat))
+
+	// 3. Reconstruct how versions 1.35 and earlier would calculate the checksum
+	// by defining a struct with the exact legacy name and fields.
+	type CPUManagerCheckpoint struct {
+		PolicyName    string                       `json:"policyName"`
+		DefaultCPUSet string                       `json:"defaultCpuSet"`
+		Entries       map[string]map[string]string `json:"entries,omitempty"`
+		Checksum      checksum.Checksum            `json:"checksum"`
+	}
+
+	legacyCheckpoint := &CPUManagerCheckpoint{
+		PolicyName:    currentCheckpoint.PolicyName,
+		DefaultCPUSet: currentCheckpoint.DefaultCPUSet,
+		Entries:       currentCheckpoint.Entries,
+	}
+
+	expectedLegacyChecksum := checksum.New(legacyCheckpoint)
+
+	// 4. Assert that the checksum written by our 1.36+ code matches
+	// what a 1.35 Kubelet would expect to see.
+	if writtenChecksum != expectedLegacyChecksum {
+		t.Errorf("Written Checksum %d does not match legacy calculation %d. Forward compatibility broken.", writtenChecksum, expectedLegacyChecksum)
+	}
+}
diff --git a/pkg/kubelet/cm/memorymanager/state/state_checkpoint_test.go b/pkg/kubelet/cm/memorymanager/state/state_checkpoint_test.go
index 860b9c9462eb5..fb4b247b88151 100644
--- a/pkg/kubelet/cm/memorymanager/state/state_checkpoint_test.go
+++ b/pkg/kubelet/cm/memorymanager/state/state_checkpoint_test.go
@@ -17,6 +17,7 @@ limitations under the License.
 package state
 
 import (
+	"encoding/json"
 	"os"
 	"strings"
 	"testing"
@@ -29,6 +30,7 @@ import (
 	featuregatetesting "k8s.io/component-base/featuregate/testing"
 	"k8s.io/kubernetes/pkg/features"
 	"k8s.io/kubernetes/pkg/kubelet/checkpointmanager"
+	"k8s.io/kubernetes/pkg/kubelet/checkpointmanager/checksum"
 	testutil "k8s.io/kubernetes/pkg/kubelet/cm/cpumanager/state/testing"
 	"k8s.io/kubernetes/test/utils/ktesting"
 )
@@ -592,3 +594,53 @@ func TestCheckpointStateClear(t *testing.T) {
 		})
 	}
 }
+
+func TestMemoryManagerCheckpointV1_MarshalCheckpoint_ForwardCompatibility(t *testing.T) {
+	// 1. Create a V1 checkpoint using the struct defined in the current codebase (1.36+)
+	currentCheckpoint := &MemoryManagerCheckpointV1{
+		PolicyName:   "none",
+		MachineState: NUMANodeMap{},
+		Entries:      ContainerMemoryAssignments{},
+	}
+
+	// Marshal it using the logic that forces the "MemoryManagerCheckpoint" name
+	data, err := currentCheckpoint.MarshalCheckpoint()
+	if err != nil {
+		t.Fatalf("Failed to marshal checkpoint: %v", err)
+	}
+
+	// 2. Unmarshal the raw JSON to extract the checksum that was actually written to the file
+	var result map[string]interface{}
+	if err := json.Unmarshal(data, &result); err != nil {
+		t.Fatalf("Failed to unmarshal JSON: %v", err)
+	}
+
+	actualChecksumFloat, ok := result["checksum"].(float64)
+	if !ok {
+		t.Fatalf("Checksum field missing or invalid type")
+	}
+	writtenChecksum := checksum.Checksum(uint64(actualChecksumFloat))
+
+	// 3. Reconstruct how versions 1.35 and earlier would calculate the checksum
+	// by defining a struct with the exact legacy name and fields.
+	type MemoryManagerCheckpoint struct {
+		PolicyName   string                     `json:"policyName"`
+		MachineState NUMANodeMap                `json:"machineState"`
+		Entries      ContainerMemoryAssignments `json:"entries,omitempty"`
+		Checksum     checksum.Checksum          `json:"checksum"`
+	}
+
+	legacyCheckpoint := &MemoryManagerCheckpoint{
+		PolicyName:   currentCheckpoint.PolicyName,
+		MachineState: currentCheckpoint.MachineState,
+		Entries:      currentCheckpoint.Entries,
+	}
+
+	expectedLegacyChecksum := checksum.New(legacyCheckpoint)
+
+	// 4. Assert that the checksum written by our 1.36+ code matches
+	// what a 1.35 Kubelet would expect to see.
+	if writtenChecksum != expectedLegacyChecksum {
+		t.Errorf("Written Checksum %d does not match legacy calculation %d. Forward compatibility broken.", writtenChecksum, expectedLegacyChecksum)
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestCPUManagerCheckpointV2_MarshalCheckpoint_ForwardCompatibility", "TestMemoryManagerCheckpointV1_MarshalCheckpoint_ForwardCompatibility"]

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
