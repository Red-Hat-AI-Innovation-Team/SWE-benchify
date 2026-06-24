#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/resourcequota/strategy.go b/pkg/registry/core/resourcequota/strategy.go
index a57416d3fd001..5a6dda4820fb8 100644
--- a/pkg/registry/core/resourcequota/strategy.go
+++ b/pkg/registry/core/resourcequota/strategy.go
@@ -18,6 +18,7 @@ package resourcequota
 
 import (
 	"context"
+	"fmt"
 
 	"k8s.io/apimachinery/pkg/runtime"
 	"k8s.io/apimachinery/pkg/util/validation/field"
@@ -74,9 +75,36 @@ func (resourcequotaStrategy) Validate(ctx context.Context, obj runtime.Object) f
 	return validation.ValidateResourceQuota(resourcequota)
 }
 
+// all known resource names that we want to check for request <= limit
+var knownResourceNames = []api.ResourceName{
+	api.ResourceCPU,
+	api.ResourceMemory,
+	api.ResourceStorage,
+	api.ResourceEphemeralStorage,
+}
+
 // WarningsOnCreate returns warnings for the creation of the given object.
 func (resourcequotaStrategy) WarningsOnCreate(ctx context.Context, obj runtime.Object) []string {
-	return nil
+	resourcequota := obj.(*api.ResourceQuota)
+	var allWarnings []string
+	for _, resourceName := range knownResourceNames {
+		requestResourceName := api.ResourceName(fmt.Sprintf("requests.%s", resourceName))
+		request, requestOK := resourcequota.Spec.Hard[requestResourceName]
+		if !requestOK && (resourceName == api.ResourceCPU || resourceName == api.ResourceMemory) {
+			// try the bare name for cpu and memory
+			request, requestOK = resourcequota.Spec.Hard[resourceName]
+			if requestOK {
+				requestResourceName = resourceName
+			}
+		}
+		limitResourceName := api.ResourceName(fmt.Sprintf("limits.%s", resourceName))
+		limit, limitOK := resourcequota.Spec.Hard[limitResourceName]
+		if requestOK && limitOK && request.Cmp(limit) > 0 {
+			allWarnings = append(allWarnings, fmt.Sprintf("ResourceQuota %s (%s) should be less than %s (%s)",
+				requestResourceName, request.String(), limitResourceName, limit.String()))
+		}
+	}
+	return allWarnings
 }
 
 // Canonicalize normalizes the object after validation.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
