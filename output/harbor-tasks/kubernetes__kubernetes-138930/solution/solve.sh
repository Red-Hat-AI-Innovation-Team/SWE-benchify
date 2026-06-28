#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/prober/prober_manager.go b/pkg/kubelet/prober/prober_manager.go
index 7d07479ca9351..fbbddb75dc08c 100644
--- a/pkg/kubelet/prober/prober_manager.go
+++ b/pkg/kubelet/prober/prober_manager.go
@@ -196,7 +196,7 @@ func (m *manager) AddPod(ctx context.Context, pod *v1.Pod) {
 			if _, ok := m.workers[key]; ok {
 				logger.V(8).Info("Startup probe already exists for container",
 					"pod", klog.KObj(pod), "containerName", c.Name)
-				return
+				continue
 			}
 			w := newWorker(m, startup, pod, c)
 			m.workers[key] = w
@@ -208,7 +208,7 @@ func (m *manager) AddPod(ctx context.Context, pod *v1.Pod) {
 			if _, ok := m.workers[key]; ok {
 				logger.V(8).Info("Readiness probe already exists for container",
 					"pod", klog.KObj(pod), "containerName", c.Name)
-				return
+				continue
 			}
 			w := newWorker(m, readiness, pod, c)
 			m.workers[key] = w
@@ -220,7 +220,7 @@ func (m *manager) AddPod(ctx context.Context, pod *v1.Pod) {
 			if _, ok := m.workers[key]; ok {
 				logger.V(8).Info("Liveness probe already exists for container",
 					"pod", klog.KObj(pod), "containerName", c.Name)
-				return
+				continue
 			}
 			w := newWorker(m, liveness, pod, c)
 			m.workers[key] = w
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
