#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/kuberuntime/kuberuntime_container.go b/pkg/kubelet/kuberuntime/kuberuntime_container.go
index 3075566105f1c..a1d9453f8918d 100644
--- a/pkg/kubelet/kuberuntime/kuberuntime_container.go
+++ b/pkg/kubelet/kuberuntime/kuberuntime_container.go
@@ -1222,7 +1222,12 @@ func (m *kubeGenericRuntimeManager) computeInitContainerActions(ctx context.Cont
 
 				restartOnFailure := restartOnFailure
 				if utilfeature.DefaultFeatureGate.Enabled(features.ContainerRestartRules) {
-					restartOnFailure = kubecontainer.ShouldContainerBeRestarted(container, pod, podStatus)
+					// Only container-level restart policy is used. The container-level restart
+					// rules are not evaluated because the container might not have exited, so
+					// there is no exit code on which the rules can be used.
+					if container.RestartPolicy != nil {
+						restartOnFailure = *container.RestartPolicy != v1.ContainerRestartPolicyNever
+					}
 				}
 				if !restartOnFailure {
 					changes.KillPod = true
diff --git a/pkg/kubelet/kuberuntime/kuberuntime_manager.go b/pkg/kubelet/kuberuntime/kuberuntime_manager.go
index 26ba815fee257..a2a112c4bc3e8 100644
--- a/pkg/kubelet/kuberuntime/kuberuntime_manager.go
+++ b/pkg/kubelet/kuberuntime/kuberuntime_manager.go
@@ -589,16 +589,6 @@ func containerChanged(container *v1.Container, containerStatus *kubecontainer.St
 }
 
 func shouldRestartOnFailure(pod *v1.Pod) bool {
-	// With feature ContainerRestartRules enabled, the pod should be restarted
-	// on failure if any of its containers have container-level restart policy
-	// that is restartable.
-	if utilfeature.DefaultFeatureGate.Enabled(features.ContainerRestartRules) {
-		for _, c := range pod.Spec.Containers {
-			if podutil.IsContainerRestartable(pod.Spec, c) {
-				return true
-			}
-		}
-	}
 	return pod.Spec.RestartPolicy != v1.RestartPolicyNever
 }
 
@@ -1147,7 +1137,11 @@ func (m *kubeGenericRuntimeManager) computePodActions(ctx context.Context, pod *
 		var reason containerKillReason
 		restart := shouldRestartOnFailure(pod)
 		if utilfeature.DefaultFeatureGate.Enabled(features.ContainerRestartRules) {
-			restart = kubecontainer.ShouldContainerBeRestarted(&container, pod, podStatus)
+			// For probe failures, use container-level restart policy only. Container-level restart
+			// rules are not evaluated because the container is still running.
+			if container.RestartPolicy != nil {
+				restart = *container.RestartPolicy != v1.ContainerRestartPolicyNever
+			}
 		}
 		if _, _, changed := containerChanged(&container, containerStatus); changed {
 			message = fmt.Sprintf("Container %s definition changed", container.Name)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
