#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/scheduler/schedule_one_test.go b/pkg/scheduler/schedule_one_test.go
index d6469f9582cf2..0279d730f6191 100644
--- a/pkg/scheduler/schedule_one_test.go
+++ b/pkg/scheduler/schedule_one_test.go
@@ -1318,6 +1318,79 @@ func TestSchedulerScheduleOne(t *testing.T) {
 	}
 }
 
+func TestHandleSchedulingFailureSkipsRecreatedPod(t *testing.T) {
+	logger, ctx := ktesting.NewTestContext(t)
+	ctx, cancel := context.WithCancel(ctx)
+	defer cancel()
+
+	oldPod := st.MakePod().Name("foo").Namespace("ns").UID("old-uid").SchedulerName(testSchedulerName).Obj()
+	recreatedPod := oldPod.DeepCopy()
+	recreatedPod.UID = "new-uid"
+
+	client := clientsetfake.NewClientset(recreatedPod)
+	informerFactory := informers.NewSharedInformerFactory(client, 0)
+	eventBroadcaster := events.NewBroadcaster(&events.EventSinkImpl{Interface: client.EventsV1()})
+
+	schedFramework, err := tf.NewFramework(ctx,
+		[]tf.RegisterPluginFunc{
+			tf.RegisterQueueSortPlugin(queuesort.Name, queuesort.New),
+			tf.RegisterBindPlugin(defaultbinder.Name, defaultbinder.New),
+		},
+		testSchedulerName,
+		frameworkruntime.WithClientSet(client),
+		frameworkruntime.WithEventRecorder(eventBroadcaster.NewRecorder(scheme.Scheme, testSchedulerName)),
+		frameworkruntime.WithInformerFactory(informerFactory),
+	)
+	if err != nil {
+		t.Fatal(err)
+	}
+
+	ar := metrics.NewMetricsAsyncRecorder(10, time.Second, ctx.Done())
+	queue := internalqueue.NewSchedulingQueue(nil, informerFactory, internalqueue.WithMetricsRecorder(ar))
+	sched := &Scheduler{
+		client:          client,
+		SchedulingQueue: queue,
+	}
+
+	informerFactory.Start(ctx.Done())
+	informerFactory.WaitForCacheSync(ctx.Done())
+
+	queue.Add(ctx, oldPod)
+	popped, err := queue.Pop(logger)
+	if err != nil {
+		t.Fatalf("Pop: %v", err)
+	}
+	if got := queue.InFlightPods(); !podListContainsPod(got, oldPod) {
+		t.Fatalf("expected popped pod to be in-flight before failure handling, got %v", got)
+	}
+
+	nominatingInfo := &fwk.NominatingInfo{NominatingMode: fwk.ModeOverride, NominatedNodeName: "node1"}
+	sched.handleSchedulingFailure(ctx, schedFramework, popped, fwk.NewStatus(fwk.Unschedulable, "no fit"), nominatingInfo, time.Now())
+
+	if err := wait.PollUntilContextTimeout(ctx, time.Millisecond, wait.ForeverTestTimeout, false, func(context.Context) (bool, error) {
+		return len(queue.InFlightPods()) == 0, nil
+	}); err != nil {
+		t.Fatalf("in-flight pod was not cleared: %v", queue.InFlightPods())
+	}
+	if got := queue.PodsInBackoffQ(); len(got) != 0 {
+		t.Fatalf("expected recreated pod to stay out of backoffQ, got %v", got)
+	}
+	if got := queue.UnschedulablePods(); len(got) != 0 {
+		t.Fatalf("expected recreated pod to stay out of unschedulablePods, got %v", got)
+	}
+	if got := queue.NominatedPodsForNode("node1"); len(got) != 0 {
+		t.Fatalf("expected recreated pod to stay out of nominated pods, got %v", got)
+	}
+
+	updatedPod, err := client.CoreV1().Pods(recreatedPod.Namespace).Get(ctx, recreatedPod.Name, metav1.GetOptions{})
+	if err != nil {
+		t.Fatalf("Get pod: %v", err)
+	}
+	if diff := cmp.Diff(recreatedPod.Status, updatedPod.Status); diff != "" {
+		t.Fatalf("expected recreated pod status to remain unchanged (-want,+got):\n%s", diff)
+	}
+}
+
 type constSigPluginConfig struct {
 	name       string
 	signature  []fwk.SignFragment
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/scheduler/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestHandleSchedulingFailureSkipsRecreatedPod"]
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
