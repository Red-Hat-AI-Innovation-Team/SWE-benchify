#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/internal/xds/bootstrap/bootstrap_test.go b/internal/xds/bootstrap/bootstrap_test.go
index 0dd87416a30c..138cf9868564 100644
--- a/internal/xds/bootstrap/bootstrap_test.go
+++ b/internal/xds/bootstrap/bootstrap_test.go
@@ -525,9 +525,8 @@ func (s) TestGetConfiguration_Failure(t *testing.T) {
 	const name = "empty"
 	t.Run(name, func(t *testing.T) {
 		testGetConfigurationWithFileNameEnv(t, name, true, nil)
-		// If both the env vars are empty, a nil config with a nil error must be
-		// returned.
-		testGetConfigurationWithFileContentEnv(t, name, false, nil)
+		// If both the env vars are empty, an error must be returned.
+		testGetConfigurationWithFileContentEnv(t, name, true, nil)
 	})
 }
 
@@ -665,9 +664,9 @@ func (s) TestGetConfiguration_BootstrapEnvPriority(t *testing.T) {
 	envconfig.XDSBootstrapFileContent = ""
 	defer func() { envconfig.XDSBootstrapFileContent = origBootstrapContent }()
 
-	// When both env variables are empty, GetConfiguration should return nil.
-	if cfg, err := GetConfiguration(); err != nil || cfg != nil {
-		t.Errorf("GetConfiguration() returned (%v, %v), want (<nil>, <nil>)", cfg, err)
+	// When both env variables are empty, GetConfiguration should return error.
+	if _, err := GetConfiguration(); err == nil {
+		t.Errorf("GetConfiguration() returned nil, want error")
 	}
 
 	// When one of them is set, it should be used.
diff --git a/internal/xds/xdsclient/pool/pool_ext_test.go b/internal/xds/xdsclient/pool/pool_ext_test.go
index 2150a2703f8b..7889b2defc20 100644
--- a/internal/xds/xdsclient/pool/pool_ext_test.go
+++ b/internal/xds/xdsclient/pool/pool_ext_test.go
@@ -185,11 +185,8 @@ func (s) TestNestedXDSChannel(t *testing.T) {
 	if err != nil {
 		t.Fatalf("Failed to create bootstrap configuration: %v", err)
 	}
-	config, err := bootstrap.NewConfigFromContents(bootstrapContents)
-	if err != nil {
-		t.Fatalf("Failed to parse bootstrap contents: %v", err)
-	}
-	xdsclient.DefaultPool.SetFallbackBootstrapConfig(config)
+
+	testutils.CreateBootstrapFileForTesting(t, bootstrapContents)
 	defer func() { xdsclient.DefaultPool.UnsetBootstrapConfigForTesting() }()
 
 	// Update the management server that holds resources for resolving the real
diff --git a/xds/csds/csds_e2e_test.go b/xds/csds/csds_e2e_test.go
index 252e693dc28c..e73e28ff39f3 100644
--- a/xds/csds/csds_e2e_test.go
+++ b/xds/csds/csds_e2e_test.go
@@ -35,7 +35,6 @@ import (
 	"google.golang.org/grpc/internal/pretty"
 	"google.golang.org/grpc/internal/testutils"
 	"google.golang.org/grpc/internal/testutils/xds/e2e"
-	"google.golang.org/grpc/internal/xds/bootstrap"
 	"google.golang.org/grpc/internal/xds/xdsclient"
 	"google.golang.org/grpc/internal/xds/xdsclient/xdsresource"
 	"google.golang.org/grpc/xds/csds"
@@ -221,14 +220,10 @@ func (s) TestCSDS(t *testing.T) {
 	// Create a bootstrap contents pointing to the above management server.
 	nodeID := uuid.New().String()
 	bootstrapContents := e2e.DefaultBootstrapContents(t, nodeID, mgmtServer.Address)
-	config, err := bootstrap.NewConfigFromContents(bootstrapContents)
-	if err != nil {
-		t.Fatalf("Failed to parse bootstrap contents: %s, %v", string(bootstrapContents), err)
-	}
 	// We use the default xDS client pool here because the CSDS service reports
 	// on the state of the default xDS client which is implicitly managed
 	// within the xdsclient.DefaultPool.
-	xdsclient.DefaultPool.SetFallbackBootstrapConfig(config)
+	testutils.CreateBootstrapFileForTesting(t, bootstrapContents)
 	defer func() { xdsclient.DefaultPool.UnsetBootstrapConfigForTesting() }()
 	// Create two xDS clients, with different names. These should end up
 	// creating two different xDS clients.
@@ -424,14 +419,10 @@ func (s) TestCSDS_NACK(t *testing.T) {
 	// Create a bootstrap contents pointing to the above management server.
 	nodeID := uuid.New().String()
 	bootstrapContents := e2e.DefaultBootstrapContents(t, nodeID, mgmtServer.Address)
-	config, err := bootstrap.NewConfigFromContents(bootstrapContents)
-	if err != nil {
-		t.Fatalf("Failed to parse bootstrap contents: %s, %v", string(bootstrapContents), err)
-	}
 	// We use the default xDS client pool here because the CSDS service reports
 	// on the state of the default xDS client which is implicitly managed
 	// within the xdsclient.DefaultPool.
-	xdsclient.DefaultPool.SetFallbackBootstrapConfig(config)
+	testutils.CreateBootstrapFileForTesting(t, bootstrapContents)
 	defer func() { xdsclient.DefaultPool.UnsetBootstrapConfigForTesting() }()
 	// Create two xDS clients, with different names. These should end up
 	// creating two different xDS clients.
diff --git a/xds/server_test.go b/xds/server_test.go
index df631410a6a1..2a0c6f47523f 100644
--- a/xds/server_test.go
+++ b/xds/server_test.go
@@ -178,7 +178,7 @@ func (s) TestNewServer_Failure(t *testing.T) {
 		{
 			desc:       "bootstrap env var not set",
 			serverOpts: []grpc.ServerOption{grpc.Creds(xdsCreds), BootstrapContentsForTesting(nil)},
-			wantErr:    "failed to read xDS bootstrap config from env vars",
+			wantErr:    "failed to read xDS bootstrap config",
 		},
 		{
 			desc: "empty bootstrap config",
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./internal/xds/bootstrap/... ./internal/xds/xdsclient/pool/... ./xds/... ./xds/csds/... 2>&1 | tee /tmp/test_output.txt || true

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
