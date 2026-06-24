#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/printers/internalversion/printers.go b/pkg/printers/internalversion/printers.go
index 079786473fbff..a61b1cc62b897 100644
--- a/pkg/printers/internalversion/printers.go
+++ b/pkg/printers/internalversion/printers.go
@@ -2636,12 +2636,16 @@ func printNetworkPolicyList(list *networking.NetworkPolicyList, options printers
 }
 
 func printStorageClass(obj *storage.StorageClass, options printers.GenerateOptions) ([]metav1.TableRow, error) {
+	return printStorageClassInternal(obj, options, "")
+}
+
+func printStorageClassInternal(obj *storage.StorageClass, options printers.GenerateOptions, effectiveDefault string) ([]metav1.TableRow, error) {
 	row := metav1.TableRow{
 		Object: runtime.RawExtension{Object: obj},
 	}
 
 	name := obj.Name
-	if storageutil.IsDefaultAnnotation(obj.ObjectMeta) {
+	if effectiveDefault != "" && obj.Name == effectiveDefault {
 		name += " (default)"
 	}
 	provtype := obj.Provisioner
@@ -2668,8 +2672,12 @@ func printStorageClass(obj *storage.StorageClass, options printers.GenerateOptio
 
 func printStorageClassList(list *storage.StorageClassList, options printers.GenerateOptions) ([]metav1.TableRow, error) {
 	rows := make([]metav1.TableRow, 0, len(list.Items))
+
+	// Find the effective default StorageClass (most recently created one with default annotation)
+	effectiveDefault := getEffectiveDefaultStorageClass(list.Items)
+
 	for i := range list.Items {
-		r, err := printStorageClass(&list.Items[i], options)
+		r, err := printStorageClassInternal(&list.Items[i], options, effectiveDefault)
 		if err != nil {
 			return nil, err
 		}
@@ -2678,6 +2686,28 @@ func printStorageClassList(list *storage.StorageClassList, options printers.Gene
 	return rows, nil
 }
 
+// getEffectiveDefaultStorageClass returns the name of the effective default StorageClass.
+// When multiple StorageClasses have the default annotation, the most recently created one
+// is the effective default. If timestamps are equal, the one with alphabetically first name wins.
+func getEffectiveDefaultStorageClass(items []storage.StorageClass) string {
+	var effectiveDefault *storage.StorageClass
+	for i := range items {
+		if storageutil.IsDefaultAnnotation(items[i].ObjectMeta) {
+			if effectiveDefault == nil {
+				effectiveDefault = &items[i]
+			} else if items[i].CreationTimestamp.After(effectiveDefault.CreationTimestamp.Time) {
+				effectiveDefault = &items[i]
+			} else if items[i].CreationTimestamp.Equal(&effectiveDefault.CreationTimestamp) && items[i].Name < effectiveDefault.Name {
+				effectiveDefault = &items[i]
+			}
+		}
+	}
+	if effectiveDefault != nil {
+		return effectiveDefault.Name
+	}
+	return ""
+}
+
 func printVolumeAttributesClass(obj *storage.VolumeAttributesClass, options printers.GenerateOptions) ([]metav1.TableRow, error) {
 	row := metav1.TableRow{
 		Object: runtime.RawExtension{Object: obj},
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
