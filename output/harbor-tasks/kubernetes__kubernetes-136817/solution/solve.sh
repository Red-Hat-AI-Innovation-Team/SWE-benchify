#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/garbagecollector/garbagecollector.go b/pkg/controller/garbagecollector/garbagecollector.go
index 24044f8706d15..f43578073e800 100644
--- a/pkg/controller/garbagecollector/garbagecollector.go
+++ b/pkg/controller/garbagecollector/garbagecollector.go
@@ -625,7 +625,12 @@ func (gc *GarbageCollector) attemptToDeleteItem(ctx context.Context, item *node)
 		// FinalizerDeletingDependents from the item, resulting in the final
 		// deletion of the item.
 		policy := metav1.DeletePropagationForeground
-		return gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)
+		err := gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)
+		if errors.IsNotFound(err) {
+			gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)
+			return enqueuedVirtualDeleteEventErr
+		}
+		return err
 	default:
 		// item doesn't have any solid owner, so it needs to be garbage
 		// collected. Also, none of item's owners is waiting for the deletion of
@@ -646,7 +651,12 @@ func (gc *GarbageCollector) attemptToDeleteItem(ctx context.Context, item *node)
 			"item", item.identity,
 			"propagationPolicy", policy,
 		)
-		return gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)
+		err := gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)
+		if errors.IsNotFound(err) {
+			gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)
+			return enqueuedVirtualDeleteEventErr
+		}
+		return err
 	}
 }
 
diff --git a/pkg/controller/garbagecollector/operations.go b/pkg/controller/garbagecollector/operations.go
index a300025272807..40acfdef578d0 100644
--- a/pkg/controller/garbagecollector/operations.go
+++ b/pkg/controller/garbagecollector/operations.go
@@ -67,8 +67,8 @@ func (gc *GarbageCollector) deleteObject(item objectReference, resourceVersion s
 		// check if the ownerReferences changed
 		liveObject, liveErr := resourceClient.Get(context.TODO(), item.Name, metav1.GetOptions{})
 		if errors.IsNotFound(liveErr) {
-			// object we wanted to delete is gone, success!
-			return nil
+			// object we wanted to delete is gone, return NotFound so caller can handle it consistently
+			return liveErr
 		}
 		if liveErr == nil && liveObject.UID == item.UID && liveObject.ResourceVersion != resourceVersion && reflect.DeepEqual(liveObject.OwnerReferences, ownersAtResourceVersion) {
 			// object changed, causing a conflict error, but ownerReferences did not change.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
