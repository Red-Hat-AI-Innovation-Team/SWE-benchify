#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/scheduler/schedule_one_podgroup_test.go b/pkg/scheduler/schedule_one_podgroup_test.go
index b23d568d193e6..bf3235777c93a 100644
--- a/pkg/scheduler/schedule_one_podgroup_test.go
+++ b/pkg/scheduler/schedule_one_podgroup_test.go
@@ -424,6 +424,141 @@ func TestPodGroupCycle_UpdateSnapshotError(t *testing.T) {
 	}
 }
 
+func TestPodGroupCycle_FillsPodResultsOnFewerResults(t *testing.T) {
+	testPodGroup := st.MakePodGroup().Name("pg").Namespace("default").Obj()
+	p1 := st.MakePod().Name("p1").UID("p1").PodGroupName("pg").SchedulerName("test-scheduler").Obj()
+	p2 := st.MakePod().Name("p2").UID("p2").PodGroupName("pg").SchedulerName("test-scheduler").Obj()
+	p3 := st.MakePod().Name("p3").UID("p3").PodGroupName("pg").SchedulerName("test-scheduler").Obj()
+	testNode := st.MakeNode().Name("node1").UID("node1").Obj()
+
+	qInfo1 := &framework.QueuedPodInfo{PodInfo: &framework.PodInfo{Pod: p1}}
+	qInfo2 := &framework.QueuedPodInfo{PodInfo: &framework.PodInfo{Pod: p2}}
+	qInfo3 := &framework.QueuedPodInfo{PodInfo: &framework.PodInfo{Pod: p3}}
+
+	podGroupInfo := &framework.QueuedPodGroupInfo{
+		QueuedPodInfos: []*framework.QueuedPodInfo{qInfo1, qInfo2, qInfo3},
+		PodGroupInfo: &framework.PodGroupInfo{
+			Name:            "pg",
+			Namespace:       "default",
+			UnscheduledPods: []*v1.Pod{p1, p2, p3},
+		},
+	}
+
+	_, ctx := ktesting.NewTestContext(t)
+	ctx, cancel := context.WithCancel(ctx)
+	defer cancel()
+
+	fakePlugin := &fakePodGroupPlugin{
+		filterStatus: map[string]*fwk.Status{
+			"p1": nil,
+			"p2": fwk.NewStatus(fwk.Error, "filter error for p2"),
+			"p3": nil,
+		},
+		permitStatus: map[string]*fwk.Status{
+			"p1": nil,
+			"p2": nil,
+			"p3": nil,
+		},
+	}
+
+	registry := []tf.RegisterPluginFunc{
+		tf.RegisterQueueSortPlugin(queuesort.Name, queuesort.New),
+		tf.RegisterBindPlugin(defaultbinder.Name, defaultbinder.New),
+		tf.RegisterPostFilterPlugin(fakePlugin.Name(), func(_ context.Context, _ runtime.Object, _ fwk.Handle) (fwk.Plugin, error) {
+			return fakePlugin, nil
+		}),
+		tf.RegisterPermitPlugin(fakePlugin.Name(), func(_ context.Context, _ runtime.Object, _ fwk.Handle) (fwk.Plugin, error) {
+			return fakePlugin, nil
+		}),
+		tf.RegisterFilterPlugin(fakePlugin.Name(), func(_ context.Context, _ runtime.Object, _ fwk.Handle) (fwk.Plugin, error) {
+			return fakePlugin, nil
+		}),
+	}
+
+	client := clientsetfake.NewSimpleClientset(testPodGroup, testNode)
+	informerFactory := informers.NewSharedInformerFactory(client, 0)
+	podGroupLister := informerFactory.Scheduling().V1alpha3().PodGroups().Lister()
+
+	informerFactory.Start(ctx.Done())
+	informerFactory.WaitForCacheSync(ctx.Done())
+	queue := internalqueue.NewSchedulingQueue(nil, informerFactory)
+	snapshot := internalcache.NewEmptySnapshot()
+
+	schedFwk, err := tf.NewFramework(ctx, registry, "test-scheduler",
+		frameworkruntime.WithInformerFactory(informerFactory),
+		frameworkruntime.WithSnapshotSharedLister(snapshot),
+		frameworkruntime.WithPodNominator(queue),
+		frameworkruntime.WithClientSet(client),
+		frameworkruntime.WithEventRecorder(events.NewFakeRecorder(100)),
+	)
+	if err != nil {
+		t.Fatalf("Failed to create new framework: %v", err)
+	}
+
+	cache := internalcache.New(ctx, nil, true)
+	logger, ctx := ktesting.NewTestContext(t)
+	cache.AddNode(logger, testNode)
+
+	handledPods := make(map[string]*fwk.Status)
+	var lock sync.Mutex
+
+	sched := &Scheduler{
+		Profiles:                       profile.Map{"test-scheduler": schedFwk},
+		SchedulingQueue:                internalqueue.NewTestQueue(ctx, nil),
+		Cache:                          cache,
+		client:                         client,
+		podGroupLister:                 podGroupLister,
+		nodeInfoSnapshot:               internalcache.NewEmptySnapshot(),
+		workloadAwarePreemptionEnabled: false,
+		FailureHandler: func(ctx context.Context, fwk framework.Framework, p *framework.QueuedPodInfo, status *fwk.Status, ni *fwk.NominatingInfo, start time.Time) {
+			lock.Lock()
+			defer lock.Unlock()
+			handledPods[p.Pod.Name] = status
+		},
+	}
+
+	// Checking that scheduling algorithm is returning shorter list
+	if err := sched.Cache.UpdateSnapshot(logger, sched.nodeInfoSnapshot); err != nil {
+		t.Fatalf("Failed to update snapshot: %v", err)
+	}
+	sched.SchedulePod = sched.schedulePod
+	schedulePodResult := sched.podGroupSchedulingAlgorithm(ctx, schedFwk, framework.NewCycleState(), podGroupInfo, runAllPostFilters)
+	if len(schedulePodResult.podResults) != 2 {
+		t.Errorf("Expected 2 pod results, got %d", len(schedulePodResult.podResults))
+	}
+
+	// Run the scheduling cycle and check that all pods are handled.
+	sched.podGroupCycle(ctx, schedFwk, framework.NewCycleState(), podGroupInfo)
+
+	lock.Lock()
+	defer lock.Unlock()
+
+	if len(handledPods) != 3 {
+		t.Errorf("Expected FailureHandler to be called for 3 pods, but got called for %d", len(handledPods))
+	}
+
+	expectedGroupErrMsg := "failed to schedule other pod from a pod group: running \"FakePodGroupPlugin\" filter plugin: filter error for p2"
+	expectedP2ErrMsg := "running \"FakePodGroupPlugin\" filter plugin: filter error for p2"
+
+	if status, ok := handledPods["p1"]; !ok {
+		t.Errorf("Expected FailureHandler to be called for p1")
+	} else if status.AsError() == nil || status.AsError().Error() != expectedGroupErrMsg {
+		t.Errorf("Expected status error for p1 to be %q, got %v", expectedGroupErrMsg, status.AsError())
+	}
+
+	if status, ok := handledPods["p2"]; !ok {
+		t.Errorf("Expected FailureHandler to be called for p2")
+	} else if status.AsError() == nil || status.AsError().Error() != expectedP2ErrMsg {
+		t.Errorf("Expected status error for p2 to be %q, got %v", expectedP2ErrMsg, status.AsError())
+	}
+
+	if status, ok := handledPods["p3"]; !ok {
+		t.Errorf("Expected FailureHandler to be called for p3")
+	} else if status.AsError() == nil || status.AsError().Error() != expectedGroupErrMsg {
+		t.Errorf("Expected status error for p3 to be %q, got %v", expectedGroupErrMsg, status.AsError())
+	}
+}
+
 func TestPodGroupCycle_PodGroupPostFilter(t *testing.T) {
 	tests := []struct {
 		name                             string
@@ -1391,8 +1526,17 @@ func TestSubmitPodGroupAlgorithmResult(t *testing.T) {
 		{
 			name: "Unschedulable for the entire pod group",
 			algorithmResult: podGroupAlgorithmResult{
-				status:     fwk.NewStatus(fwk.Unschedulable, "node affinity mismatch"),
-				podResults: []algorithmResult{},
+				status: fwk.NewStatus(fwk.Unschedulable, "node affinity mismatch"),
+				podResults: []algorithmResult{{
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Unschedulable),
+				}, {
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Unschedulable),
+				}, {
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Unschedulable),
+				}},
 			},
 			expectBound:  sets.New[string](),
 			expectFailed: sets.New("p1", "p2", "p3"),
@@ -1414,6 +1558,9 @@ func TestSubmitPodGroupAlgorithmResult(t *testing.T) {
 				}, {
 					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
 					status:         fwk.NewStatus(fwk.Error, "plugin returned error"),
+				}, {
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Error, "plugin returned error"),
 				}},
 			},
 			expectBound:  sets.New[string](),
