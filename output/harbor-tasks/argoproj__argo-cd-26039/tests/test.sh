#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/util/healthz/healthz_test.go b/util/healthz/healthz_test.go
index 93f68beb83915..e3d30c93646cd 100644
--- a/util/healthz/healthz_test.go
+++ b/util/healthz/healthz_test.go
@@ -5,7 +5,11 @@ import (
 	"net"
 	"net/http"
 	"testing"
+	"time"
 
+	log "github.com/sirupsen/logrus"
+	"github.com/sirupsen/logrus/hooks/test"
+	"github.com/stretchr/testify/assert"
 	"github.com/stretchr/testify/require"
 )
 
@@ -13,7 +17,7 @@ func TestHealthCheck(t *testing.T) {
 	sentinel := false
 	lc := &net.ListenConfig{}
 	ctx := t.Context()
-
+	svcErrMsg := "This is a dummy error"
 	serve := func(c chan<- string) {
 		// listen on first available dynamic (unprivileged) port
 		listener, err := lc.Listen(ctx, "tcp", ":0")
@@ -27,7 +31,7 @@ func TestHealthCheck(t *testing.T) {
 		mux := http.NewServeMux()
 		ServeHealthCheck(mux, func(_ *http.Request) error {
 			if sentinel {
-				return errors.New("This is a dummy error")
+				return errors.New(svcErrMsg)
 			}
 			return nil
 		})
@@ -52,10 +56,26 @@ func TestHealthCheck(t *testing.T) {
 	require.Equalf(t, http.StatusOK, resp.StatusCode, "Was expecting status code 200 from health check, but got %d instead", resp.StatusCode)
 
 	sentinel = true
+	hook := test.NewGlobal()
 
 	req, err = http.NewRequestWithContext(ctx, http.MethodGet, server+"/healthz", http.NoBody)
 	require.NoError(t, err)
 	resp, err = http.DefaultClient.Do(req)
 	require.NoError(t, err)
 	require.Equalf(t, http.StatusServiceUnavailable, resp.StatusCode, "Was expecting status code 503 from health check, but got %d instead", resp.StatusCode)
+	assert.NotEmpty(t, hook.Entries, "Was expecting at least one log entry from health check, but got none")
+	expectedMsg := "Error serving health check request"
+	var foundEntry log.Entry
+	for _, entry := range hook.Entries {
+		if entry.Level == log.ErrorLevel &&
+			entry.Message == expectedMsg {
+			foundEntry = entry
+			break
+		}
+	}
+	require.NotEmpty(t, foundEntry, "Expected an error message '"'"'%s'"'"', but it was'"'"'t found", expectedMsg)
+	actualErr, ok := foundEntry.Data["error"].(error)
+	require.True(t, ok, "Expected '"'"'error'"'"' field to contain an error, but it doesn'"'"'t")
+	assert.Equal(t, svcErrMsg, actualErr.Error(), "expected original error message '"'"'"+svcErrMsg+"'"'"', but got '"'"'"+actualErr.Error()+"'"'"'")
+	assert.Greater(t, foundEntry.Data["duration"].(time.Duration), time.Duration(0))
 }
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test ./... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestHealthCheck"]

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
