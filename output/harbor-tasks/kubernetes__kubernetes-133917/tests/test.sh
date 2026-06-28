#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/client-go/tools/clientcmd/client_config_test.go b/staging/src/k8s.io/client-go/tools/clientcmd/client_config_test.go
index 4872eadf3d217..baa406f4e459c 100644
--- a/staging/src/k8s.io/client-go/tools/clientcmd/client_config_test.go
+++ b/staging/src/k8s.io/client-go/tools/clientcmd/client_config_test.go
@@ -1222,3 +1222,166 @@ func TestMergeRawConfigDoOverride(t *testing.T) {
 		t.Errorf("Expected namespace %v, got %v", config.Contexts["clean"].Namespace, act.Contexts["clean"].Namespace)
 	}
 }
+
+func TestClientCertOverrideData(t *testing.T) {
+	// Test that when overrides contain cert/key file paths or data fields,
+	// the corresponding fields are properly handled to avoid validation conflicts
+	// in particular code in DirectClientConfig::getAuthInfo.
+	// This covers both scenarios: overrides with file paths (which clear data fields)
+	// and overrides with data fields (which clear file paths).
+
+	testCases := []struct {
+		name        string
+		description string
+		setupTest   func(t *testing.T) (*clientcmdapi.Config, *ConfigOverrides, func())
+		validate    func(t *testing.T, authInfo *clientcmdapi.AuthInfo)
+	}{
+		{
+			name:        "override-with-file-paths",
+			description: "Test override with cert/key file paths",
+			setupTest: func(t *testing.T) (*clientcmdapi.Config, *ConfigOverrides, func()) {
+				certFile, err := os.CreateTemp("", "test-client-*.crt")
+				if err != nil {
+					t.Fatalf("Failed to create temp cert file: %v", err)
+				}
+
+				keyFile, err := os.CreateTemp("", "test-client-*.key")
+				if err != nil {
+					t.Fatalf("Failed to create temp key file: %v", err)
+				}
+
+				if err := os.WriteFile(certFile.Name(), []byte("dummy-cert-content"), 0600); err != nil {
+					t.Fatalf("Failed to write cert file: %v", err)
+				}
+				if err := os.WriteFile(keyFile.Name(), []byte("dummy-key-content"), 0600); err != nil {
+					t.Fatalf("Failed to write key file: %v", err)
+				}
+
+				baseConfig := clientcmdapi.Config{
+					Clusters: map[string]*clientcmdapi.Cluster{
+						"test-cluster": {
+							Server:                   "https://example.com:6443",
+							CertificateAuthorityData: []byte("fake-ca-data"),
+						},
+					},
+					AuthInfos: map[string]*clientcmdapi.AuthInfo{
+						"test-user": {
+							ClientCertificateData: []byte("base-cert-data"),
+							ClientKeyData:         []byte("base-key-data"),
+						},
+					},
+					Contexts: map[string]*clientcmdapi.Context{
+						"test-context": {
+							Cluster:  "test-cluster",
+							AuthInfo: "test-user",
+						},
+					},
+					CurrentContext: "test-context",
+				}
+
+				overrides := &ConfigOverrides{
+					AuthInfo: clientcmdapi.AuthInfo{
+						ClientCertificate:     certFile.Name(),
+						ClientCertificateData: nil,
+						ClientKey:             keyFile.Name(),
+						ClientKeyData:         nil,
+					},
+				}
+
+				cleanup := func() {
+					utiltesting.CloseAndRemove(t, certFile)
+					utiltesting.CloseAndRemove(t, keyFile)
+				}
+
+				return &baseConfig, overrides, cleanup
+			},
+			validate: func(t *testing.T, authInfo *clientcmdapi.AuthInfo) {
+				if authInfo.ClientCertificate == "" {
+					t.Errorf("Expected ClientCertificate file path to be set")
+				}
+				if authInfo.ClientKey == "" {
+					t.Errorf("Expected ClientKey file path to be set")
+				}
+				if authInfo.ClientCertificateData != nil {
+					t.Errorf("Expected ClientCertificateData to be nil when file path is used")
+				}
+				if authInfo.ClientKeyData != nil {
+					t.Errorf("Expected ClientKeyData to be nil when file path is used")
+				}
+			},
+		},
+		{
+			name:        "override-with-data-fields",
+			description: "Test override with cert/key data fields",
+			setupTest: func(t *testing.T) (*clientcmdapi.Config, *ConfigOverrides, func()) {
+				baseConfig := clientcmdapi.Config{
+					Clusters: map[string]*clientcmdapi.Cluster{
+						"test-cluster": {
+							Server:                   "https://example.com:6443",
+							CertificateAuthorityData: []byte("fake-ca-data"),
+						},
+					},
+					AuthInfos: map[string]*clientcmdapi.AuthInfo{
+						"test-user": {
+							ClientCertificate: "/path/to/base-cert.pem",
+							ClientKey:         "/path/to/base-key.pem",
+						},
+					},
+					Contexts: map[string]*clientcmdapi.Context{
+						"test-context": {
+							Cluster:  "test-cluster",
+							AuthInfo: "test-user",
+						},
+					},
+					CurrentContext: "test-context",
+				}
+
+				overrides := &ConfigOverrides{
+					AuthInfo: clientcmdapi.AuthInfo{
+						ClientCertificate:     "",
+						ClientCertificateData: []byte("override-cert-data"),
+						ClientKey:             "",
+						ClientKeyData:         []byte("override-key-data"),
+					},
+				}
+
+				return &baseConfig, overrides, func() {}
+			},
+			validate: func(t *testing.T, authInfo *clientcmdapi.AuthInfo) {
+				if authInfo.ClientCertificate != "" {
+					t.Errorf("Expected ClientCertificate file path to be empty when data is used")
+				}
+				if authInfo.ClientKey != "" {
+					t.Errorf("Expected ClientKey file path to be empty when data is used")
+				}
+				if string(authInfo.ClientCertificateData) != "override-cert-data" {
+					t.Errorf("Expected ClientCertificateData to be '"'"'override-cert-data'"'"', got %s", string(authInfo.ClientCertificateData))
+				}
+				if string(authInfo.ClientKeyData) != "override-key-data" {
+					t.Errorf("Expected ClientKeyData to be '"'"'override-key-data'"'"', got %s", string(authInfo.ClientKeyData))
+				}
+			},
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			baseConfig, overrides, cleanup := tc.setupTest(t)
+			defer cleanup()
+
+			clientConfig := NewNonInteractiveClientConfig(*baseConfig, "test-context", overrides, nil)
+
+			mergedConfig, err := clientConfig.MergedRawConfig()
+			if err != nil {
+				t.Fatalf("MergedRawConfig() failed: %v", err)
+			}
+
+			authInfo := mergedConfig.AuthInfos["test-user"]
+			if authInfo == nil {
+				t.Fatalf("Expected AuthInfo '"'"'test-user'"'"' not found")
+			}
+
+			tc.validate(t, authInfo)
+		})
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/client-go/tools/clientcmd/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestClientCertOverrideData"]

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
