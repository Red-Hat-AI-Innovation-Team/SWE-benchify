#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/scheduler/schedule_one_podgroup.go b/pkg/scheduler/schedule_one_podgroup.go
index c46b711f37e66..8e0a27158b0f4 100644
--- a/pkg/scheduler/schedule_one_podgroup.go
+++ b/pkg/scheduler/schedule_one_podgroup.go
@@ -229,11 +229,16 @@ func (sched *Scheduler) podGroupCycle(ctx context.Context, schedFwk framework.Fr
 		result := podGroupAlgorithmResult{
 			status: fwk.AsStatus(err),
 		}
+		// Ensure podResults has an entry for each pod in the pod group with Error status.
+		result = completePodGroupAlgorithmResult(ctx, podGroupInfo, podGroupCycleState, runAllPostFilters, result)
 		sched.submitPodGroupAlgorithmResult(ctx, schedFwk, podGroupCycleState, podGroupInfo, result, start)
 		return
 	}
 
 	result := sched.podGroupSchedulingAlgorithm(ctx, schedFwk, podGroupCycleState, podGroupInfo, runAllPostFilters)
+
+	// Ensure podResults has an entry for each pod in the pod group with a status.
+	result = completePodGroupAlgorithmResult(ctx, podGroupInfo, podGroupCycleState, runAllPostFilters, result)
 	metrics.PodGroupSchedulingAlgorithmLatency.Observe(metrics.SinceInSeconds(start))
 
 	// Run workload aware preemption if required. If the preemption is successful,
@@ -490,7 +495,29 @@ func (sched *Scheduler) podGroupPodSchedulingAlgorithm(ctx context.Context, sche
 	}, revertFn
 }
 
+// completePodGroupAlgorithmResult ensures that the podGroupAlgorithmResult contains the same number of podResults as there are pods in QueuedPodInfos.
+func completePodGroupAlgorithmResult(ctx context.Context, podGroupInfo *framework.QueuedPodGroupInfo, podGroupState *framework.CycleState, postFilterMode podGroupPostFilterMode, podGroupResult podGroupAlgorithmResult) podGroupAlgorithmResult {
+	numInResult := len(podGroupResult.podResults)
+	numInQueue := len(podGroupInfo.QueuedPodInfos)
+	if numInResult == numInQueue {
+		return podGroupResult
+	}
+	newResults := make([]algorithmResult, numInQueue)
+	copy(newResults, podGroupResult.podResults)
+	for i := numInResult; i < numInQueue; i++ {
+		pInfo := podGroupInfo.QueuedPodInfos[i]
+		newResults[i] = algorithmResult{
+			podCtx: initPodSchedulingContext(ctx, pInfo.Pod, podGroupState, postFilterMode),
+			status: podGroupResult.status.Clone(),
+		}
+	}
+	podGroupResult.podResults = newResults
+	return podGroupResult
+}
+
 // submitPodGroupAlgorithmResult submits the result of the pod group scheduling algorithm.
+// It assumes that podGroupResult contains results for all pods from the pod group,
+// if it does not, podGroupCondition will be updated to reflect the error.
 // If that algorithm succedeed, the schedulable pods proceed to the binding cycle.
 // Unschedulable pods are moved back to the scheduling queue and need to wait
 // for the next pod group scheduling cycle.
@@ -499,19 +526,16 @@ func (sched *Scheduler) podGroupPodSchedulingAlgorithm(ctx context.Context, sche
 func (sched *Scheduler) submitPodGroupAlgorithmResult(ctx context.Context, schedFwk framework.Framework, podGroupState *framework.CycleState, podGroupInfo *framework.QueuedPodGroupInfo, podGroupResult podGroupAlgorithmResult, start time.Time) {
 	logger := klog.FromContext(ctx)
 
+	if len(podGroupResult.podResults) != len(podGroupInfo.QueuedPodInfos) {
+		// This should never happen, but if it does, complete the result with the error status.
+		logger.Error(fmt.Errorf("some pods were not processed"), "scheduling error for pod group", "podGroup", klog.KObj(podGroupInfo))
+		podGroupResult.status = fwk.NewStatus(fwk.Error, "scheduling error for pod group, some pods were not processed")
+		podGroupResult.podResults = nil
+		podGroupResult = completePodGroupAlgorithmResult(ctx, podGroupInfo, podGroupState, runAllPostFilters, podGroupResult)
+	}
 	var scheduledPods, unschedulablePods int
 	for i, pInfo := range podGroupInfo.QueuedPodInfos {
-		var podResult algorithmResult
-		if len(podGroupResult.podResults) > i {
-			podResult = podGroupResult.podResults[i]
-		} else {
-			// In pod group-level unschedulable or error cases, podResult may not be defined.
-			// Initialize it now to handle pod failure correctly.
-			podResult = algorithmResult{
-				podCtx: initPodSchedulingContext(ctx, pInfo.Pod, podGroupState, runAllPostFilters),
-				status: podGroupResult.status.Clone(),
-			}
-		}
+		podResult := podGroupResult.podResults[i]
 		podCtx := podResult.podCtx
 		ctx := klog.NewContext(ctx, podCtx.logger)
 		// To be consistent with pod-by-pod scheduling, construct pod scheduling start time as `now - scheduling duration`.
@@ -776,14 +800,13 @@ func makeProposedAssignments(res *podGroupAlgorithmResult) []fwk.ProposedAssignm
 	return proposedAssignments
 }
 
-// podGroupSchedulingAlgorithm attempts to schedule pods in the pod group according to the policy and constraints and returns the scheduling result for each pod in the pod group.
+// podGroupSchedulingAlgorithm attempts to schedule pods in the pod group according to the policy and constraints and returns the scheduling result for all evaluated pods in the pod group, not necessarily all pods in the pod group.
 func (sched *Scheduler) podGroupSchedulingAlgorithm(ctx context.Context, schedFwk framework.Framework, podGroupCycleState *framework.CycleState, podGroupInfo *framework.QueuedPodGroupInfo, postFilterMode podGroupPostFilterMode) podGroupAlgorithmResult {
 	podGroupCycleCtx, cancel := context.WithCancel(ctx)
 	defer cancel()
 
 	if utilfeature.DefaultFeatureGate.Enabled(features.TopologyAwareWorkloadScheduling) {
 		return sched.podGroupSchedulingPlacementAlgorithm(podGroupCycleCtx, schedFwk, podGroupCycleState, podGroupInfo, postFilterMode)
-	} else {
-		return sched.podGroupSchedulingDefaultAlgorithm(podGroupCycleCtx, schedFwk, podGroupCycleState, podGroupInfo, postFilterMode)
 	}
+	return sched.podGroupSchedulingDefaultAlgorithm(podGroupCycleCtx, schedFwk, podGroupCycleState, podGroupInfo, postFilterMode)
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
