#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/apis/autoscaling/v2/conversion_test.go b/pkg/apis/autoscaling/v2/conversion_test.go
new file mode 100644
index 0000000000000..35ba9952498c2
--- /dev/null
+++ b/pkg/apis/autoscaling/v2/conversion_test.go
@@ -0,0 +1,107 @@
+/*
+Copyright The Kubernetes Authors.
+
+Licensed under the Apache License, Version 2.0 (the "License");
+you may not use this file except in compliance with the License.
+You may obtain a copy of the License at
+
+    http://www.apache.org/licenses/LICENSE-2.0
+
+Unless required by applicable law or agreed to in writing, software
+distributed under the License is distributed on an "AS IS" BASIS,
+WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
+See the License for the specific language governing permissions and
+limitations under the License.
+*/
+
+package v2
+
+import (
+	"encoding/json"
+	"testing"
+
+	"github.com/stretchr/testify/assert"
+	autoscalingv1 "k8s.io/api/autoscaling/v1"
+	autoscalingv2 "k8s.io/api/autoscaling/v2"
+	"k8s.io/apimachinery/pkg/api/resource"
+	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
+	"k8s.io/kubernetes/pkg/apis/autoscaling"
+	v1 "k8s.io/kubernetes/pkg/apis/autoscaling/v1"
+	"k8s.io/kubernetes/pkg/apis/autoscaling/validation"
+	"k8s.io/utils/ptr"
+)
+
+// This test ensures that when converting an HPA with an object metric with averageValue
+// from v2 to v1 and back to v2, the value is not defaulted back to zero, causing validation errors.
+func TestObjectMetricAverageValue_RoundTripV2V1(t *testing.T) {
+	var err error
+
+	// Construct a v2 HPA object metric, and set to averageValue with a non-zero value.
+	hpaV2 := &autoscalingv2.HorizontalPodAutoscaler{
+		TypeMeta: metav1.TypeMeta{
+			Kind:       "HorizontalPodAutoscaler",
+			APIVersion: "autoscaling/v2",
+		},
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      "my-hpa",
+			Namespace: "default",
+		},
+		Spec: autoscalingv2.HorizontalPodAutoscalerSpec{
+			ScaleTargetRef: autoscalingv2.CrossVersionObjectReference{
+				Kind:       "Deployment",
+				Name:       "my-deployment",
+				APIVersion: "apps/v1",
+			},
+			MinReplicas: ptr.To[int32](1),
+			MaxReplicas: 3,
+			Metrics: []autoscalingv2.MetricSpec{
+				{
+					Type: autoscalingv2.ObjectMetricSourceType,
+					Object: &autoscalingv2.ObjectMetricSource{
+						Target: autoscalingv2.MetricTarget{
+							Type:         autoscalingv2.AverageValueMetricType,
+							AverageValue: ptr.To(resource.MustParse("100")),
+						},
+						Metric: autoscalingv2.MetricIdentifier{
+							Name: "requests-per-second",
+						},
+						DescribedObject: autoscalingv2.CrossVersionObjectReference{
+							Kind:       "Deployment",
+							Name:       "my-deployment",
+							APIVersion: "apps/v1"},
+					},
+				},
+			},
+		},
+	}
+
+	// Convert from v2 to internal HPA and ensure that no validation errors are produced
+	hpaInternal := &autoscaling.HorizontalPodAutoscaler{}
+	err = Convert_v2_HorizontalPodAutoscaler_To_autoscaling_HorizontalPodAutoscaler(hpaV2, hpaInternal, nil)
+	assert.NoError(t, err, "Conversion to internal should not fail")
+
+	validationErrors := validation.ValidateHorizontalPodAutoscaler(hpaInternal, validation.HorizontalPodAutoscalerSpecValidationOptions{})
+	assert.Zero(t, len(validationErrors), "Validation should not produce errors")
+
+	// Convert internal HPA to v1 HPA
+	hpaV1 := &autoscalingv1.HorizontalPodAutoscaler{}
+	err = v1.Convert_autoscaling_HorizontalPodAutoscaler_To_v1_HorizontalPodAutoscaler(hpaInternal, hpaV1, nil)
+	assert.NoError(t, err, "Conversion to v1 should not fail")
+
+	// Serialise hpaV1 to JSON
+	jsonData, err := json.Marshal(hpaV1)
+	assert.NoError(t, err, "JSON marshalling should not fail")
+
+	// Unmarshal json data to a new v1.HorizontalPodAutoscaler object
+	var hpaV1FromJSON autoscalingv1.HorizontalPodAutoscaler
+	err = json.Unmarshal(jsonData, &hpaV1FromJSON)
+	assert.NoError(t, err, "JSON unmarshalling should not fail")
+
+	// Convert to internal from JSON-unmarshalled v1 HPA, and ensure that no validation errors are produced
+	hpaInternalFromV1 := &autoscaling.HorizontalPodAutoscaler{}
+	err = v1.Convert_v1_HorizontalPodAutoscaler_To_autoscaling_HorizontalPodAutoscaler(&hpaV1FromJSON, hpaInternalFromV1, nil)
+	assert.NoError(t, err, "Conversion from v1 should not fail")
+
+	validationErrors = validation.ValidateHorizontalPodAutoscaler(hpaInternalFromV1, validation.HorizontalPodAutoscalerSpecValidationOptions{})
+	assert.Zero(t, len(validationErrors), "Validation should not produce errors")
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/apis/autoscaling/v2/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestObjectMetricAverageValue_RoundTripV2V1"]
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
