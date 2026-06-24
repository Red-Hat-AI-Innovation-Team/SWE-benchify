#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/kuberuntime/instrumented_services.go b/pkg/kubelet/kuberuntime/instrumented_services.go
index 52896d59b1fd6..446f4e7d45bdd 100644
--- a/pkg/kubelet/kuberuntime/instrumented_services.go
+++ b/pkg/kubelet/kuberuntime/instrumented_services.go
@@ -181,7 +181,7 @@ func (in instrumentedRuntimeService) RunPodSandbox(ctx context.Context, config *
 	const operation = "run_podsandbox"
 	startTime := time.Now()
 	defer recordOperation(operation, startTime)
-	defer metrics.RunPodSandboxDuration.WithLabelValues(runtimeHandler).Observe(metrics.SinceInSeconds(startTime))
+	defer metrics.RunPodSandboxDuration.ObserveSince(startTime, runtimeHandler)()
 
 	out, err := in.service.RunPodSandbox(ctx, config, runtimeHandler)
 	recordError(operation, err)
diff --git a/pkg/kubelet/server/server.go b/pkg/kubelet/server/server.go
index 191482784c698..0ee72e1643e53 100644
--- a/pkg/kubelet/server/server.go
+++ b/pkg/kubelet/server/server.go
@@ -1190,8 +1190,11 @@ func (s *Server) ServeHTTP(w http.ResponseWriter, req *http.Request) {
 	servermetrics.HTTPInflightRequests.WithLabelValues(method, path, serverType, longRunning).Inc()
 	defer servermetrics.HTTPInflightRequests.WithLabelValues(method, path, serverType, longRunning).Dec()
 
-	startTime := time.Now()
-	defer servermetrics.HTTPRequestsDuration.WithLabelValues(method, path, serverType, longRunning).Observe(servermetrics.SinceInSeconds(startTime))
+	// Use ObserveSince to ensure the duration is calculated when the defer executes,
+	// not when it's declared. In Go, arguments to deferred functions are evaluated
+	// immediately at the defer statement, which would cause the metric to record
+	// near-zero values (~2 microseconds) instead of actual request handling time.
+	defer servermetrics.HTTPRequestsDuration.ObserveSince(time.Now(), method, path, serverType, longRunning)()
 
 	handler.ServeHTTP(w, req)
 }
diff --git a/pkg/scheduler/eventhandlers.go b/pkg/scheduler/eventhandlers.go
index 2febf790f5370..1cf1858986e01 100644
--- a/pkg/scheduler/eventhandlers.go
+++ b/pkg/scheduler/eventhandlers.go
@@ -52,8 +52,7 @@ import (
 
 func (sched *Scheduler) addNodeToCache(obj interface{}) {
 	evt := fwk.ClusterEvent{Resource: fwk.Node, ActionType: fwk.Add}
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(evt.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), evt.Label())()
 	logger := sched.logger
 	node, ok := obj.(*v1.Node)
 	if !ok {
@@ -99,8 +98,7 @@ func (sched *Scheduler) updateNodeInCache(oldObj, newObj interface{}) {
 
 func (sched *Scheduler) deleteNodeFromCache(obj interface{}) {
 	evt := fwk.ClusterEvent{Resource: fwk.Node, ActionType: fwk.Delete}
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(evt.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), evt.Label())()
 
 	logger := sched.logger
 	var node *v1.Node
@@ -226,8 +224,7 @@ func (sched *Scheduler) deletePod(obj interface{}) {
 }
 
 func (sched *Scheduler) addPodToSchedulingQueue(pod *v1.Pod) {
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventUnscheduledPodAdd.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), framework.EventUnscheduledPodAdd.Label())()
 
 	logger := sched.logger
 	logger.V(3).Info("Add event for unscheduled pod", "pod", klog.KObj(pod))
@@ -303,10 +300,10 @@ func (sched *Scheduler) updatePodInSchedulingQueue(oldPod, newPod *v1.Pod) {
 		return
 	}
 
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventUnscheduledPodUpdate.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(start, framework.EventUnscheduledPodUpdate.Label())()
 	for _, evt := range framework.PodSchedulingPropertiesChange(newPod, oldPod) {
 		if evt.Label() != framework.EventUnscheduledPodUpdate.Label() {
-			defer metrics.EventHandlingLatency.WithLabelValues(evt.Label()).Observe(metrics.SinceInSeconds(start))
+			defer metrics.EventHandlingLatency.ObserveSince(start, evt.Label())()
 		}
 	}
 
@@ -344,8 +341,7 @@ func hasNominatedNodeNameChanged(oldPod, newPod *v1.Pod) bool {
 }
 
 func (sched *Scheduler) deletePodFromSchedulingQueue(pod *v1.Pod, inBinding bool) {
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventUnscheduledPodDelete.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), framework.EventUnscheduledPodDelete.Label())()
 
 	logger := sched.logger
 
@@ -383,8 +379,7 @@ func getLEPriorityPreCheck(priority int32) queue.PreEnqueueCheck {
 }
 
 func (sched *Scheduler) addAssignedPodToCache(pod *v1.Pod) {
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventAssignedPodAdd.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), framework.EventAssignedPodAdd.Label())()
 
 	logger := sched.logger
 
@@ -411,7 +406,7 @@ func (sched *Scheduler) addAssignedPodToCache(pod *v1.Pod) {
 
 func (sched *Scheduler) updateAssignedPodInCache(oldPod, newPod *v1.Pod) {
 	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventAssignedPodUpdate.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(start, framework.EventAssignedPodUpdate.Label())()
 
 	logger := sched.logger
 
@@ -453,8 +448,7 @@ func (sched *Scheduler) updateAssignedPodInCache(oldPod, newPod *v1.Pod) {
 }
 
 func (sched *Scheduler) deleteAssignedPodFromCache(pod *v1.Pod) {
-	start := time.Now()
-	defer metrics.EventHandlingLatency.WithLabelValues(framework.EventAssignedPodDelete.Label()).Observe(metrics.SinceInSeconds(start))
+	defer metrics.EventHandlingLatency.ObserveSince(time.Now(), framework.EventAssignedPodDelete.Label())()
 
 	logger := sched.logger
 
@@ -538,8 +532,7 @@ func addAllEventHandlers(
 		if at&fwk.Add != 0 {
 			evt := fwk.ClusterEvent{Resource: resource, ActionType: fwk.Add}
 			funcs.AddFunc = func(obj interface{}) {
-				start := time.Now()
-				defer metrics.EventHandlingLatency.WithLabelValues(evt.Label()).Observe(metrics.SinceInSeconds(start))
+				defer metrics.EventHandlingLatency.ObserveSince(time.Now(), evt.Label())()
 				if resource == fwk.StorageClass && !utilfeature.DefaultFeatureGate.Enabled(features.SchedulerQueueingHints) {
 					sc, ok := obj.(*storagev1.StorageClass)
 					if !ok {
diff --git a/pkg/scheduler/framework/runtime/batch.go b/pkg/scheduler/framework/runtime/batch.go
index ad296f8a0103d..9822799f6926c 100644
--- a/pkg/scheduler/framework/runtime/batch.go
+++ b/pkg/scheduler/framework/runtime/batch.go
@@ -106,9 +106,7 @@ func (b *OpportunisticBatch) GetNodeHint(ctx context.Context, pod *v1.Pod, state
 func (b *OpportunisticBatch) StoreScheduleResults(ctx context.Context, signature fwk.PodSignature, hintedNode, chosenNode string, otherNodes framework.SortedScoredNodes, cycleCount int64) {
 	logger := klog.FromContext(ctx)
 
-	startTime := time.Now()
-	defer metrics.StoreScheduleResultsDuration.WithLabelValues(b.handle.ProfileName()).Observe(metrics.SinceInSeconds(startTime))
-
+	defer metrics.StoreScheduleResultsDuration.ObserveSince(time.Now(), b.handle.ProfileName())()
 	// Set our cycle information for next time.
 	b.lastCycle = schedulingCycle{
 		cycleCount: cycleCount,
diff --git a/staging/src/k8s.io/component-base/metrics/histogram.go b/staging/src/k8s.io/component-base/metrics/histogram.go
index 73b56d1b80e0e..846be004713d2 100644
--- a/staging/src/k8s.io/component-base/metrics/histogram.go
+++ b/staging/src/k8s.io/component-base/metrics/histogram.go
@@ -19,6 +19,7 @@ package metrics
 import (
 	"context"
 	"sync"
+	"time"
 
 	"github.com/blang/semver/v4"
 	"github.com/prometheus/client_golang/prometheus"
@@ -214,6 +215,21 @@ func (v *HistogramVec) With(labels map[string]string) ObserverMetric {
 	return v.HistogramVec.With(labels)
 }
 
+// ObserveSince returns a function that observes the duration since the given start time.
+// This is intended to be used with defer to measure the time elapsed since a given point:
+//
+//	start := time.Now()
+//	defer metricVec.ObserveSince(start, "label1", "label2")()
+//
+// The returned function must be called (typically via defer) to record the observation.
+// This pattern avoids the common pitfall where arguments to deferred functions are evaluated
+// immediately, which would result in incorrect timing measurements.
+func (v *HistogramVec) ObserveSince(start time.Time, lvs ...string) func() {
+	return func() {
+		v.WithLabelValues(lvs...).Observe(time.Since(start).Seconds())
+	}
+}
+
 // Delete deletes the metric where the variable labels are the same as those
 // passed in as labels. It returns true if a metric was deleted.
 //
@@ -292,3 +308,8 @@ func (vc *HistogramVecWithContext) With(labels map[string]string) *exemplarHisto
 		observer:                vc.HistogramVec.With(labels),
 	}
 }
+
+// ObserveSince is the wrapper of HistogramVec.ObserveSince.
+func (vc *HistogramVecWithContext) ObserveSince(start time.Time, lvs ...string) func() {
+	return vc.HistogramVec.ObserveSince(start, lvs...)
+}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
