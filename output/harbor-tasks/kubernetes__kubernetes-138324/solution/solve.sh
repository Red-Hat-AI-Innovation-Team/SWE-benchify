#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/scheduler/schedule_one.go b/pkg/scheduler/schedule_one.go
index c8318322275ce..164eb41f3dd27 100644
--- a/pkg/scheduler/schedule_one.go
+++ b/pkg/scheduler/schedule_one.go
@@ -1256,6 +1256,10 @@ func (sched *Scheduler) handleSchedulingFailure(ctx context.Context, podFwk fram
 			logger.Info("Pod has been assigned to node. Abort adding it back to queue.", "pod", klog.KObj(pod), "node", cachedPod.Spec.NodeName)
 			// We need to call DonePod here because we don't call AddUnschedulableIfNotPresent in this case.
 		} else {
+			if cachedPod.UID != podInfo.Pod.UID {
+				logger.V(2).Info("Pod was recreated while handling scheduling failure. Skip requeueing and status updates.", "pod", klog.KObj(pod), "oldUID", podInfo.Pod.UID, "newUID", cachedPod.UID)
+				return
+			}
 			// As <cachedPod> is from SharedInformer, we need to do a DeepCopy() here.
 			// ignore this err since apiserver doesn't properly validate affinity terms
 			// and we can't fix the validation for backwards compatibility.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
