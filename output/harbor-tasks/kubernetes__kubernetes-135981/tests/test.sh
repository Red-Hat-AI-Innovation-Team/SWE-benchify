#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/scheduler/backend/queue/scheduling_queue_test.go b/pkg/scheduler/backend/queue/scheduling_queue_test.go
index 07f03a24d073f..0467d8efb34b4 100644
--- a/pkg/scheduler/backend/queue/scheduling_queue_test.go
+++ b/pkg/scheduler/backend/queue/scheduling_queue_test.go
@@ -1534,9 +1534,13 @@ func TestPriorityQueue_Activate(t *testing.T) {
 
 type preEnqueuePlugin struct {
 	allowlists []string
+	name       string
 }
 
 func (pl *preEnqueuePlugin) Name() string {
+	if pl.name != "" {
+		return pl.name
+	}
 	return "preEnqueuePlugin"
 }
 
@@ -3182,6 +3186,12 @@ var (
 	add = func(t *testing.T, logger klog.Logger, queue *PriorityQueue, pInfo *framework.QueuedPodInfo) {
 		queue.Add(logger, pInfo.Pod)
 	}
+	pop = func(t *testing.T, logger klog.Logger, queue *PriorityQueue, _ *framework.QueuedPodInfo) {
+		_, err := queue.Pop(logger)
+		if err != nil {
+			t.Fatalf("Unexpected error during Pop: %v", err)
+		}
+	}
 	popAndRequeueAsUnschedulable = func(t *testing.T, logger klog.Logger, queue *PriorityQueue, pInfo *framework.QueuedPodInfo) {
 		// To simulate the pod is failed in scheduling in the real world, Pop() the pod from activeQ before AddUnschedulableIfNotPresent() below.
 		// UnschedulablePlugins will get cleared by Pop, so make a copy first.
@@ -3362,8 +3372,8 @@ func TestPodTimestamp(t *testing.T) {
 	}
 }
 
-// TestPendingPodsMetric tests Prometheus metrics related with pending pods
-func TestPendingPodsMetric(t *testing.T) {
+// TestSchedulerPodsMetric tests Prometheus metrics
+func TestSchedulerPodsMetric(t *testing.T) {
 	timestamp := time.Now()
 	preenqueuePluginName := "preEnqueuePlugin"
 	metrics.Register()
@@ -4647,3 +4657,189 @@ func TestPriorityQueue_GetPod(t *testing.T) {
 		})
 	}
 }
+
+func TestUnschedulablePodsMetric(t *testing.T) {
+	type step func(t *testing.T, logger klog.Logger, q *PriorityQueue)
+
+	addPod := func(pInfo *framework.QueuedPodInfo) step {
+		return func(t *testing.T, logger klog.Logger, q *PriorityQueue) {
+			add(t, logger, q, pInfo)
+		}
+	}
+	deletePod := func(pInfo *framework.QueuedPodInfo) step {
+		return func(t *testing.T, logger klog.Logger, q *PriorityQueue) {
+			deletePod(t, logger, q, pInfo)
+		}
+	}
+	popPod := func() step {
+		return func(t *testing.T, logger klog.Logger, q *PriorityQueue) {
+			pop(t, logger, q, nil)
+		}
+	}
+	moveAllToActiveOrBackoffQ := func() step {
+		return func(t *testing.T, logger klog.Logger, q *PriorityQueue) {
+			moveAllToActiveOrBackoffQ(t, logger, q, nil)
+		}
+	}
+	updatePluginAllowList := func(pluginName string, list []string) step {
+		return func(t *testing.T, logger klog.Logger, q *PriorityQueue) {
+			q.preEnqueuePluginMap[""][pluginName].(*preEnqueuePlugin).allowlists = list
+		}
+	}
+
+	pluginName1 := "plugin1"
+	pluginName2 := "plugin2"
+	queueable := "queueable"
+	timestamp := time.Now()
+	pod := &framework.QueuedPodInfo{
+		PodInfo: mustNewPodInfo(
+			st.MakePod().Name("podA").Namespace("namespaceA").Label(queueable, "").UID("someUid").Obj()),
+		Timestamp:            timestamp,
+		UnschedulablePlugins: sets.New[string](),
+	}
+
+	resetMetrics := func() {
+		metrics.UnschedulableReason(pluginName1, "").Set(0)
+		metrics.UnschedulableReason(pluginName2, "").Set(0)
+	}
+
+	makeGated := func(pInfo *framework.QueuedPodInfo) *framework.QueuedPodInfo {
+		return setQueuedPodInfoGated(pInfo.DeepCopy(), pluginName1, []fwk.ClusterEvent{framework.EventUnschedulableTimeout})
+	}
+
+	tests := []struct {
+		name            string
+		steps           []step
+		expectedMetrics []int
+	}{
+		{
+			name: "Unschedulable pods metric must be 0 after a pod is gated, ungated, re-queued, and eventually popped from the scheduling queue",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				moveAllToActiveOrBackoffQ(),
+				updatePluginAllowList(pluginName1, []string{queueable}),
+				moveAllToActiveOrBackoffQ(),
+				popPod(),
+			},
+			expectedMetrics: []int{0, 0},
+		},
+		{
+			name: "Unschedulable pods metric must be 0 after pod is gated and then deleted",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				moveAllToActiveOrBackoffQ(),
+				deletePod(pod),
+			},
+			expectedMetrics: []int{0, 0},
+		},
+		{
+			name: "Unschedulable pods metric must be 1 after pod is gated multiple time by the same plugin",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				moveAllToActiveOrBackoffQ(),
+			},
+			expectedMetrics: []int{1, 0},
+		},
+		{
+			name: "Unschedulable pods metric must be 0 after non gated pods is added and then deleted",
+			steps: []step{
+				addPod(pod),
+				deletePod(pod),
+			},
+			expectedMetrics: []int{0, 0},
+		},
+		{
+			name: "Unschedulable pods metric should not be duplicate if gated pods added and then gated with the same plugin again",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(makeGated(pod)),
+				moveAllToActiveOrBackoffQ(),
+			},
+			expectedMetrics: []int{1, 0},
+		},
+		{
+			name: "Unschedulable pods metric should be 0 if pod was gated by two plugins sequentially and then ungated and popped",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				updatePluginAllowList(pluginName1, []string{queueable}),
+				updatePluginAllowList(pluginName2, []string{}),
+				moveAllToActiveOrBackoffQ(),
+				updatePluginAllowList(pluginName2, []string{queueable}),
+				moveAllToActiveOrBackoffQ(),
+				popPod(),
+			},
+			expectedMetrics: []int{0, 0},
+		},
+		{
+			name: "Unschedulable pods metric should be 0 if pod was gated by two plugins sequentially and then deleted",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				updatePluginAllowList(pluginName1, []string{queueable}),
+				updatePluginAllowList(pluginName2, []string{}),
+				moveAllToActiveOrBackoffQ(),
+				deletePod(pod),
+			},
+			expectedMetrics: []int{0, 0},
+		},
+		{
+			name: "Unschedulable pods metric should be 1 for both plugins if pod was gated by two plugins sequentially",
+			steps: []step{
+				updatePluginAllowList(pluginName1, []string{}),
+				addPod(pod),
+				updatePluginAllowList(pluginName1, []string{queueable}),
+				updatePluginAllowList(pluginName2, []string{}),
+				moveAllToActiveOrBackoffQ(),
+			},
+			expectedMetrics: []int{1, 1},
+		},
+	}
+
+	for _, tt := range tests {
+		t.Run(tt.name, func(t *testing.T) {
+			logger, ctx := ktesting.NewTestContext(t)
+			ctx, cancel := context.WithCancel(ctx)
+			defer cancel()
+			resetMetrics()
+
+			m := makeEmptyQueueingHintMapPerProfile()
+			m[""][framework.EventUnschedulableTimeout] = []*QueueingHintFunction{
+				{
+					PluginName:     pluginName1,
+					QueueingHintFn: queueHintReturnQueue,
+				},
+				{
+					PluginName:     pluginName2,
+					QueueingHintFn: queueHintReturnQueue,
+				},
+			}
+
+			plugin1 := preEnqueuePlugin{name: pluginName1, allowlists: []string{queueable}}
+			plugin2 := preEnqueuePlugin{name: pluginName2, allowlists: []string{queueable}}
+
+			preenq := map[string]map[string]fwk.PreEnqueuePlugin{"": {pluginName1: &plugin1, pluginName2: &plugin2}}
+			recorder := metrics.NewMetricsAsyncRecorder(3, 20*time.Microsecond, ctx.Done())
+			q := NewTestQueue(ctx, newDefaultQueueSort(), WithClock(testingclock.NewFakeClock(timestamp)), WithPreEnqueuePluginMap(preenq), WithMetricsRecorder(recorder), WithQueueingHintMapPerProfile(m))
+
+			for _, step := range tt.steps {
+				step(t, logger, q)
+			}
+
+			for i, pluginName := range []string{pluginName1, pluginName2} {
+				val, err := testutil.GetGaugeMetricValue(metrics.UnschedulableReason(pluginName, ""))
+
+				if err != nil {
+					t.Errorf("Error while collection metric value:\n%s", err)
+				}
+				if int(val) != tt.expectedMetrics[i] {
+					t.Errorf("Unexpected metric for plugin %s result expected %d, actual %d", pluginName, tt.expectedMetrics[i], int(val))
+				}
+			}
+
+		})
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/scheduler/backend/queue/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestUnschedulablePodsMetric"]
passed = set()
with open("/tmp/test_output.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action == "pass":
            passed.add(test)
            # Also add the bare test name (no subtest suffix)
            passed.add(test.split("/")[0])

all_pass = all(
    t in passed or t.split("/")[0] in passed
    for t in f2p
)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if t not in passed and t.split("/")[0] not in passed]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
