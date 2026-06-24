#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode.go b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode.go
index f51f886f42a06..d5daf9f4e0b37 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode.go
@@ -44,8 +44,10 @@ var (
 // for the file format); this function tries each in order and populates dest
 // with the first one it can successfully decode and convert.
 //
-// Objects that cannot be decoded or converted are skipped so that a driver
-// upgrade does not break older consumers.
+// Entries whose apiVersion is not registered in the scheme (e.g. a newer
+// version written by an upgraded driver) are skipped silently so that a
+// driver upgrade does not break older consumers. Any other failure is
+// fatal. dest is only populated on a nil return.
 //
 // dest must be a pointer to a type registered in the metadata scheme (e.g.,
 // *v1alpha1.DeviceMetadata or *metadata.DeviceMetadata). The internal type
@@ -60,26 +62,26 @@ func DecodeMetadataFromStream(decoder *json.Decoder, dest runtime.Object) error
 
 	deserializer := codecFactory.UniversalDeserializer()
 
-	var skippedErrors []string
+	var unknownVersions []string
 	for decoder.More() {
 		var raw json.RawMessage
 		if err := decoder.Decode(&raw); err != nil {
 			return fmt.Errorf("read metadata object from stream: %w", err)
 		}
-
 		obj, gvk, err := deserializer.Decode(raw, nil, nil)
 		if err != nil {
-			if gvk != nil {
-				skippedErrors = append(skippedErrors, fmt.Sprintf("%s: %v", gvk.GroupVersion(), err))
-			} else {
-				skippedErrors = append(skippedErrors, err.Error())
+			if gvk == nil || gvk.Version == "" {
+				return fmt.Errorf("decode metadata object: %w", err)
+			}
+			if runtime.IsNotRegisteredError(err) && !scheme.IsVersionRegistered(gvk.GroupVersion()) {
+				unknownVersions = append(unknownVersions, gvk.GroupVersion().String())
+				continue
 			}
-			continue
+			return fmt.Errorf("decode %s: %w", gvk.GroupVersion(), err)
 		}
 
 		if err := scheme.Convert(obj, dest, nil); err != nil {
-			skippedErrors = append(skippedErrors, fmt.Sprintf("%s: convert: %v", obj.GetObjectKind().GroupVersionKind().GroupVersion(), err))
-			continue
+			return fmt.Errorf("convert %s: %w", obj.GetObjectKind().GroupVersionKind().GroupVersion(), err)
 		}
 
 		// scheme.Convert does not propagate TypeMeta. Set it explicitly
@@ -90,10 +92,10 @@ func DecodeMetadataFromStream(decoder *json.Decoder, dest runtime.Object) error
 		}
 		return nil
 	}
-	if len(skippedErrors) > 0 {
-		return fmt.Errorf("no compatible metadata version found in stream (errors: %s)", strings.Join(skippedErrors, "; "))
+	if len(unknownVersions) == 0 {
+		return fmt.Errorf("no metadata objects found in stream")
 	}
-	return fmt.Errorf("no metadata objects found in stream")
+	return fmt.Errorf("no compatible metadata version found in stream (unknown versions: %s)", strings.Join(unknownVersions, ", "))
 }
 
 // ReadResourceClaimMetadataWithDriverName reads and decodes the metadata file
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
