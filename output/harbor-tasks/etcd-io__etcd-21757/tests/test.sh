#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/traceutil/trace_test.go b/pkg/traceutil/trace_test.go
index 395a1e0bb02d..10f8b2b192a1 100644
--- a/pkg/traceutil/trace_test.go
+++ b/pkg/traceutil/trace_test.go
@@ -93,10 +93,11 @@ func TestCreate(t *testing.T) {
 
 func TestLog(t *testing.T) {
 	tests := []struct {
-		name        string
-		trace       *Trace
-		fields      []Field
-		expectedMsg []string
+		name           string
+		trace          *Trace
+		fields         []Field
+		expectedMsg    []string
+		notExpectedMsg []string
 	}{
 		{
 			name: "When dump all logs",
@@ -135,12 +136,18 @@ func TestLog(t *testing.T) {
 				{"count", 1},
 			},
 			expectedMsg: []string{
-				"Test",
+				// stable message name
+				"\"trace\"",
+				// operation and trace_id emitted as structured fields
+				"\"operation\":\"Test\"",
+				"\"trace_id\":",
 				"msg1", "msg2",
 				"traceKey1:traceValue1", "count:1",
 				"stepKey1:stepValue1", "stepKey2:stepValue2",
 				"\"step_count\":2",
 			},
+			// step entries must not embed the trace ID inline
+			notExpectedMsg: []string{"trace["},
 		},
 		{
 			name: "When trace has subtrace",
@@ -178,13 +185,16 @@ func TestLog(t *testing.T) {
 				{"count", 1},
 			},
 			expectedMsg: []string{
-				"Test",
+				"\"trace\"",
+				"\"operation\":\"Test\"",
+				"\"trace_id\":",
 				"msg1", "msg2", "submsg",
 				"traceKey1:traceValue1", "count:1",
 				"stepKey1:stepValue1", "stepKey2:stepValue2", "subStepKey:subStepValue",
 				"beginSubTrace:true", "endSubTrace:true",
 				"\"step_count\":3",
 			},
+			notExpectedMsg: []string{"trace["},
 		},
 	}
 
@@ -209,6 +219,9 @@ func TestLog(t *testing.T) {
 			for _, msg := range tt.expectedMsg {
 				assert.Truef(t, bytes.Contains(data, []byte(msg)), "Expected to find %v in log", msg)
 			}
+			for _, msg := range tt.notExpectedMsg {
+				assert.Falsef(t, bytes.Contains(data, []byte(msg)), "Expected NOT to find %v in log", msg)
+			}
 		})
 	}
 }
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/traceutil/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestLog"]

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
