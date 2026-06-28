#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/eviction/eviction_manager.go b/pkg/kubelet/eviction/eviction_manager.go
index 4019d6aa3f59e..7c772b20aef0f 100644
--- a/pkg/kubelet/eviction/eviction_manager.go
+++ b/pkg/kubelet/eviction/eviction_manager.go
@@ -588,6 +588,15 @@ func (m *managerImpl) containerEphemeralStorageLimitEviction(logger klog.Logger,
 			thresholdsMap[container.Name] = ephemeralLimit
 		}
 	}
+	for _, container := range pod.Spec.InitContainers {
+		if !podutil.IsRestartableInitContainer(&container) {
+			continue
+		}
+		ephemeralLimit := container.Resources.Limits.StorageEphemeral()
+		if ephemeralLimit != nil && ephemeralLimit.Value() != 0 {
+			thresholdsMap[container.Name] = ephemeralLimit
+		}
+	}
 
 	for _, containerStat := range podStats.Containers {
 		containerUsed := diskUsage(containerStat.Logs)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
