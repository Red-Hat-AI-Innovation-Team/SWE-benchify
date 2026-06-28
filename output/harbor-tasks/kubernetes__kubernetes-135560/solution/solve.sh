#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd.go b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd.go
index 3be79df54ea17..7135aca3a254a 100644
--- a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd.go
+++ b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/mutating/patch/smd.go
@@ -138,7 +138,7 @@ func ApplyStructuredMergeDiff(
 		return nil, fmt.Errorf("invalid ApplyConfiguration: %w", err)
 	}
 
-	liveObjTyped, err := typeConverter.ObjectToTyped(originalObject)
+	liveObjTyped, err := typeConverter.ObjectToTyped(originalObject, typed.AllowDuplicates)
 	if err != nil {
 		return nil, fmt.Errorf("failed to convert original object to typed object: %w", err)
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
