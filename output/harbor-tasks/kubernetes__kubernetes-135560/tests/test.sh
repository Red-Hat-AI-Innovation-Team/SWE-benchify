#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd_test.go b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd_test.go
index e4e3810a0d613..3f0b87233dcfd 100644
--- a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd_test.go
+++ b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd_test.go
@@ -233,6 +233,107 @@ func TestApplyConfiguration(t *testing.T) {
 			object:      &appsv1.Deployment{Spec: appsv1.DeploymentSpec{Replicas: ptr.To[int32](1)}},
 			expectedErr: "must evaluate to Object but got Object.spec.metadata",
 		},
+		{
+			name: "apply configuration with duplicate env vars in original object",
+			expression: `Object{
+					spec: Object.spec{
+						replicas: 3
+					}
+				}`,
+			gvr: deploymentGVR,
+			object: &appsv1.Deployment{
+				Spec: appsv1.DeploymentSpec{
+					Replicas: ptr.To[int32](1),
+					Template: corev1.PodTemplateSpec{
+						Spec: corev1.PodSpec{
+							Containers: []corev1.Container{{
+								Name: "nginx",
+								Env: []corev1.EnvVar{
+									{Name: "test", Value: "a"},
+									{Name: "test", Value: "b"},
+								},
+							}},
+						},
+					},
+				},
+			},
+			expectedResult: &appsv1.Deployment{
+				Spec: appsv1.DeploymentSpec{
+					Replicas: ptr.To[int32](3),
+					Template: corev1.PodTemplateSpec{
+						Spec: corev1.PodSpec{
+							Containers: []corev1.Container{{
+								Name: "nginx",
+								Env: []corev1.EnvVar{
+									{Name: "test", Value: "a"},
+									{Name: "test", Value: "b"},
+								},
+							}},
+						},
+					},
+				},
+			},
+		},
+		// This test verifies that modifying an existing environment variable works correctly,
+		// even if the original object contains duplicates.
+		// Because '"'"'env'"'"' is defined with `listType=map` and `listMapKey=name` in the schema,
+		// Structured Merge Diff (SMD) treats '"'"'name'"'"' as the unique key.
+		// When the patch updates the entry with name="test", SMD merges the changes.
+		// As a side effect of the merge process on a map-type list, duplicate entries for the
+		// same key in the original object are consolidated into a single entry in the result.
+		// This matches the behavior of Server-Side Apply (SSA) and kubectl apply.
+		{
+			name: "apply configuration modify existing env variable",
+			expression: `Object{
+					spec: Object.spec{
+						template: Object.spec.template{
+							spec: Object.spec.template.spec{
+								containers: [Object.spec.template.spec.containers{
+									name: "nginx",
+									env: [Object.spec.template.spec.containers.env{
+										name: "test",
+										value: "c"
+									}]
+								}]
+							}
+						}
+					}
+				}`,
+			gvr: deploymentGVR,
+			object: &appsv1.Deployment{
+				Spec: appsv1.DeploymentSpec{
+					Replicas: ptr.To[int32](1),
+					Template: corev1.PodTemplateSpec{
+						Spec: corev1.PodSpec{
+							Containers: []corev1.Container{{
+								Name: "nginx",
+								Env: []corev1.EnvVar{
+									{Name: "test", Value: "a"},
+									{Name: "test", Value: "b"},
+									{Name: "foo", Value: "bar"},
+								},
+							}},
+						},
+					},
+				},
+			},
+			expectedResult: &appsv1.Deployment{
+				Spec: appsv1.DeploymentSpec{
+					Replicas: ptr.To[int32](1),
+					Template: corev1.PodTemplateSpec{
+						Spec: corev1.PodSpec{
+							Containers: []corev1.Container{{
+								Name: "nginx",
+								Env: []corev1.EnvVar{
+									{Name: "test", Value: "c"},
+									{Name: "foo", Value: "bar"},
+								},
+							}},
+						},
+					},
+				},
+			},
+		},
 	}
 
 	compiler, err := cel.NewCompositedCompiler(environment.MustBaseEnvSet(environment.DefaultCompatibilityVersion()))
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestApplyConfiguration"]
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
