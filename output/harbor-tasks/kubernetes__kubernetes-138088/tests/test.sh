#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/kubelet_server_journal_test.go b/pkg/kubelet/kubelet_server_journal_test.go
index bf42f685f453a..03705f7b435f7 100644
--- a/pkg/kubelet/kubelet_server_journal_test.go
+++ b/pkg/kubelet/kubelet_server_journal_test.go
@@ -19,6 +19,8 @@ package kubelet
 import (
 	"bytes"
 	"context"
+	"net/http"
+	"net/http/httptest"
 	"net/url"
 	"os"
 	"path/filepath"
@@ -34,6 +36,48 @@ import (
 	"k8s.io/utils/ptr"
 )
 
+func TestJournalServerMethodRestriction(t *testing.T) {
+	tests := []struct {
+		name           string
+		method         string
+		expectedStatus int
+		expectedAllow  string
+	}{
+		{
+			name:           "GET is allowed by method gate",
+			method:         http.MethodGet,
+			expectedStatus: http.StatusBadRequest,
+		},
+		{
+			name:           "POST is allowed by method gate",
+			method:         http.MethodPost,
+			expectedStatus: http.StatusBadRequest,
+		},
+		{
+			name:           "PUT is rejected",
+			method:         http.MethodPut,
+			expectedStatus: http.StatusMethodNotAllowed,
+			expectedAllow:  "GET, POST",
+		},
+	}
+
+	for _, tt := range tests {
+		t.Run(tt.name, func(t *testing.T) {
+			// invalid sinceTime forces an early validation error (400), so we only
+			// validate method gating and avoid invoking external log commands.
+			req := httptest.NewRequest(tt.method, "/logs?sinceTime=invalid", nil)
+			recorder := httptest.NewRecorder()
+
+			journal.ServeHTTP(recorder, req)
+
+			assert.Equal(t, tt.expectedStatus, recorder.Code)
+			if tt.expectedAllow != "" {
+				assert.Equal(t, tt.expectedAllow, recorder.Header().Get("Allow"))
+			}
+		})
+	}
+}
+
 func Test_getLoggingCmd(t *testing.T) {
 	var emptyCmdEnv []string
 	tests := []struct {
diff --git a/pkg/kubelet/server/server_test.go b/pkg/kubelet/server/server_test.go
index 1875897f01b0b..b9d1093b52388 100644
--- a/pkg/kubelet/server/server_test.go
+++ b/pkg/kubelet/server/server_test.go
@@ -421,13 +421,11 @@ func TestServeLogs(t *testing.T) {
 	defer fw.testHTTPServer.Close()
 
 	content := string(`<pre><a href="kubelet.log">kubelet.log</a><a href="google.log">google.log</a></pre>`)
-
 	fw.fakeKubelet.logFunc = func(w http.ResponseWriter, req *http.Request) {
 		w.WriteHeader(http.StatusOK)
 		w.Header().Add("Content-Type", "text/html")
 		w.Write([]byte(content))
 	}
-
 	resp, err := http.Get(fw.testHTTPServer.URL + "/logs/")
 	if err != nil {
 		t.Fatalf("Got error GETing: %v", err)
@@ -443,6 +441,38 @@ func TestServeLogs(t *testing.T) {
 	if !strings.Contains(result, "kubelet.log") || !strings.Contains(result, "google.log") {
 		t.Errorf("Received wrong data: %s", result)
 	}
+
+}
+
+func TestGETOnlyEndpointsRejectPostWithAllowHeader(t *testing.T) {
+	tCtx := ktesting.Init(t)
+	fw := newServerTest(tCtx)
+	defer fw.testHTTPServer.Close()
+
+	tests := []struct {
+		name string
+		path string
+	}{
+		{name: "pods", path: "/pods/"},
+		{name: "containerLogs", path: "/containerLogs/default/mypod/mycontainer"},
+		{name: "runningpods", path: "/runningpods/"},
+		{name: "logs", path: "/logs/"},
+		{name: "pprof", path: "/debug/pprof/profile?seconds=1"},
+	}
+
+	for _, tt := range tests {
+		t.Run(tt.name, func(t *testing.T) {
+			req, err := http.NewRequest(http.MethodPost, fw.testHTTPServer.URL+tt.path, nil)
+			require.NoError(t, err)
+
+			resp, err := http.DefaultClient.Do(req)
+			require.NoError(t, err)
+			defer resp.Body.Close() //nolint:errcheck
+
+			assert.Equal(t, http.StatusMethodNotAllowed, resp.StatusCode)
+			assert.Equal(t, http.MethodGet, resp.Header.Get("Allow"))
+		})
+	}
 }
 
 func TestServeRunInContainer(t *testing.T) {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestJournalServerMethodRestriction"]

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
