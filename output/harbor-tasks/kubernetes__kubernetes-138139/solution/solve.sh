#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/kuberuntime/kuberuntime_container_linux.go b/pkg/kubelet/kuberuntime/kuberuntime_container_linux.go
index b103e840fd193..33d0159716ab7 100644
--- a/pkg/kubelet/kuberuntime/kuberuntime_container_linux.go
+++ b/pkg/kubelet/kuberuntime/kuberuntime_container_linux.go
@@ -168,9 +168,9 @@ func (m *kubeGenericRuntimeManager) generateLinuxContainerResources(ctx context.
 			unified[cm.Cgroup2MemoryLow] = "0"
 		}
 
-		// Guaranteed pods by their QoS definition requires that memory request equals memory limit and cpu request must equal cpu limit.
-		// Here, we only check from memory perspective. Hence MemoryQoS feature is disabled on those QoS pods by not setting memory.high.
-		if memoryRequest != memoryLimit {
+		// Skip memory.high only for equal, positive memory request/limit (container guaranteed memory).
+		// For Burstable pods, memory.high uses the memory limit, for BestEffort pods (request=limit=0), node allocatable is used.
+		if memoryRequest != memoryLimit || memoryRequest == 0 {
 			// The formula for memory.high for container cgroup is modified in Alpha stage of the feature in K8s v1.27.
 			// It will be set based on formula:
 			// `memory.high=floor[(requests.memory + memory throttling factor * (limits.memory or node allocatable memory - requests.memory))/pageSize] * pageSize`
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
