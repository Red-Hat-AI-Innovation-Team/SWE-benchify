#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager.go b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager.go
index ac8d4279d6f7a..cff31115a00af 100644
--- a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager.go
+++ b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager.go
@@ -140,24 +140,27 @@ func (f *FieldManager) Update(liveObj, newObj runtime.Object, manager string) (o
 }
 
 // UpdateNoErrors is the same as Update, but it will not return
-// errors. If an error happens, the object is returned with
-// managedFields cleared.
+// errors. If an error happens, we preserve the managedFields from
+// liveObj.
 func (f *FieldManager) UpdateNoErrors(liveObj, newObj runtime.Object, manager string) runtime.Object {
 	obj, err := f.Update(liveObj, newObj, manager)
 	if err != nil {
-		atMostEverySecond.Do(func() {
-			ns, name := "unknown", "unknown"
-			if accessor, err := meta.Accessor(newObj); err == nil {
-				ns = accessor.GetNamespace()
-				name = accessor.GetName()
+		// Preserve the managedFields from the live object rather than
+		// stripping them entirely, to avoid silent data loss when the
+		// managedFields update fails (e.g. due to an unavailable
+		// conversion webhook).
+		// Note: meta.Accessor for liveObj and newObj below never return an error in this code branch,
+		// because if they would f.Update above would return "newObj, nil". Accordingly, the case
+		// where one of the accessors returns an error is not handled here.
+		if liveAccessor, aErr := meta.Accessor(liveObj); aErr == nil {
+			if newAccessor, aErr := meta.Accessor(newObj); aErr == nil {
+				atMostEverySecond.Do(func() {
+					klog.ErrorS(err, "[SHOULD NOT HAPPEN] failed to update managedFields (restored previous managedFields from live object)", "versionKind",
+						newObj.GetObjectKind().GroupVersionKind(), "namespace", newAccessor.GetNamespace(), "name", newAccessor.GetName())
+				})
+				newAccessor.SetManagedFields(liveAccessor.GetManagedFields())
 			}
-
-			klog.ErrorS(err, "[SHOULD NOT HAPPEN] failed to update managedFields", "versionKind",
-				newObj.GetObjectKind().GroupVersionKind(), "namespace", ns, "name", name)
-		})
-		// Explicitly remove managedFields on failure, so that
-		// we can't have garbage in it.
-		RemoveObjectManagedFields(newObj)
+		}
 		return newObj
 	}
 	return obj
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
