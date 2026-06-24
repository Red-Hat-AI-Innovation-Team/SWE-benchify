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
go test -json -count=1 ./util/healthz/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestHealthCheck"]
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
