#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/eviction/eviction_manager_test.go b/pkg/kubelet/eviction/eviction_manager_test.go
index de8c6984665a0..67783c0f98ae6 100644
--- a/pkg/kubelet/eviction/eviction_manager_test.go
+++ b/pkg/kubelet/eviction/eviction_manager_test.go
@@ -3095,3 +3095,79 @@ func TestManagerWithLocalStorageCapacityIsolationOpen(t *testing.T) {
 		t.Fatalf("Unexpected evicted pod (-want,+got):\n%s", diff)
 	}
 }
+
+func TestContainerEphemeralStorageLimitEvictionForRestartableInitContainers(t *testing.T) {
+	tCtx := ktesting.Init(t)
+
+	initContainer := newRestartableInitContainer("sidecar", newResourceList("", "", ""), newResourceList("", "", "10Mi"))
+	mainContainer := newContainer("main", newResourceList("", "", ""), newResourceList("", "", ""))
+
+	pod := newPod("sidecar-ephemeral-repro", 0, []v1.Container{mainContainer}, nil)
+	pod.Spec.InitContainers = []v1.Container{initContainer}
+
+	sidecarQuantity := resource.MustParse("50Mi")
+	sidecarUsed := uint64(sidecarQuantity.Value())
+	mainUsed := uint64(0)
+	podStats := statsapi.PodStats{
+		PodRef: statsapi.PodReference{
+			Name: pod.Name, Namespace: pod.Namespace, UID: string(pod.UID),
+		},
+		Containers: []statsapi.ContainerStats{
+			{
+				Name:   "sidecar",
+				Logs:   &statsapi.FsStats{UsedBytes: &sidecarUsed},
+				Rootfs: &statsapi.FsStats{UsedBytes: &sidecarUsed},
+			},
+			{
+				Name:   "main",
+				Logs:   &statsapi.FsStats{UsedBytes: &mainUsed},
+				Rootfs: &statsapi.FsStats{UsedBytes: &mainUsed},
+			},
+		},
+	}
+
+	diskStat := diskStats{
+		rootFsAvailableBytes:  "1Gi",
+		imageFsAvailableBytes: "200Mi",
+		podStats:              map[*v1.Pod]statsapi.PodStats{pod: podStats},
+	}
+	summaryProvider := &fakeSummaryProvider{result: makeDiskStats(diskStat)}
+
+	config := Config{
+		MaxPodGracePeriodSeconds: 5,
+		PressureTransitionPeriod: time.Minute * 5,
+		Thresholds:               []evictionapi.Threshold{},
+	}
+
+	podKiller := &mockPodKiller{}
+	nodeRef := &v1.ObjectReference{Kind: "Node", Name: "test", UID: types.UID("test"), Namespace: ""}
+	fakeClock := testingclock.NewFakeClock(time.Now())
+
+	mgr := &managerImpl{
+		clock:                         fakeClock,
+		killPodFunc:                   podKiller.killPodNow,
+		imageGC:                       &mockDiskGC{err: nil},
+		containerGC:                   &mockDiskGC{err: nil},
+		config:                        config,
+		recorder:                      &record.FakeRecorder{},
+		summaryProvider:               summaryProvider,
+		nodeRef:                       nodeRef,
+		localStorageCapacityIsolation: true,
+		dedicatedImageFs:              ptr.To(false),
+	}
+
+	activePodsFunc := func() []*v1.Pod {
+		return []*v1.Pod{pod}
+	}
+
+	evictedPods, err := mgr.synchronize(tCtx, &mockDiskInfoProvider{dedicatedImageFs: ptr.To(false)}, activePodsFunc)
+	if err != nil {
+		t.Fatalf("Manager should not have error but got %v", err)
+	}
+	if podKiller.pod == nil {
+		t.Fatalf("Manager should have evicted the pod for restartable init container exceeding ephemeral-storage limit")
+	}
+	if len(evictedPods) != 1 || evictedPods[0].Name != pod.Name {
+		t.Fatalf("Expected evicted pod %q, got %v", pod.Name, evictedPods)
+	}
+}
diff --git a/test/e2e_node/eviction_test.go b/test/e2e_node/eviction_test.go
index 4081f4c973c4e..47052ef026d9a 100644
--- a/test/e2e_node/eviction_test.go
+++ b/test/e2e_node/eviction_test.go
@@ -435,6 +435,14 @@ var _ = SIGDescribe("LocalStorageCapacityIsolationEviction", framework.WithSlow(
 				evictionPriority: 0, // This pod should not be evicted because it uses less than its limit
 				pod:              diskConsumingPod("container-disk-below-sizelimit", useUnderLimit, nil, v1.ResourceRequirements{Limits: containerLimit}),
 			},
+			{
+				evictionPriority: 1, // The restartable init container (sidecar) exceeds its container ephemeral-storage limit, so the pod should be evicted.
+				pod:              diskConsumingSidecarPod("sidecar-container-disk-limit", useOverLimit, v1.ResourceRequirements{Limits: containerLimit}),
+			},
+			{
+				evictionPriority: 0, // The restartable init container (sidecar) stays under its limit, so the pod should not be evicted.
+				pod:              diskConsumingSidecarPod("sidecar-container-disk-below-sizelimit", useUnderLimit, v1.ResourceRequirements{Limits: containerLimit}),
+			},
 		})
 	})
 })
