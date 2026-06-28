#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
index 575fd5e2e9a57..91176286d47f0 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
@@ -451,42 +451,56 @@ func (s *Validator) validateExpressions(ctx context.Context, fldPath *field.Path
 			}
 			continue
 		}
-		if evalResult != types.True {
-			currentFldPath := fldPath
-			if len(compiled.NormalizedRuleFieldPath) > 0 {
-				currentFldPath = currentFldPath.Child(compiled.NormalizedRuleFieldPath)
-			}
 
-			addErr := func(e *field.Error) {
-				if !compiled.UsesOldSelf && correlation.shouldRatchetError() {
-					warning.AddWarning(ctx, "", e.Error())
-				} else {
-					errs = append(errs, e)
-				}
+		if evalResult == types.True {
+			continue
+		}
+
+		// Prepare a field error describing why the expression evaluated to False.
+		// Its detail may come from another expression that might fail to evaluate or exceed the budget.
+
+		currentFldPath := fldPath
+		if len(compiled.NormalizedRuleFieldPath) > 0 {
+			currentFldPath = currentFldPath.Child(compiled.NormalizedRuleFieldPath)
+		}
+
+		addErr := func(e *field.Error) {
+			if !compiled.UsesOldSelf && correlation.shouldRatchetError() {
+				warning.AddWarning(ctx, "", e.Error())
+			} else {
+				errs = append(errs, e)
 			}
+		}
 
-			if compiled.MessageExpression != nil {
-				messageExpression, newRemainingBudget, msgErr := evalMessageExpression(ctx, compiled.MessageExpression, rule.MessageExpression, activation, remainingBudget)
-				if msgErr != nil {
-					if msgErr.Type == cel.ErrorTypeInternal {
-						addErr(field.InternalError(currentFldPath, msgErr))
-						return errs, -1
-					} else if msgErr.Type == cel.ErrorTypeInvalid {
-						addErr(field.Invalid(currentFldPath, sts.Type, msgErr.Error()))
-						return errs, -1
-					} else {
-						klog.V(2).ErrorS(msgErr, "messageExpression evaluation failed")
-						addErr(fieldErrorForReason(currentFldPath, sts.Type, ruleMessageOrDefault(rule), rule.Reason))
-						remainingBudget = newRemainingBudget
-					}
-				} else {
-					addErr(fieldErrorForReason(currentFldPath, sts.Type, messageExpression, rule.Reason))
-					remainingBudget = newRemainingBudget
-				}
+		detail, ok := "", false
+		if compiled.MessageExpression != nil {
+			messageExpression, newRemainingBudget, msgErr := evalMessageExpression(ctx, compiled.MessageExpression, rule.MessageExpression, activation, remainingBudget)
+			if msgErr == nil {
+				detail, ok = messageExpression, true
+				remainingBudget = newRemainingBudget
+			} else if msgErr.Type == cel.ErrorTypeInternal {
+				addErr(field.InternalError(currentFldPath, msgErr))
+				return errs, -1
+			} else if msgErr.Type == cel.ErrorTypeInvalid {
+				addErr(field.Invalid(currentFldPath, sts.Type, msgErr.Error()))
+				return errs, -1
 			} else {
-				addErr(fieldErrorForReason(currentFldPath, sts.Type, ruleMessageOrDefault(rule), rule.Reason))
+				klog.V(2).ErrorS(msgErr, "messageExpression evaluation failed")
+				remainingBudget = newRemainingBudget
 			}
 		}
+		if !ok {
+			detail = ruleMessageOrDefault(rule)
+		}
+
+		value := obj
+		if ok {
+			value = field.OmitValueType{}
+		} else if sts.Type == "object" || sts.Type == "array" {
+			value = sts.Type
+		}
+
+		addErr(fieldErrorForReason(currentFldPath, value, detail, rule.Reason))
 	}
 	return errs, remainingBudget
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
