#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/config/common_test.go b/pkg/kubelet/config/common_test.go
index 19e26814d62be..8d60d269cad77 100644
--- a/pkg/kubelet/config/common_test.go
+++ b/pkg/kubelet/config/common_test.go
@@ -28,13 +28,16 @@ import (
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
 	"k8s.io/apimachinery/pkg/runtime"
 	"k8s.io/apimachinery/pkg/types"
+	utilfeature "k8s.io/apiserver/pkg/util/feature"
 	clientscheme "k8s.io/client-go/kubernetes/scheme"
+	featuregatetesting "k8s.io/component-base/featuregate/testing"
 	"k8s.io/klog/v2"
 	"k8s.io/klog/v2/ktesting"
 	"k8s.io/kubernetes/pkg/api/legacyscheme"
 	podtest "k8s.io/kubernetes/pkg/api/pod/testing"
 	"k8s.io/kubernetes/pkg/apis/core"
 	"k8s.io/kubernetes/pkg/apis/core/validation"
+	"k8s.io/kubernetes/pkg/features"
 	"k8s.io/kubernetes/pkg/securitycontext"
 	"k8s.io/utils/ptr"
 )
@@ -242,6 +245,45 @@ func TestDecodeSinglePodRejectsResourceClaims(t *testing.T) {
 	}
 }
 
+func TestDecodeSinglePodWithOptions(t *testing.T) {
+	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.ContainerRestartRules, true)
+	logger, _ := ktesting.NewTestContext(t)
+	restartPolicyAlways := v1.ContainerRestartPolicyAlways
+	pod := &v1.Pod{
+		TypeMeta: metav1.TypeMeta{
+			APIVersion: "",
+		},
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      "test",
+			UID:       "12345",
+			Namespace: "mynamespace",
+		},
+		Spec: v1.PodSpec{
+			RestartPolicy: v1.RestartPolicyNever,
+			Containers: []v1.Container{{
+				Name:                     "image",
+				Image:                    "test/image",
+				ImagePullPolicy:          "IfNotPresent",
+				TerminationMessagePath:   "/dev/termination-log",
+				TerminationMessagePolicy: v1.TerminationMessageReadFile,
+				SecurityContext:          securitycontext.ValidSecurityContextWithContainerDefaults(),
+				RestartPolicy:            &restartPolicyAlways,
+			}},
+		},
+	}
+	json, err := runtime.Encode(clientscheme.Codecs.LegacyCodec(v1.SchemeGroupVersion), pod)
+	if err != nil {
+		t.Errorf("unexpected error: %v", err)
+	}
+	parsed, _, err := tryDecodeSinglePod(logger, json, noDefault)
+	if err != nil {
+		t.Errorf("unexpected error: %v (%s)", err, string(json))
+	}
+	if !parsed {
+		t.Errorf("expected to have parsed file: (%s)", string(json))
+	}
+}
+
 func TestDecodePodList(t *testing.T) {
 	logger, _ := ktesting.NewTestContext(t)
 	grace := int64(30)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/config/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestDecodeSinglePodWithOptions"]
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
