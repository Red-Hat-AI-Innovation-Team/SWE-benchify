#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/scheduler/backend/queue/scheduling_queue.go b/pkg/scheduler/backend/queue/scheduling_queue.go
index 2e9e5c09b3566..e36f0014ad0f8 100644
--- a/pkg/scheduler/backend/queue/scheduling_queue.go
+++ b/pkg/scheduler/backend/queue/scheduling_queue.go
@@ -610,8 +610,11 @@ func (p *PriorityQueue) runPreEnqueuePlugin(ctx context.Context, logger klog.Log
 		// No need to change GatingPlugin; it's overwritten by the next PreEnqueue plugin if they gate this pod, or it's overwritten with an empty string if all PreEnqueue plugins pass.
 		return s
 	}
+	// Only increment metric and insert if not already incremented for this plugin
+	if !pInfo.UnschedulablePlugins.Has(pl.Name()) && !pInfo.PendingPlugins.Has(pl.Name()) {
+		metrics.UnschedulableReason(pl.Name(), pod.Spec.SchedulerName).Inc()
+	}
 	pInfo.UnschedulablePlugins.Insert(pl.Name())
-	metrics.UnschedulableReason(pl.Name(), pod.Spec.SchedulerName).Inc()
 	pInfo.GatingPlugin = pl.Name()
 	pInfo.GatingPluginEvents = p.pluginToEventsMap[pInfo.GatingPlugin]
 	if s.Code() == fwk.Error {
@@ -1130,6 +1133,10 @@ func (p *PriorityQueue) Delete(pod *v1.Pod) {
 	}
 	if pInfo = p.unschedulablePods.get(pod); pInfo != nil {
 		p.unschedulablePods.delete(pod, pInfo.Gated())
+		// Drop metric for deleted pod.
+		for plugin := range pInfo.UnschedulablePlugins.Union(pInfo.PendingPlugins) {
+			metrics.UnschedulableReason(plugin, pInfo.Pod.Spec.SchedulerName).Dec()
+		}
 	}
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
