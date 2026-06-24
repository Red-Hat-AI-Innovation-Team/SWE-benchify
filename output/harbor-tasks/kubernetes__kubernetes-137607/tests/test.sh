#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
index 222fbbced2173..79a00ae099426 100644
--- a/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
+++ b/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources_test.go
@@ -2114,12 +2114,11 @@ func testPlugin(tCtx ktesting.TContext) {
 			want: want{
 				filter: perNodeResult{
 					workerNode.Name: {
-						status: fwk.NewStatus(fwk.UnschedulableAndUnresolvable, `timed out trying to allocate devices`),
+						// Timeouts return Error so the pod retries via backoff.
+						status: fwk.AsStatus(fmt.Errorf("node %s: timed out trying to allocate devices", workerNode.Name)),
 					},
 				},
-				postfilter: result{
-					status: fwk.NewStatus(fwk.Unschedulable, `still not schedulable`),
-				},
+				// No postfilter: Error aborts scheduling immediately.
 			},
 			// Skipping this test case on Windows as a 1ns timeout is not guaranteed to
 			// expire immediately on Windows due to its coarser timer granularity -
diff --git a/test/integration/dra/core.go b/test/integration/dra/core.go
index 6d4bacdf84944..23a48b7aeb887 100644
--- a/test/integration/dra/core.go
+++ b/test/integration/dra/core.go
@@ -95,23 +95,30 @@ func testConvert(tCtx ktesting.TContext) {
 // testFilterTimeout covers the scheduler plugin'"'"'s filter timeout configuration and behavior.
 //
 // It runs the scheduler with non-standard settings and thus cannot run in parallel.
-func testFilterTimeout(tCtx ktesting.TContext, devicesPerSlice int) {
+func testFilterTimeout(tCtx ktesting.TContext, requestDeviceCount int) {
 	namespace := createTestNamespace(tCtx, nil)
 	class, driverName := createTestClass(tCtx, namespace)
-	deviceNames := make([]string, devicesPerSlice)
-	for i := range devicesPerSlice {
+	deviceNames := make([]string, requestDeviceCount)
+	for i := range requestDeviceCount {
 		deviceNames[i] = fmt.Sprintf("dev-%d", i)
 	}
 	slice := st.MakeResourceSlice("worker-0", driverName).Devices(deviceNames...)
 	createSlice(tCtx, slice.Obj())
-	otherSlice := st.MakeResourceSlice("worker-1", driverName).Devices(deviceNames...)
+	otherSlice := st.MakeResourceSlice("worker-1", driverName).Devices(deviceNames[:requestDeviceCount-1]...)
 	createdOtherSlice := createSlice(tCtx, otherSlice.Obj())
-	claim := claim.DeepCopy()
-	claim.Spec.Devices.Requests[0].Exactly.Count = int64(devicesPerSlice + 1) // Impossible to allocate.
-	claim = createClaim(tCtx, namespace, "", class, claim)
+
+	// Impossible to allocate on worker-1: not enough devices, but allocation is too
+	// dumb to notice that upfront and keeps trying until it times out.
+	// On worker-0 we can allocate, but don'"'"'t schedule because of the timeout on worker-1.
+	newClaim := func(suffix string) *resourceapi.ResourceClaim {
+		c := claim.DeepCopy()
+		c.Spec.Devices.Requests[0].Exactly.Count = int64(requestDeviceCount)
+		return createClaim(tCtx, namespace, suffix, class, c)
+	}
 
 	runSubTest(tCtx, "disabled", func(tCtx ktesting.TContext) {
-		pod := createPod(tCtx, namespace, "", podWithClaimName, claim)
+		cl := newClaim("-disabled")
+		pod := createPod(tCtx, namespace, "-disabled", podWithClaimName, cl)
 		startSchedulerWithConfig(tCtx, `
 profiles:
 - schedulerName: default-scheduler
@@ -120,11 +127,14 @@ profiles:
     args:
       filterTimeout: 0s
 `)
-		expectPodUnschedulable(tCtx, pod, "cannot allocate all claims")
+		// Without a timeout, the allocator runs to completion on both nodes.
+		// worker-0 has enough devices and succeeds, so the pod gets scheduled.
+		tCtx.ExpectNoError(e2epod.WaitForPodScheduled(tCtx, tCtx.Client(), namespace, pod.Name))
 	})
 
 	runSubTest(tCtx, "enabled", func(tCtx ktesting.TContext) {
-		pod := createPod(tCtx, namespace, "", podWithClaimName, claim)
+		cl := newClaim("-enabled")
+		pod := createPod(tCtx, namespace, "-enabled", podWithClaimName, cl)
 		startSchedulerWithConfig(tCtx, `
 profiles:
 - schedulerName: default-scheduler
@@ -133,12 +143,13 @@ profiles:
     args:
       filterTimeout: 10ms
 `)
-		expectPodUnschedulable(tCtx, pod, "timed out trying to allocate devices")
+		expectPodSchedulerError(tCtx, pod, "timed out trying to allocate devices")
 
-		// Update one slice such that allocation succeeds.
-		// The scheduler must retry and should succeed now.
+		// Update the smaller slice such that allocation also succeeds.
+		// The scheduler retries automatically (timeouts go through
+		// backoff queue, not unschedulable pool) and should succeed now.
 		createdOtherSlice.Spec.Devices = append(createdOtherSlice.Spec.Devices, resourceapi.Device{
-			Name: fmt.Sprintf("dev-%d", devicesPerSlice),
+			Name: deviceNames[requestDeviceCount-1],
 		})
 		_, err := tCtx.Client().ResourceV1().ResourceSlices().Update(tCtx, createdOtherSlice, metav1.UpdateOptions{})
 		tCtx.ExpectNoError(err, "update worker-1'"'"'s ResourceSlice")
diff --git a/test/integration/dra/dra.go b/test/integration/dra/dra.go
index 35ce2cc6daf2c..0fb153a387bca 100644
--- a/test/integration/dra/dra.go
+++ b/test/integration/dra/dra.go
@@ -133,7 +133,7 @@ func run(tCtx ktesting.TContext, whatRE string) {
 				runSubTest(tCtx, "EvictClusterWithSlices", func(tCtx ktesting.TContext) { testEvictCluster(tCtx, useNoRule) })
 				// Number of devices per slice is chosen so that Filter takes a few seconds:
 				// without a timeout, the test doesn'"'"'t run too long, but long enough that a short timeout triggers.
-				runSubTest(tCtx, "FilterTimeout", func(tCtx ktesting.TContext) { testFilterTimeout(tCtx, 20) })
+				runSubTest(tCtx, "FilterTimeout", func(tCtx ktesting.TContext) { testFilterTimeout(tCtx, 21) })
 				runSubTest(tCtx, "UsesAllResources", testUsesAllResources)
 			},
 		},
@@ -243,7 +243,7 @@ func run(tCtx ktesting.TContext, whatRE string) {
 				// Number of devices per slice is chosen so that Filter takes a few seconds: The allocator
 				// in the experimental channel has an improvement that requires a higher number here than
 				// in the incubating and stable channels.
-				runSubTest(tCtx, "FilterTimeout", func(tCtx ktesting.TContext) { testFilterTimeout(tCtx, 20) })
+				runSubTest(tCtx, "FilterTimeout", func(tCtx ktesting.TContext) { testFilterTimeout(tCtx, 21) })
 				runSubTest(tCtx, "ShareResourceClaimSequentially", testShareResourceClaimSequentially)
 				runSubTest(tCtx, "UsesAllResources", testUsesAllResources)
 			},
diff --git a/test/integration/dra/helpers.go b/test/integration/dra/helpers.go
index b52e6c10addf1..96f6967fe334c 100644
--- a/test/integration/dra/helpers.go
+++ b/test/integration/dra/helpers.go
@@ -272,17 +272,18 @@ func waitForClaimAllocatedToDevice(tCtx ktesting.TContext, namespace, claimName
 	)
 }
 
-func expectPodUnschedulable(tCtx ktesting.TContext, pod *v1.Pod, reason string) {
+func expectPodSchedulerError(tCtx ktesting.TContext, pod *v1.Pod, reason string) {
 	tCtx.Helper()
-	tCtx.ExpectNoError(e2epod.WaitForPodNameUnschedulableInNamespace(tCtx, tCtx.Client(), pod.Name, pod.Namespace), fmt.Sprintf("expected pod to be unschedulable because %q", reason))
-	pod, err := tCtx.Client().CoreV1().Pods(pod.Namespace).Get(tCtx, pod.Name, metav1.GetOptions{})
-	tCtx.ExpectNoError(err)
-	gomega.NewWithT(tCtx).Expect(pod).To(gomega.HaveField("Status.Conditions", gomega.ContainElement(gstruct.MatchFields(gstruct.IgnoreExtras, gstruct.Fields{
-		"Type":    gomega.Equal(v1.PodScheduled),
-		"Status":  gomega.Equal(v1.ConditionFalse),
-		"Reason":  gomega.Equal(v1.PodReasonUnschedulable),
-		"Message": gomega.ContainSubstring(reason),
-	}))))
+	tCtx.ExpectNoError(e2epod.WaitForPodCondition(tCtx, tCtx.Client(), pod.Namespace, pod.Name, v1.PodReasonSchedulerError, time.Minute, func(pod *v1.Pod) (bool, error) {
+		if pod.Status.Phase == v1.PodPending {
+			for _, cond := range pod.Status.Conditions {
+				if cond.Type == v1.PodScheduled && cond.Status == v1.ConditionFalse && cond.Reason == v1.PodReasonSchedulerError && strings.Contains(cond.Message, reason) {
+					return true, nil
+				}
+			}
+		}
+		return false, nil
+	}), fmt.Sprintf("expected pod to have scheduler error because %q", reason))
 }
 
 type nodeInfo struct {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestPlugin"]

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
