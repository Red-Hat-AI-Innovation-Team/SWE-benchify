#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/pod/storage/eviction.go b/pkg/registry/core/pod/storage/eviction.go
index 2a6561530a736..412b7ef558b31 100644
--- a/pkg/registry/core/pod/storage/eviction.go
+++ b/pkg/registry/core/pod/storage/eviction.go
@@ -18,6 +18,7 @@ package storage
 
 import (
 	"context"
+	goerrors "errors"
 	"fmt"
 	"reflect"
 	"time"
@@ -427,10 +428,20 @@ func (r *EvictionREST) checkAndDecrement(namespace string, podName string, pdb p
 		return createTooManyRequestsError(pdb.Name)
 	}
 	if pdb.Status.DisruptionsAllowed < 0 {
-		return errors.NewForbidden(policy.Resource("poddisruptionbudget"), pdb.Name, fmt.Errorf("pdb disruptions allowed is negative"))
+		err := errors.NewForbidden(policy.Resource("poddisruptionbudget"), pdb.Name, goerrors.New("pdb disruptions allowed is negative"))
+		err.ErrStatus.Details.Causes = append(err.ErrStatus.Details.Causes, metav1.StatusCause{
+			Type:    policyv1.DisruptionBudgetCause,
+			Message: fmt.Sprintf("The disruption budget %s does not allow evicting pods currently: pdb disruptions allowed is negative", pdb.Name),
+		})
+		return err
 	}
 	if len(pdb.Status.DisruptedPods) > MaxDisruptedPodSize {
-		return errors.NewForbidden(policy.Resource("poddisruptionbudget"), pdb.Name, fmt.Errorf("DisruptedPods map too big - too many evictions not confirmed by PDB controller"))
+		err := errors.NewForbidden(policy.Resource("poddisruptionbudget"), pdb.Name, goerrors.New("DisruptedPods map too big - too many evictions not confirmed by PDB controller"))
+		err.ErrStatus.Details.Causes = append(err.ErrStatus.Details.Causes, metav1.StatusCause{
+			Type:    policyv1.DisruptionBudgetCause,
+			Message: fmt.Sprintf("The disruption budget %s does not allow evicting pods currently: too many pending evictions not confirmed by PDB controller", pdb.Name),
+		})
+		return err
 	}
 	if pdb.Status.DisruptionsAllowed == 0 {
 		err := errors.NewTooManyRequests("Cannot evict pod as it would violate the pod's disruption budget.", 0)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
