#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
index a9078cf5ceac4..a534d2f59d5a9 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
@@ -69,8 +69,10 @@ func mustMarshal(obj interface{}) []byte {
 func TestDecodeMetadataFromStream(t *testing.T) {
 	unknownVersionJSON := `{"apiVersion":"metadata.k8s.io/v99","kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
 	unknownV2JSON := `{"apiVersion":"metadata.k8s.io/v100","kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
+	unknownVersionMissingKindJSON := `{"apiVersion":"metadata.k8s.io/v99","metadata":{"name":"test"}}` + "\n"
 	missingKindJSON := `{"apiVersion":"metadata.resource.k8s.io/v1alpha1","metadata":{"name":"test"}}` + "\n"
 	missingApiversionJSON := `{"kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
+	malformedV1Alpha1JSON := `{"apiVersion":"metadata.resource.k8s.io/v1alpha1","kind":"DeviceMetadata","metadata":{"name":"test"},"requests":"this-should-be-an-array"}` + "\n"
 
 	expectedV1Alpha1 := &v1alpha1.DeviceMetadata{
 		TypeMeta: metav1.TypeMeta{
@@ -150,55 +152,62 @@ func TestDecodeMetadataFromStream(t *testing.T) {
 		"missing-kind": {
 			streamInput: []byte(missingKindJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
 		"missing-apiversion": {
 			streamInput: []byte(missingApiversionJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata object",
+		},
+		"malformed-registered-version": {
+			streamInput: []byte(malformedV1Alpha1JSON),
+			dest:        &v1alpha1.DeviceMetadata{},
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
 		"only-unknown-versions": {
 			streamInput: []byte(unknownVersionJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "no compatible metadata version found in stream (unknown versions: metadata.k8s.io/v99)",
 		},
-		"multiple-unknown-versions": {
-			streamInput: append([]byte(unknownVersionJSON), []byte(unknownV2JSON)...),
+		"unknown-version-missing-kind": {
+			streamInput: []byte(unknownVersionMissingKindJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata.k8s.io/v99",
 		},
-		"unknown-version-then-broken": {
-			streamInput: append([]byte(unknownVersionJSON), []byte(missingKindJSON)...),
+		"multiple-unknown-versions": {
+			streamInput: append([]byte(unknownVersionJSON), []byte(unknownV2JSON)...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "no compatible metadata version found in stream (unknown versions: metadata.k8s.io/v99, metadata.k8s.io/v100)",
 		},
 		"known-version-then-broken": {
 			streamInput: append(validV1Alpha1JSON, []byte("{broken")...),
 			dest:        &v1alpha1.DeviceMetadata{},
 			expected:    expectedV1Alpha1,
 		},
-
-		// Forward compatibility: object-level errors are skipped so
-		// that an older consumer can reach a version it understands.
 		"skips-unknown-version": {
 			streamInput: append([]byte(unknownVersionJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
 			expected:    expectedV1Alpha1,
 		},
-		"skips-missing-kind": {
+		"malformed-registered-then-valid-is-fatal": {
+			streamInput: append([]byte(malformedV1Alpha1JSON), validV1Alpha1JSON...),
+			dest:        &v1alpha1.DeviceMetadata{},
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
+		},
+		"missing-kind-then-valid-is-fatal": {
 			streamInput: append([]byte(missingKindJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
-		"skips-missing-apiversion": {
+		"missing-apiversion-then-valid-is-fatal": {
 			streamInput: append([]byte(missingApiversionJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata object",
 		},
-		"skips-multiple-errors": {
-			streamInput: append(append([]byte(unknownVersionJSON), []byte(missingKindJSON)...), validV1Alpha1JSON...),
+		"unknown-version-then-malformed-is-fatal": {
+			streamInput: append([]byte(unknownVersionJSON), []byte(missingKindJSON)...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
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
f2p = ["TestDecodeMetadataFromStream"]

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