@@ -1440,6 +1587,9 @@ func TestSubmitPodGroupAlgorithmResult(t *testing.T) {
 				}, {
 					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
 					status:         fwk.NewStatus(fwk.Error, "internal failure"),
+				}, {
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Error, "internal failure"),
 				}},
 			},
 			expectBound:  sets.New[string](),
@@ -1546,6 +1696,9 @@ func TestSubmitPodGroupAlgorithmResult(t *testing.T) {
 				}, {
 					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
 					status:         fwk.NewStatus(fwk.Error),
+				}, {
+					scheduleResult: ScheduleResult{SuggestedHost: "", nominatingInfo: clearNominatedNode},
+					status:         fwk.NewStatus(fwk.Error),
 				}},
 			},
 			expectBound:  sets.New[string](),
@@ -1557,6 +1710,25 @@ func TestSubmitPodGroupAlgorithmResult(t *testing.T) {
 				Message: "All pods scheduled",
 			},
 		},
+		{
+			name: "Different number of pods in result and queue, should fail all queue pods",
+			algorithmResult: podGroupAlgorithmResult{
+				status: fwk.NewStatus(fwk.Error),
+				podResults: []algorithmResult{{
+					scheduleResult: ScheduleResult{SuggestedHost: "node1"},
+					status:         nil,
+					permitStatus:   nil,
+				}},
+			},
+			expectBound:  sets.New[string](),
+			expectFailed: sets.New("p1", "p2", "p3"),
+			expectCondition: &metav1.Condition{
+				Type:    schedulingapi.PodGroupScheduled,
+				Status:  metav1.ConditionFalse,
+				Reason:  schedulingapi.PodGroupReasonSchedulerError,
+				Message: fwk.NewStatus(fwk.Error, "scheduling error for pod group, some pods were not processed").AsError().Error(),
+			},
+		},
 	}
 
 	for _, tt := range tests {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/scheduler/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestSubmitPodGroupAlgorithmResult"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
