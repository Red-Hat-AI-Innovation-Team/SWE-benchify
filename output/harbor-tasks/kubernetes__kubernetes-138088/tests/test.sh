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
go test -json -count=1 ./pkg/kubelet/... ./pkg/kubelet/server/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestJournalServerMethodRestriction"]
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
