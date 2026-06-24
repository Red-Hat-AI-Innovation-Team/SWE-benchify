#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/stats/cri_stats_provider.go b/pkg/kubelet/stats/cri_stats_provider.go
index dfc6ef30d2037..14f2fb3171c72 100644
--- a/pkg/kubelet/stats/cri_stats_provider.go
+++ b/pkg/kubelet/stats/cri_stats_provider.go
@@ -1195,6 +1195,11 @@ func (p *criStatsProvider) addCadvisorContainerCPUAndMemoryStats(
 	if memory != nil {
 		cs.Memory = memory
 	}
+
+	swap := cadvisorInfoToSwapStats(caPodStats)
+	if swap != nil {
+		cs.Swap = swap
+	}
 }
 
 func getCRICadvisorStats(logger klog.Logger, infos map[string]cadvisorapiv2.ContainerInfo) (map[string]cadvisorapiv2.ContainerInfo, map[string]cadvisorapiv2.ContainerInfo) {
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
