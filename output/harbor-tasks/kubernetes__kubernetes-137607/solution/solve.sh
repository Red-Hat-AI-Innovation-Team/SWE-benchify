#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
index 46db7e45c0918..bdaaa0bb56996 100644
--- a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
+++ b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
@@ -721,7 +721,13 @@ func (pl *DynamicResources) Filter(ctx context.Context, cs fwk.CycleState, pod *
 		a, err := state.allocator.Allocate(allocCtx, node, claimsToAllocate)
 		switch {
 		case errors.Is(err, context.DeadlineExceeded):
-			return statusUnschedulable(logger, "timed out trying to allocate devices", "pod", klog.KObj(pod), "node", klog.KObj(node), "resourceclaims", klog.KObjSlice(claimsToAllocate))
+			// Timeouts are potentially transient. Return Error
+			// so the pod retries via backoff instead of sitting in the
+			// unschedulable queue waiting for a cluster event.
+			//
+			// The timeout might be caused by ResourceSlices for the node,
+			// so including the node name may help with diagnosing the failure.
+			return statusError(logger, fmt.Errorf("node %s: timed out trying to allocate devices", node.Name), "pod", klog.KObj(pod), "node", klog.KObj(node), "resourceclaims", klog.KObjSlice(claimsToAllocate))
 		case errors.Is(err, structured.ErrFailedAllocationOnNode):
 			// Not a fatal error, allocation on other nodes may proceed.
 			// The error is only surfaced if allocation fails on all nodes.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
