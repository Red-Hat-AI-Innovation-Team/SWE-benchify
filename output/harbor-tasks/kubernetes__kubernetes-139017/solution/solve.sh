#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
index 9761971338c12..81b8bbddca9d7 100644
--- a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
+++ b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go
@@ -1056,7 +1056,7 @@ func (pl *DynamicResources) unreservePodGroupClaims(ctx context.Context, pod *v1
 }
 
 func (pl *DynamicResources) Score(ctx context.Context, cs fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
-	if !pl.enabled {
+	if !pl.enabled || !pl.fts.EnableDRAPrioritizedList {
 		return 0, nil
 	}
 	logger := klog.FromContext(ctx)
@@ -1085,13 +1085,29 @@ func (pl *DynamicResources) Score(ctx context.Context, cs fwk.CycleState, pod *v
 
 func computeScore(iterator iter.Seq2[int, *resourceapi.ResourceClaim], allocations nodeAllocation) (int64, error) {
 	var score int64
-	for i, claim := range iterator {
+	unallocatedIndex := 0
+	for _, claim := range iterator {
 		// Collect the names for all allocated subrequests.
 		allocatedSubRequests := sets.New[string]()
-		if i >= len(allocations.allocationResults) {
-			return 0, fmt.Errorf("number of allocations %d is smaller than number of claims", len(allocations.allocationResults))
+
+		var allocation *resourceapi.AllocationResult
+		// The allocation for a claim can be in two places:
+		// 1. For claims allocated in a previous cycle (e.g. PodGroup claims), the allocation
+		//    is already in claim.Status.Allocation.
+		// 2. For claims allocated in this cycle (in Filter), the allocation is in
+		//    allocations.allocationResults.
+		// Since we iterate over all claims, we must check both and maintain a separate index
+		// for claims that needed allocation in this cycle.
+		if claim.Status.Allocation != nil {
+			allocation = claim.Status.Allocation
+		} else {
+			if unallocatedIndex >= len(allocations.allocationResults) {
+				return 0, fmt.Errorf("number of allocations %d is smaller than number of claims needing allocation", len(allocations.allocationResults))
+			}
+			allocation = &allocations.allocationResults[unallocatedIndex]
+			unallocatedIndex++
 		}
-		allocation := allocations.allocationResults[i]
+
 		for _, res := range allocation.Devices.Results {
 			request := res.Request
 			if resourceclaim.IsSubRequestRef(request) {
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
