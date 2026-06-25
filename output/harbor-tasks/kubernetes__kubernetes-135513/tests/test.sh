#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply_test.go b/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply_test.go
index 50e1f56899379..af12657a0608a 100644
--- a/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply_test.go
+++ b/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply_test.go
@@ -2204,6 +2204,77 @@ func TestDontAllowForceApplyWithServerSide(t *testing.T) {
 	t.Fatalf(`expected error "%s"`, expectedError)
 }
 
+func TestApplyDryRunClientMergesWithServerState(t *testing.T) {
+	// This test verifies that --dry-run=client performs a proper three-way merge:
+	// - Values from the manifest should overwrite server values
+	// - Server-only values (not in manifest) should be preserved
+	//
+	//   Server state:  port=9999, clusterIP=10.0.0.42
+	//   Last applied:  port=9999 (no clusterIP - it'"'"'s server-assigned)
+	//   New manifest:  port=80   (no clusterIP)
+	//
+	// Expected result: port=80 (from manifest), clusterIP=10.0.0.42 (preserved from server)
+	cmdtesting.InitTestErrorHandler(t)
+
+	lastApplied := `{"apiVersion":"v1","kind":"Service","metadata":{"name":"test-service","namespace":"test"},"spec":{"ports":[{"port":9999,"protocol":"TCP"}]}}`
+
+	serverState := &unstructured.Unstructured{
+		Object: map[string]any{
+			"apiVersion": "v1",
+			"kind":       "Service",
+			"metadata": map[string]any{
+				"name":      "test-service",
+				"namespace": "test",
+				"annotations": map[string]any{
+					corev1.LastAppliedConfigAnnotation: lastApplied,
+				},
+			},
+			"spec": map[string]any{
+				"ports":     []any{map[string]any{"port": int64(9999), "protocol": "TCP"}},
+				"clusterIP": "10.0.0.42",
+			},
+		},
+	}
+	serverStateBytes, err := runtime.Encode(unstructured.UnstructuredJSONScheme, serverState)
+	require.NoError(t, err)
+
+	tf := cmdtesting.NewTestFactory().WithNamespace("test")
+	defer tf.Cleanup()
+
+	tf.UnstructuredClient = &fake.RESTClient{
+		NegotiatedSerializer: resource.UnstructuredPlusDefaultContentConfig().NegotiatedSerializer,
+		Client: fake.CreateHTTPClient(func(req *http.Request) (*http.Response, error) {
+			if req.Method == http.MethodGet && req.URL.Path == "/namespaces/test/services/test-service" {
+				return &http.Response{StatusCode: http.StatusOK, Header: cmdtesting.DefaultHeader(), Body: io.NopCloser(bytes.NewReader(serverStateBytes))}, nil
+			}
+			t.Fatalf("unexpected request: %s %s", req.Method, req.URL.Path)
+			return nil, nil
+		}),
+	}
+	tf.ClientConfigVal = cmdtesting.DefaultClientConfig()
+
+	ioStreams, _, outBuf, errBuf := genericiooptions.NewTestIOStreams()
+	cmd := NewCmdApply("kubectl", tf, ioStreams)
+	require.NoError(t, cmd.Flags().Set("filename", filenameSVC))
+	require.NoError(t, cmd.Flags().Set("dry-run", "client"))
+	require.NoError(t, cmd.Flags().Set("output", "json"))
+	cmd.Run(cmd, []string{})
+
+	require.Empty(t, errBuf.String())
+
+	result := &unstructured.Unstructured{}
+	require.NoError(t, result.UnmarshalJSON(outBuf.Bytes()))
+
+	ports, _, _ := unstructured.NestedSlice(result.Object, "spec", "ports")
+	require.Len(t, ports, 1)
+	port, _, _ := unstructured.NestedInt64(ports[0].(map[string]any), "port")
+	assert.Equal(t, int64(80), port, "port should come from manifest (was 9999 on server)")
+
+	clusterIP, found, _ := unstructured.NestedString(result.Object, "spec", "clusterIP")
+	assert.True(t, found, "clusterIP should be preserved from server")
+	assert.Equal(t, "10.0.0.42", clusterIP)
+}
+
 func TestDontAllowApplyWithPodGeneratedName(t *testing.T) {
 	expectedError := "error: from testing-: cannot use generate name with apply"
 	cmdutil.BehaviorOnFatal(func(str string, code int) {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestApplyDryRunClientMergesWithServerState"]

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
