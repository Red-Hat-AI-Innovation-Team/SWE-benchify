#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy.go
index b51b94f7274c1..b89e42db167fb 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy.go
@@ -105,7 +105,9 @@ func (a statusStrategy) ValidateUpdate(ctx context.Context, obj, old runtime.Obj
 	var correlatedObject *common.CorrelatedObject
 	if utilfeature.DefaultFeatureGate.Enabled(apiextensionsfeatures.CRDValidationRatcheting) {
 		correlatedObject = common.NewCorrelatedObject(uNew.Object, uOld.Object, &model.Structural{Structural: a.structuralSchema})
-		options = append(options, validation.WithRatcheting(correlatedObject.Key("status")))
+		if a.structuralSchema != nil {
+			options = append(options, validation.WithRatcheting(correlatedObject.Key("status")))
+		}
 		celOptions = append(celOptions, cel.WithRatcheting(correlatedObject))
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
