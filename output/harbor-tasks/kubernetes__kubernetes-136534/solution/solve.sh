#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/kubectl/pkg/util/resource/resource.go b/staging/src/k8s.io/kubectl/pkg/util/resource/resource.go
index cc7bc4ab7b72d..3a34da9e8a179 100644
--- a/staging/src/k8s.io/kubectl/pkg/util/resource/resource.go
+++ b/staging/src/k8s.io/kubectl/pkg/util/resource/resource.go
@@ -152,7 +152,12 @@ func determineContainerReqs(pod *corev1.Pod, container *corev1.Container, cs *co
 // max returns the result of max(a, b...) for each named resource and is only used if we can't
 // accumulate into an existing resource list
 func max(a corev1.ResourceList, b ...corev1.ResourceList) corev1.ResourceList {
-	result := a.DeepCopy()
+	var result corev1.ResourceList
+	if a != nil {
+		result = a.DeepCopy()
+	} else {
+		result = corev1.ResourceList{}
+	}
 	for _, other := range b {
 		maxResourceList(result, other)
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
