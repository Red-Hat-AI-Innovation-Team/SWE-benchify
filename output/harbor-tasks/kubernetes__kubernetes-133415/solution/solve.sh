#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/podautoscaler/replica_calculator.go b/pkg/controller/podautoscaler/replica_calculator.go
index 656cf3ca51cde..2ff5d4323df77 100644
--- a/pkg/controller/podautoscaler/replica_calculator.go
+++ b/pkg/controller/podautoscaler/replica_calculator.go
@@ -501,7 +501,6 @@ func calculatePodLevelRequests(pod *v1.Pod, resource v1.ResourceName) (int64, er
 // resource by summing requests from all containers in the pod.
 // If a container name is specified, it uses only that container.
 func calculatePodRequestsFromContainers(pod *v1.Pod, container string, resource v1.ResourceName) (int64, error) {
-	// Calculate all regular containers and restartable init containers requests.
 	containers := append([]v1.Container{}, pod.Spec.Containers...)
 	for _, c := range pod.Spec.InitContainers {
 		if c.RestartPolicy != nil && *c.RestartPolicy == v1.ContainerRestartPolicyAlways {
@@ -518,7 +517,17 @@ func calculatePodRequestsFromContainers(pod *v1.Pod, container string, resource
 			}
 			request += containerRequest.MilliValue()
 		}
+		// container names are unique inside the pod
+		if container == c.Name {
+			return request, nil
+		}
+	}
+
+	// If we're looking for a specific container and didn't find it
+	if container != "" {
+		return 0, fmt.Errorf("container %s not found in Pod %s", container, pod.Name)
 	}
+
 	return request, nil
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
