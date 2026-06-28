#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/pod/storage/eviction.go b/pkg/registry/core/pod/storage/eviction.go
index f088cf37de365..c1819b5b8d387 100644
--- a/pkg/registry/core/pod/storage/eviction.go
+++ b/pkg/registry/core/pod/storage/eviction.go
@@ -434,7 +434,26 @@ func (r *EvictionREST) checkAndDecrement(namespace string, podName string, pdb p
 	}
 	if pdb.Status.DisruptionsAllowed == 0 {
 		err := errors.NewTooManyRequests("Cannot evict pod as it would violate the pod's disruption budget.", 0)
-		err.ErrStatus.Details.Causes = append(err.ErrStatus.Details.Causes, metav1.StatusCause{Type: policyv1.DisruptionBudgetCause, Message: fmt.Sprintf("The disruption budget %s needs %d healthy pods and has %d currently", pdb.Name, pdb.Status.DesiredHealthy, pdb.Status.CurrentHealthy)})
+		condition := meta.FindStatusCondition(pdb.Status.Conditions, policyv1.DisruptionAllowedCondition)
+		var msg string
+		switch {
+		// check whether sync is failed first because DesiredHealthy and CurrentHealthy are not trustworthy when the sync is failed
+		case condition != nil && condition.Status == metav1.ConditionFalse && len(condition.Message) > 0 && condition.Reason == policyv1.SyncFailedReason:
+			msg = fmt.Sprintf("The disruption budget %s does not allow evicting pods currently because it failed sync: %s", pdb.Name, condition.Message)
+		case pdb.Status.CurrentHealthy <= pdb.Status.DesiredHealthy:
+			msg = fmt.Sprintf("The disruption budget %s needs %d healthy pods and has %d currently", pdb.Name, pdb.Status.DesiredHealthy, pdb.Status.CurrentHealthy)
+		case condition != nil && condition.Status == metav1.ConditionFalse && len(condition.Message) > 0:
+			msg = fmt.Sprintf("The disruption budget %s does not allow evicting pods currently (%s): %s", pdb.Name, condition.Reason, condition.Message)
+		default:
+			msg = fmt.Sprintf("The disruption budget %s does not allow evicting pods currently", pdb.Name)
+		}
+		err.ErrStatus.Details.Causes = append(
+			err.ErrStatus.Details.Causes,
+			metav1.StatusCause{
+				Type:    policyv1.DisruptionBudgetCause,
+				Message: msg,
+			},
+		)
 		return err
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
