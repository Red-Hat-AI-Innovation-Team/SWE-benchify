#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/apis/core/validation/validation.go b/pkg/apis/core/validation/validation.go
index 4fabcc3940ea7..cc08203cb6656 100644
--- a/pkg/apis/core/validation/validation.go
+++ b/pkg/apis/core/validation/validation.go
@@ -3694,7 +3694,7 @@ func validateContainerRestartPolicy(policy *core.ContainerRestartPolicy, rules [
 	}
 
 	if len(rules) > 20 {
-		allErrs = append(allErrs, field.TooLong(fldPath.Child("restartPolicyRules"), rules, 20))
+		allErrs = append(allErrs, field.TooMany(fldPath.Child("restartPolicyRules"), len(rules), 20))
 	}
 	for i, rule := range rules {
 		policyRulesFld := fldPath.Child("restartPolicyRules").Index(i)
@@ -3713,7 +3713,7 @@ func validateContainerRestartPolicy(policy *core.ContainerRestartPolicy, rules [
 			}
 
 			if len(rule.ExitCodes.Values) > 255 {
-				allErrs = append(allErrs, field.TooLong(exitCodesFld.Child("values"), rule.ExitCodes.Values, 255))
+				allErrs = append(allErrs, field.TooMany(exitCodesFld.Child("values"), len(rule.ExitCodes.Values), 255))
 			}
 		} else {
 			allErrs = append(allErrs, field.Required(policyRulesFld.Child("exitCodes"), "must be specified"))
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
