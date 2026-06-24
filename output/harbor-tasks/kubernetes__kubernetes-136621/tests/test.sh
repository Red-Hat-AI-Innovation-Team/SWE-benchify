#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking_test.go b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking_test.go
index 2a78ac6284790..63243f431d06f 100644
--- a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking_test.go
+++ b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking_test.go
@@ -214,6 +214,24 @@ func TestTypeCheck(t *testing.T) {
 			},
 		}},
 	}}
+	noTypeSchemaPolicy := &v1.ValidatingAdmissionPolicy{Spec: v1.ValidatingAdmissionPolicySpec{
+		Validations: []v1.Validation{
+			{
+				Expression: "true",
+			},
+		},
+		MatchConstraints: &v1.MatchResources{ResourceRules: []v1.NamedRuleWithOperations{
+			{
+				RuleWithOperations: v1.RuleWithOperations{
+					Rule: v1.Rule{
+						APIGroups:   []string{"apps"},
+						APIVersions: []string{"v1"},
+						Resources:   []string{"deployments"},
+					},
+				},
+			},
+		}},
+	}}
 
 	deploymentPolicyWithBadMessageExpression := deploymentPolicy.DeepCopy()
 	deploymentPolicyWithBadMessageExpression.Spec.Validations[0].MessageExpression = "object.foo + 114514" // confusion
@@ -395,6 +413,23 @@ func TestTypeCheck(t *testing.T) {
 				toContain(`undefined field '"'"'bar'"'"'`),
 			},
 		},
+		{
+			name: "params with untyped schema",
+			policy: &v1.ValidatingAdmissionPolicy{Spec: v1.ValidatingAdmissionPolicySpec{
+				ParamKind: &v1.ParamKind{
+					APIVersion: "v1",
+					Kind:       "Config",
+				},
+				Validations: []v1.Validation{
+					{
+						Expression: "params != null",
+					},
+				},
+				MatchConstraints: deploymentPolicy.Spec.MatchConstraints,
+			}},
+			schemaToReturn: &spec.Schema{},
+			assertions:     []assertionFunc{toBeEmpty},
+		},
 		{
 			name:   "multiple expressions",
 			policy: multiExpressionPolicy,
@@ -490,6 +525,12 @@ func TestTypeCheck(t *testing.T) {
 			},
 			assertions: []assertionFunc{toBeEmpty},
 		},
+		{
+			name:           "schema without type",
+			policy:         noTypeSchemaPolicy,
+			schemaToReturn: &spec.Schema{},
+			assertions:     []assertionFunc{toBeEmpty},
+		},
 		{
 			name: "variables valid",
 			policy: &v1.ValidatingAdmissionPolicy{Spec: v1.ValidatingAdmissionPolicySpec{
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestTypeCheck"]
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
