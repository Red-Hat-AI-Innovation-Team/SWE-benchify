#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/delete.go b/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/delete.go
index e8b74c8a913e8..2efd08d25a8ef 100644
--- a/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/delete.go
+++ b/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/delete.go
@@ -103,11 +103,13 @@ func DeleteResource(r rest.GracefulDeleter, allowsOptions bool, scope *RequestSc
 				defaultGVK := scope.MetaGroupVersion.WithKind("DeleteOptions")
 				obj, gvk, err := apihelpers.GetMetaInternalVersionCodecs().DecoderToVersion(s.Serializer, defaultGVK.GroupVersion()).Decode(body, &defaultGVK, options)
 				if err != nil {
+					err = errors.NewBadRequest(err.Error())
 					scope.err(err, w, req)
 					return
 				}
 				if obj != options {
-					scope.err(fmt.Errorf("decoded object cannot be converted to DeleteOptions"), w, req)
+					err = errors.NewBadRequest("decoded object cannot be converted to DeleteOptions")
+					scope.err(err, w, req)
 					return
 				}
 				span.AddEvent("Decoded delete options")
@@ -278,11 +280,13 @@ func DeleteCollection(r rest.CollectionDeleter, checkBody bool, scope *RequestSc
 				defaultGVK := scope.MetaGroupVersion.WithKind("DeleteOptions")
 				obj, gvk, err := apihelpers.GetMetaInternalVersionCodecs().DecoderToVersion(s.Serializer, defaultGVK.GroupVersion()).Decode(body, &defaultGVK, options)
 				if err != nil {
+					err = errors.NewBadRequest(err.Error())
 					scope.err(err, w, req)
 					return
 				}
 				if obj != options {
-					scope.err(fmt.Errorf("decoded object cannot be converted to DeleteOptions"), w, req)
+					err = errors.NewBadRequest("decoded object cannot be converted to DeleteOptions")
+					scope.err(err, w, req)
 					return
 				}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
