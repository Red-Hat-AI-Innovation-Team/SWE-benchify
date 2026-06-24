#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/volume/csi/csi_block_test.go b/pkg/volume/csi/csi_block_test.go
index 3b06ff1c7c771..deffc6b39f902 100644
--- a/pkg/volume/csi/csi_block_test.go
+++ b/pkg/volume/csi/csi_block_test.go
@@ -18,6 +18,7 @@ package csi
 
 import (
 	"context"
+	"errors"
 	"fmt"
 	"os"
 	"path/filepath"
@@ -491,6 +492,46 @@ func TestBlockMapperMapPodDeviceNoClientError(t *testing.T) {
 	}
 }
 
+func TestBlockMapperMapPodDeviceGetStageSecretsError(t *testing.T) {
+	transientError := volumetypes.NewTransientOperationFailure("")
+	plug, tmpDir := newTestPlugin(t, nil)
+	defer func() {
+		if err := os.RemoveAll(tmpDir); err != nil {
+			t.Error(err)
+		}
+	}()
+
+	csiMapper, _, pv, err := prepareBlockMapperTest(plug, "test-pv", t)
+	if err != nil {
+		t.Fatalf("Failed to make a new Mapper: %v", err)
+	}
+
+	// set a stage secret for the pv
+	pv.Spec.PersistentVolumeSource.CSI.NodePublishSecretRef = &api.SecretReference{
+		Name:      "foo",
+		Namespace: "default",
+	}
+	pvName := pv.GetName()
+	nodeName := string(plug.host.GetNodeName())
+
+	csiMapper.csiClient = setupClient(t, true)
+
+	attachID := getAttachmentName(csiMapper.volumeID, string(csiMapper.driverName), nodeName)
+	attachment := makeTestAttachment(attachID, nodeName, pvName)
+	attachment.Status.Attached = true
+	if _, err = csiMapper.k8s.StorageV1().VolumeAttachments().Create(context.Background(), attachment, metav1.CreateOptions{}); err != nil {
+		t.Fatalf("failed to setup VolumeAttachment: %v", err)
+	}
+	t.Log("created attachment ", attachID)
+
+	_, err = csiMapper.MapPodDevice()
+	if err == nil {
+		t.Errorf("test should fail, but no error occurred")
+	} else if !errors.As(err, &transientError) {
+		t.Errorf("expected a transient error but got %v", err)
+	}
+}
+
 func TestBlockMapperTearDownDevice(t *testing.T) {
 	plug, tmpDir := newTestPlugin(t, nil)
 	defer os.RemoveAll(tmpDir)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/volume/csi/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestBlockMapperMapPodDeviceGetStageSecretsError"]
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
