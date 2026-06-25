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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestApplyConfiguration"]

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
