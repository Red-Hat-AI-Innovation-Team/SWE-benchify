#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/statefulset/stateful_set_control.go b/pkg/controller/statefulset/stateful_set_control.go
index b06f8d443ee96..3e88f714ff10a 100644
--- a/pkg/controller/statefulset/stateful_set_control.go
+++ b/pkg/controller/statefulset/stateful_set_control.go
@@ -756,41 +756,89 @@ func updateStatefulSetAfterInvariantEstablished(ctx context.Context, ssc *defaul
 		}
 	}
 
-	// Collect all targets in the range between getStartOrdinal(set) and getEndOrdinal(set). Count any targets in that range
-	// that are unavailable. Select the
-	// (MaxUnavailable - Unavailable) Pods, in order with respect to their ordinal for termination. Delete
-	// those pods and count the successful deletions. Update the status with the correct number of deletions.
+	// Collect all targets in the range between getStartOrdinal(set) and getEndOrdinal(set).
+	// Count any targets in that range  that are unavailable. Select the (MaxUnavailable - Unavailable)
+	// Pods, in order with respect to their ordinal for termination.
+	// Delete those pods and count the successful deletions.
+	// Update the status with the correct number of deletions.
 	unavailablePods := 0
-
+	// For Parallel pod management, additionally count old and unavailable, within the maxUnavailable limit.
+	unavailablePodsNeedingUpdate := 0
 	for target := len(replicas) - 1; target >= 0; target-- {
-		if isUnavailable(replicas[target], set.Spec.MinReadySeconds, now) {
+		pod := replicas[target]
+		if isUnavailable(pod, set.Spec.MinReadySeconds, now) {
 			unavailablePods++
+			if set.Spec.PodManagementPolicy == apps.ParallelPodManagement &&
+				getPodRevision(pod) != updateRevision.Name &&
+				!isTerminating(pod) {
+				unavailablePodsNeedingUpdate++
+			}
 		}
 	}
 	metrics.UnavailableReplicas.WithLabelValues(set.Namespace, set.Name, podManagementPolicy).Set(float64(unavailablePods))
 
-	if unavailablePods >= maxUnavailable {
+	// short circuit only when we're above the maxUnavailable budget and for
+	// Parallel pod management there is no chance to make progress
+	if unavailablePods >= maxUnavailable && unavailablePodsNeedingUpdate == 0 {
 		// log only when a true violation occurs.
 		if unavailablePods > maxUnavailable {
 			logger.V(4).Info("StatefulSet found unavailablePods, more than the allowed maxUnavailable",
 				"statefulSet", klog.KObj(set),
 				"unavailablePods", unavailablePods,
+				"unavailablePodsNeedingUpdate", unavailablePodsNeedingUpdate,
 				"maxUnavailable", maxUnavailable)
 		}
+		return &status, nil
+	}
+
+	if set.Spec.PodManagementPolicy == apps.ParallelPodManagement {
+		// Two-phase deletion for Parallel mode avoids excessive disruption when some
+		// pods are already unavailable on the old revision. A single high-to-low loop
+		// could spend the entire budget on good pods and never reach the already-
+		// unavailable pods at the bottom, causing total disruption >> maxUnavailable.
+		//
+		// Phase 1: delete pods that are already unavailable on the old revision.
+		for target := len(replicas) - 1; target >= updateMin; target-- {
+			pod := replicas[target]
+			if getPodRevision(pod) != updateRevision.Name &&
+				!isRunningAndAvailable(pod, set.Spec.MinReadySeconds, now) &&
+				!isTerminating(pod) {
+				logger.V(2).Info("StatefulSet terminating unavailable Pod for update",
+					"statefulSet", klog.KObj(set), "pod", klog.KObj(pod))
+				if err := ssc.podControl.DeleteStatefulPod(set, pod); err != nil {
+					return &status, err
+				}
+				status.CurrentReplicas--
+			}
+		}
 
+		// Phase 2: delete additional available pods, limited by remaining budget,
+		// to always stay under the maxUnavailable.
+		remainingBudget := maxUnavailable - unavailablePods
+		for target := len(replicas) - 1; target >= updateMin && remainingBudget > 0; target-- {
+			pod := replicas[target]
+			if getPodRevision(pod) != updateRevision.Name &&
+				isRunningAndAvailable(pod, set.Spec.MinReadySeconds, now) &&
+				!isTerminating(pod) {
+				logger.V(2).Info("StatefulSet terminating Pod for update",
+					"statefulSet", klog.KObj(set), "pod", klog.KObj(pod))
+				if err := ssc.podControl.DeleteStatefulPod(set, pod); err != nil {
+					return &status, err
+				}
+				remainingBudget--
+				status.CurrentReplicas--
+			}
+		}
 		return &status, nil
 	}
 
-	// Now we need to delete MaxUnavailable- unavailablePods
-	// start deleting one by one starting from the highest ordinal first
+	// OrderedReady pod management: original single-pass high-to-low logic.
+	// effectiveUnavailable == unavailablePods here (no exemption for unavailable pods).
 	podsToDelete := maxUnavailable - unavailablePods
-
 	deletedPods := 0
 	for target := len(replicas) - 1; target >= updateMin && deletedPods < podsToDelete; target-- {
-
-		// delete the Pod if it is healthy and the revision does not match the target
+		// delete the Pod if it is not already terminating and the revision does not match the target
 		if getPodRevision(replicas[target]) != updateRevision.Name && !isTerminating(replicas[target]) {
-			// delete the Pod if it is healthy and the revision does not match the target
 			logger.V(2).Info("StatefulSet terminating Pod for update",
 				"statefulSet", klog.KObj(set),
 				"pod", klog.KObj(replicas[target]))
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
