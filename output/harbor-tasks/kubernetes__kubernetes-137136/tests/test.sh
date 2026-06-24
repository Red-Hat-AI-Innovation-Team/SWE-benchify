#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/apis/core/validation/validation_test.go b/pkg/apis/core/validation/validation_test.go
index 2fb13216aef3f..bfbae98127638 100644
--- a/pkg/apis/core/validation/validation_test.go
+++ b/pkg/apis/core/validation/validation_test.go
@@ -29606,6 +29606,44 @@ func TestValidateContainerRestartPolicy(t *testing.T) {
 				BadValue: core.ContainerRestartRuleOnExitCodesOperator(""),
 			}},
 		},
+		{
+			Name:          "restart-policy-rules with too many exit codes",
+			RestartPolicy: &containerRestartPolicyNever,
+			RestartPolicyRules: []core.ContainerRestartRule{{
+				Action: "Restart",
+				ExitCodes: &core.ContainerRestartRuleOnExitCodes{
+					Operator: "In",
+					Values:   make([]int32, 256),
+				},
+			}},
+			ExpectedErrors: field.ErrorList{{
+				Type:     field.ErrorTypeTooMany,
+				Field:    "containers[0].restartPolicyRules[0].exitCodes.values",
+				BadValue: 256,
+			}},
+		},
+		{
+			Name:          "restart-policy-rules with too many rules",
+			RestartPolicy: &containerRestartPolicyNever,
+			RestartPolicyRules: func() []core.ContainerRestartRule {
+				rules := make([]core.ContainerRestartRule, 21)
+				for i := range rules {
+					rules[i] = core.ContainerRestartRule{
+						Action: "Restart",
+						ExitCodes: &core.ContainerRestartRuleOnExitCodes{
+							Operator: "In",
+							Values:   []int32{42},
+						},
+					}
+				}
+				return rules
+			}(),
+			ExpectedErrors: field.ErrorList{{
+				Type:     field.ErrorTypeTooMany,
+				Field:    "containers[0].restartPolicyRules",
+				BadValue: 21,
+			}},
+		},
 	}
 
 	for _, tc := range errorCases {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/apis/core/validation/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestValidateContainerRestartPolicy"]
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
