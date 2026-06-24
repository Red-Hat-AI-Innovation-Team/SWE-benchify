#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/volume/attachdetach/reconciler/reconciler.go b/pkg/controller/volume/attachdetach/reconciler/reconciler.go
index 6bbca35bb1c16..d600a1d01b600 100644
--- a/pkg/controller/volume/attachdetach/reconciler/reconciler.go
+++ b/pkg/controller/volume/attachdetach/reconciler/reconciler.go
@@ -393,12 +393,12 @@ func (rc *reconciler) reportMultiAttachError(logger klog.Logger, volumeToAttach
 	pods := rc.desiredStateOfWorld.GetVolumePodsOnNodes(otherNodes, volumeToAttach.VolumeName)
 	if len(pods) == 0 {
 		// We did not find any pods that requests the volume. The pod must have been deleted already.
-		simpleMsg, _ := volumeToAttach.GenerateMsg("Multi-Attach error", "Volume is already exclusively attached to one node and can't be attached to another")
+		simpleMsg, _ := volumeToAttach.GenerateMsg("Waiting for detach", "Volume is already exclusively attached to one node, waiting on detach before it can be attached to another node")
 		for _, pod := range volumeToAttach.ScheduledPods {
 			rc.recorder.Eventf(pod, v1.EventTypeWarning, kevents.FailedAttachVolume, "%s", simpleMsg)
 		}
 		// Log detailed message to system admin
-		logger.Info("Multi-Attach error: volume is already exclusively attached and can't be attached to another node", "attachedTo", otherNodesStr, "volume", volumeToAttach)
+		logger.Info("Waiting for detach: volume is already exclusively attached, waiting on detach before it can be attached to another node", "attachedTo", otherNodesStr, "volume", volumeToAttach)
 		return
 	}
 
@@ -429,10 +429,10 @@ func (rc *reconciler) reportMultiAttachError(logger klog.Logger, volumeToAttach
 			// No local pods, there are pods only in different namespaces.
 			msg = fmt.Sprintf("Volume is already used by %d pod(s) in different namespaces", otherPods)
 		}
-		simpleMsg, _ := volumeToAttach.GenerateMsg("Multi-Attach error", msg)
+		simpleMsg, _ := volumeToAttach.GenerateMsg("Waiting for detach", msg)
 		rc.recorder.Eventf(scheduledPod, v1.EventTypeWarning, kevents.FailedAttachVolume, "%s", simpleMsg)
 	}
 
 	// Log all pods for system admin
-	logger.Info("Multi-Attach error: volume is already used by pods", "pods", klog.KObjSlice(pods), "attachedTo", otherNodesStr, "volume", volumeToAttach)
+	logger.Info("Waiting for detach: volume is in use by pods", "pods", klog.KObjSlice(pods), "attachedTo", otherNodesStr, "volume", volumeToAttach)
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
