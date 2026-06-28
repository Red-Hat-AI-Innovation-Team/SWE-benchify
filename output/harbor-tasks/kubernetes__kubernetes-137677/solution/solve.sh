#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/service/ipallocator/controller/repairip.go b/pkg/registry/core/service/ipallocator/controller/repairip.go
index feb7fce307679..79c5060e2e5b1 100644
--- a/pkg/registry/core/service/ipallocator/controller/repairip.go
+++ b/pkg/registry/core/service/ipallocator/controller/repairip.go
@@ -247,7 +247,18 @@ func (r *RepairIPAddress) RunUntil(onFirstSuccess func(), stopCh chan struct{})
 
 // runOnce verifies the state of the ClusterIP allocations and returns an error if an unrecoverable problem occurs.
 func (r *RepairIPAddress) runOnce() error {
-	return retry.RetryOnConflict(retry.DefaultBackoff, r.doRunOnce)
+	return retry.OnError(retry.DefaultBackoff, func(err error) bool {
+		// When trying to repair the ClusterIP allocations, we may get a conflict or forbidden error.
+		// IsForbidden depends on the admission chain to be ready that may depend on the
+		// Namespace informer to be ready.
+		// Ref: https://issues.k8s.io/136288
+		if apierrors.IsConflict(err) || apierrors.IsForbidden(err) {
+			klog.ErrorS(err, "Running ipallocator repair failed ... retrying")
+			return true
+		}
+		klog.ErrorS(err, "Running ipallocator repair failed with not retryable error")
+		return false
+	}, r.doRunOnce)
 }
 
 // doRunOnce verifies the state of the ClusterIP allocations and returns an error if an unrecoverable problem occurs.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
