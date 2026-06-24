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
go test -json -count=1 ./staging/src/k8s.io/kubectl/pkg/cmd/apply/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestApplyDryRunClientMergesWithServerState"]
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
