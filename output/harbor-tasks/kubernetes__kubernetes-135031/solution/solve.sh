#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/config/common.go b/pkg/kubelet/config/common.go
index fb388560ae648..c2076776da8fa 100644
--- a/pkg/kubelet/config/common.go
+++ b/pkg/kubelet/config/common.go
@@ -138,7 +138,8 @@ func tryDecodeSinglePod(logger klog.Logger, data []byte, defaultFn defaultFunc)
 	if err = defaultFn(logger, newPod); err != nil {
 		return true, pod, err
 	}
-	if errs := validation.ValidatePodCreate(newPod, validation.PodValidationOptions{}); len(errs) > 0 {
+	opts := podutil.GetValidationOptionsFromPodSpecAndMeta(&newPod.Spec, nil, &newPod.ObjectMeta, nil)
+	if errs := validation.ValidatePodCreate(newPod, opts); len(errs) > 0 {
 		return true, pod, fmt.Errorf("invalid pod: %v", errs)
 	}
 	v1Pod := &v1.Pod{}
@@ -199,7 +200,8 @@ func tryDecodePodList(logger klog.Logger, data []byte, defaultFn defaultFunc) (p
 		if err = defaultFn(logger, newPod); err != nil {
 			return true, pods, err
 		}
-		if errs := validation.ValidatePodCreate(newPod, validation.PodValidationOptions{}); len(errs) > 0 {
+		opts := podutil.GetValidationOptionsFromPodSpecAndMeta(&newPod.Spec, nil, &newPod.ObjectMeta, nil)
+		if errs := validation.ValidatePodCreate(newPod, opts); len(errs) > 0 {
 			err = fmt.Errorf("invalid pod: %v", errs)
 			return true, pods, err
 		}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
