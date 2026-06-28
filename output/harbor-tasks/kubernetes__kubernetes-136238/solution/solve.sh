#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/status/status_manager.go b/pkg/kubelet/status/status_manager.go
index f4334b59ce9ca..78ab5859598ec 100644
--- a/pkg/kubelet/status/status_manager.go
+++ b/pkg/kubelet/status/status_manager.go
@@ -202,10 +202,10 @@ func NewManager(kubeClient clientset.Interface, podManager PodManager, podDeleti
 	}
 }
 
-// isPodStatusByKubeletEqual returns true if the given pod statuses are equal when non-kubelet-owned
-// pod conditions are excluded.
-// This method normalizes the status before comparing so as to make sure that meaningless
-// changes will be ignored.
+// isPodStatusByKubeletEqual returns true if the given pod statuses are equal, ignoring
+// fields not managed by the kubelet (including non-kubelet-owned pod conditions,
+// ResourceClaimStatuses, and ExtendedResourceClaimStatus). Statuses are assumed to be
+// normalized before calling this function.
 func isPodStatusByKubeletEqual(oldStatus, status *v1.PodStatus) bool {
 	oldCopy := oldStatus.DeepCopy()
 
@@ -233,6 +233,11 @@ func isPodStatusByKubeletEqual(oldStatus, status *v1.PodStatus) bool {
 	}
 
 	oldCopy.Conditions = status.Conditions
+	// ResourceClaimStatuses is not owned and not modified by kubelet.
+	oldCopy.ResourceClaimStatuses = status.ResourceClaimStatuses
+	// ExtendedResourceClaimStatus is not owned and not modified by kubelet.
+	oldCopy.ExtendedResourceClaimStatus = status.ExtendedResourceClaimStatus
+
 	return apiequality.Semantic.DeepEqual(oldCopy, status)
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
