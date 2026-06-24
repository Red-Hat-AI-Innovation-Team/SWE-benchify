#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/xds/internal/clients/xdsclient/xdsclient_test.go b/xds/internal/clients/xdsclient/xdsclient_test.go
index 69b640069d23..073362d02a4d 100644
--- a/xds/internal/clients/xdsclient/xdsclient_test.go
+++ b/xds/internal/clients/xdsclient/xdsclient_test.go
@@ -36,11 +36,6 @@ func (s) TestXDSClient_New(t *testing.T) {
 		config  Config
 		wantErr string
 	}{
-		{
-			name:    "empty node ID",
-			config:  Config{},
-			wantErr: "node ID is empty",
-		},
 		{
 			name: "nil resource types",
 			config: Config{
@@ -75,6 +70,16 @@ func (s) TestXDSClient_New(t *testing.T) {
 			},
 			wantErr: "",
 		},
+		{
+			name: "success with servers and empty nodeID",
+			config: Config{
+				Node:             clients.Node{ID: ""},
+				ResourceTypes:    map[string]ResourceType{xdsresource.V3ListenerURL: listenerType},
+				TransportBuilder: grpctransport.NewBuilder(configs),
+				Servers:          []ServerConfig{{ServerIdentifier: clients.ServerIdentifier{ServerURI: "dummy-server"}}},
+			},
+			wantErr: "",
+		},
 		{
 			name: "success with authorities",
 			config: Config{
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./xds/internal/clients/xdsclient/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["Test"]
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