@@ -1280,6 +1288,41 @@ func diskConsumingPod(name string, diskConsumedMB int, volumeSource *v1.VolumeSo
 	return podWithCommand(volumeSource, resources, diskConsumedMB, name, fmt.Sprintf("dd if=/dev/urandom of=%s${i} bs=1048576 count=1 2>/dev/null; sleep .1;", filepath.Join(path, "file")), true)
 }
 
+// diskConsumingSidecarPod returns a pod whose restartable init container (sidecar)
+// writes diskConsumedMB MB to its writable layer, with the supplied resource
+// requirements applied to the sidecar. The main container only sleeps so that the
+// pod'"'"'s eligibility for eviction is determined entirely by the sidecar'"'"'s disk usage.
+func diskConsumingSidecarPod(name string, diskConsumedMB int, sidecarResources v1.ResourceRequirements) *v1.Pod {
+	var gracePeriod int64 = 1
+	return &v1.Pod{
+		ObjectMeta: metav1.ObjectMeta{Name: fmt.Sprintf("%s-pod", name)},
+		Spec: v1.PodSpec{
+			RestartPolicy:                 v1.RestartPolicyNever,
+			TerminationGracePeriodSeconds: &gracePeriod,
+			InitContainers: []v1.Container{
+				{
+					Image:         busyboxImage,
+					Name:          fmt.Sprintf("%s-sidecar", name),
+					RestartPolicy: &containerRestartPolicyAlways,
+					Command: []string{
+						"sh",
+						"-c",
+						fmt.Sprintf("i=0; while [ $i -lt %d ]; do dd if=/dev/urandom of=file${i} bs=1048576 count=1 2>/dev/null; sleep .1; i=$(($i+1)); done; while true; do sleep 5; done", diskConsumedMB),
+					},
+					Resources: sidecarResources,
+				},
+			},
+			Containers: []v1.Container{
+				{
+					Image:   busyboxImage,
+					Name:    fmt.Sprintf("%s-container", name),
+					Command: []string{"sh", "-c", "sleep infinity"},
+				},
+			},
+		},
+	}
+}
+
 func pidConsumingPod(name string, numProcesses int) *v1.Pod {
 	// Slowing down the iteration speed to prevent a race condition where eviction may occur
 	// before the correct number of processes is captured in the stats during a sudden surge in processes.
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestContainerEphemeralStorageLimitEvictionForRestartableInitContainers"]

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
