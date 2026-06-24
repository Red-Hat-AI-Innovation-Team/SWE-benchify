#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/resourceclaim/controller.go b/pkg/controller/resourceclaim/controller.go
index f7dadf8b0ef38..2cefc2fe8ac48 100644
--- a/pkg/controller/resourceclaim/controller.go
+++ b/pkg/controller/resourceclaim/controller.go
@@ -20,6 +20,7 @@ import (
 	"context"
 	"errors"
 	"fmt"
+	"maps"
 	"slices"
 	"strings"
 	"sync"
@@ -861,10 +862,25 @@ func (ec *Controller) syncPod(ctx context.Context, namespace, name string) error
 	if newPodClaims != nil {
 		// Patch the pod status with the new information about
 		// generated ResourceClaims.
-		statuses := make([]*corev1apply.PodResourceClaimStatusApplyConfiguration, 0, len(newPodClaims))
-		for podClaimName, resourceClaimName := range newPodClaims {
-			statuses = append(statuses, corev1apply.PodResourceClaimStatus().WithName(podClaimName).WithResourceClaimName(resourceClaimName))
+		mergedStatuses := make(map[string]string)
+		for _, status := range pod.Status.ResourceClaimStatuses {
+			if status.ResourceClaimName != nil {
+				mergedStatuses[status.Name] = *status.ResourceClaimName
+			}
+		}
+		maps.Copy(mergedStatuses, newPodClaims)
+
+		names := make([]string, 0, len(mergedStatuses))
+		for name := range mergedStatuses {
+			names = append(names, name)
 		}
+		slices.Sort(names)
+
+		statuses := make([]*corev1apply.PodResourceClaimStatusApplyConfiguration, 0, len(names))
+		for _, name := range names {
+			statuses = append(statuses, corev1apply.PodResourceClaimStatus().WithName(name).WithResourceClaimName(mergedStatuses[name]))
+		}
+
 		podApply := corev1apply.Pod(name, namespace).WithStatus(corev1apply.PodStatus().WithResourceClaimStatuses(statuses...))
 		if _, err := ec.kubeClient.CoreV1().Pods(namespace).ApplyStatus(ctx, podApply, metav1.ApplyOptions{FieldManager: fieldManager, Force: true}); err != nil {
 			return fmt.Errorf("update pod %s/%s ResourceClaimStatuses: %v", namespace, name, err)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
