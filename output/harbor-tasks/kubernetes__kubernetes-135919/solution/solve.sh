#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/cm/dra/manager.go b/pkg/kubelet/cm/dra/manager.go
index bd9f0cd684f26..f316e37db125b 100644
--- a/pkg/kubelet/cm/dra/manager.go
+++ b/pkg/kubelet/cm/dra/manager.go
@@ -360,10 +360,10 @@ func (m *Manager) prepareResources(ctx context.Context, pod *v1.Pod) error {
 				return fmt.Errorf("checkpoint ResourceClaim cache: %w", err)
 			}
 
-			// If this claim is already prepared, there is no need to prepare it again.
+			// If this claim is already prepared, continue preparing for any remaining claims.
 			if claimInfo.isPrepared() {
 				logger.V(5).Info("Resources already prepared", "pod", klog.KObj(pod), "podClaim", podClaim.Name, "claim", klog.KObj(resourceClaim))
-				return nil
+				continue
 			}
 
 			// This saved claim will be used to update ClaimInfo cache
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
