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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestHandleSchedulingFailureSkipsRecreatedPod"]

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

def parse_junit_xml(text):
    # Minimal XML parser for JUnit format (no lxml dependency)
    results = {}
    for m in re.finditer(r'<testcase[^>]*name="([^"]*)"[^>]*classname="([^"]*)"[^>]*(/?>)', text):
        name, classname, close = m.groups()
        test_id = f"{classname}.{name}"
        # Check for failure/error child elements
        if close == "/>":
            results[test_id] = "passed"
        else:
            # Find the matching </testcase> and check contents
            start = m.end()
            end = text.find("</testcase>", start)
            block = text[start:end] if end != -1 else ""
            if "<failure" in block or "<error" in block:
                results[test_id] = "failed"
            elif "<skipped" in block:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results

def parse_cargo_test(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            test_id = m.group(1)
            status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_tap(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"(ok|not ok)\s+\d+\s*-?\s*(.*)", line)
        if m:
            status = "passed" if m.group(1) == "ok" else "failed"
            desc = m.group(2).strip()
            if "# SKIP" in desc:
                status = "skipped"
                desc = desc.split("# SKIP")[0].strip()
            results[desc] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
    "junit-xml": parse_junit_xml,
    "cargo-test": parse_cargo_test,
    "tap": parse_tap,
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
