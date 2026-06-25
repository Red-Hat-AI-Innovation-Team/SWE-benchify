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

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["Test"]

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
