#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
index a9078cf5ceac4..a534d2f59d5a9 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode_test.go
@@ -69,8 +69,10 @@ func mustMarshal(obj interface{}) []byte {
 func TestDecodeMetadataFromStream(t *testing.T) {
 	unknownVersionJSON := `{"apiVersion":"metadata.k8s.io/v99","kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
 	unknownV2JSON := `{"apiVersion":"metadata.k8s.io/v100","kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
+	unknownVersionMissingKindJSON := `{"apiVersion":"metadata.k8s.io/v99","metadata":{"name":"test"}}` + "\n"
 	missingKindJSON := `{"apiVersion":"metadata.resource.k8s.io/v1alpha1","metadata":{"name":"test"}}` + "\n"
 	missingApiversionJSON := `{"kind":"DeviceMetadata","metadata":{"name":"test"}}` + "\n"
+	malformedV1Alpha1JSON := `{"apiVersion":"metadata.resource.k8s.io/v1alpha1","kind":"DeviceMetadata","metadata":{"name":"test"},"requests":"this-should-be-an-array"}` + "\n"
 
 	expectedV1Alpha1 := &v1alpha1.DeviceMetadata{
 		TypeMeta: metav1.TypeMeta{
@@ -150,55 +152,62 @@ func TestDecodeMetadataFromStream(t *testing.T) {
 		"missing-kind": {
 			streamInput: []byte(missingKindJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
 		"missing-apiversion": {
 			streamInput: []byte(missingApiversionJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata object",
+		},
+		"malformed-registered-version": {
+			streamInput: []byte(malformedV1Alpha1JSON),
+			dest:        &v1alpha1.DeviceMetadata{},
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
 		"only-unknown-versions": {
 			streamInput: []byte(unknownVersionJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "no compatible metadata version found in stream (unknown versions: metadata.k8s.io/v99)",
 		},
-		"multiple-unknown-versions": {
-			streamInput: append([]byte(unknownVersionJSON), []byte(unknownV2JSON)...),
+		"unknown-version-missing-kind": {
+			streamInput: []byte(unknownVersionMissingKindJSON),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "decode metadata.k8s.io/v99",
 		},
-		"unknown-version-then-broken": {
-			streamInput: append([]byte(unknownVersionJSON), []byte(missingKindJSON)...),
+		"multiple-unknown-versions": {
+			streamInput: append([]byte(unknownVersionJSON), []byte(unknownV2JSON)...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expectError: "no compatible metadata version found in stream",
+			expectError: "no compatible metadata version found in stream (unknown versions: metadata.k8s.io/v99, metadata.k8s.io/v100)",
 		},
 		"known-version-then-broken": {
 			streamInput: append(validV1Alpha1JSON, []byte("{broken")...),
 			dest:        &v1alpha1.DeviceMetadata{},
 			expected:    expectedV1Alpha1,
 		},
-
-		// Forward compatibility: object-level errors are skipped so
-		// that an older consumer can reach a version it understands.
 		"skips-unknown-version": {
 			streamInput: append([]byte(unknownVersionJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
 			expected:    expectedV1Alpha1,
 		},
-		"skips-missing-kind": {
+		"malformed-registered-then-valid-is-fatal": {
+			streamInput: append([]byte(malformedV1Alpha1JSON), validV1Alpha1JSON...),
+			dest:        &v1alpha1.DeviceMetadata{},
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
+		},
+		"missing-kind-then-valid-is-fatal": {
 			streamInput: append([]byte(missingKindJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
-		"skips-missing-apiversion": {
+		"missing-apiversion-then-valid-is-fatal": {
 			streamInput: append([]byte(missingApiversionJSON), validV1Alpha1JSON...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata object",
 		},
-		"skips-multiple-errors": {
-			streamInput: append(append([]byte(unknownVersionJSON), []byte(missingKindJSON)...), validV1Alpha1JSON...),
+		"unknown-version-then-malformed-is-fatal": {
+			streamInput: append([]byte(unknownVersionJSON), []byte(missingKindJSON)...),
 			dest:        &v1alpha1.DeviceMetadata{},
-			expected:    expectedV1Alpha1,
+			expectError: "decode metadata.resource.k8s.io/v1alpha1",
 		},
 	}
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestDecodeMetadataFromStream"]
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
