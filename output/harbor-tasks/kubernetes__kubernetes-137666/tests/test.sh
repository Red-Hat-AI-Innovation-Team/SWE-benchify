#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/statefulset/stateful_set_control_test.go b/pkg/controller/statefulset/stateful_set_control_test.go
index 1fbd8f3b0502f..9a6da601235e7 100644
--- a/pkg/controller/statefulset/stateful_set_control_test.go
+++ b/pkg/controller/statefulset/stateful_set_control_test.go
@@ -58,6 +58,7 @@ import (
 	"k8s.io/kubernetes/pkg/controller/history"
 	"k8s.io/kubernetes/pkg/controller/statefulset/metrics"
 	"k8s.io/kubernetes/pkg/features"
+	testingclock "k8s.io/utils/clock/testing"
 )
 
 type invariantFunc func(set *apps.StatefulSet, om *fakeObjectManager) error
@@ -1260,6 +1261,426 @@ func TestStatefulSetControlRollingUpdateWithMaxUnavailableInOrderedModeVerifyInv
 	}
 }
 
+// Regression test for https://github.com/kubernetes/kubernetes/issues/137409.
+// When MaxUnavailableStatefulSet is enabled and a pod with Parallel pod management is on an
+// old revision AND already unavailable (e.g. crashlooping), the controller must still delete
+// the pod to trigger a revision update. The bug caused a deadlock: the pod could never become
+// available because it had the wrong revision, and the controller would never update it because
+// it treated the pod'"'"'s existing unavailability as consuming the entire maxUnavailable budget.
+// For OrderedReady pod management the original strict behaviour is preserved for backwards
+// compatibility.
+func TestStatefulSetControlRollingUpdateWithMaxUnavailableAndUnavailableStalePod(t *testing.T) {
+	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.MaxUnavailableStatefulSet, true)
+
+	fakeClock := testingclock.NewFakeClock(time.Date(2026, time.March, 12, 12, 0, 0, 0, time.UTC))
+
+	testCases := []struct {
+		name                      string
+		podManagementPolicy       apps.PodManagementPolicyType
+		replicas                  int32
+		partition                 int32
+		maxUnavailable            intstr.IntOrString
+		minReadySeconds           int32
+		unavailableOrdinals       []int
+		makeUnavailable           func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error
+		expectedRemainingOrdinals []int
+	}{
+		{
+			name:                "Parallel/single replica: unavailable pod on old revision must be updated",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            1,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{0},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{},
+		},
+		{
+			name:                "Parallel/3 replicas, highest-ordinal pod unavailable on old revision",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1},
+		},
+		{
+			name:                "Parallel/5 replicas, 2 pods unavailable on old revision",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(2),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "OrderedReady/single replica: unavailable pod on old revision blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            1,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{0},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0},
+		},
+		{
+			name:                "OrderedReady/3 replicas, highest-ordinal pod unavailable on old revision blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "OrderedReady/5 replicas, 2 pods unavailable on old revision blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(2),
+			unavailableOrdinals: []int{4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3},
+		},
+		{
+			name:                "Parallel/3 replicas, highest-ordinal pod terminating on old revision: budget consumed, next pod must NOT be deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodTerminated(set, ordinal)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "OrderedReady/3 replicas, highest-ordinal pod terminating on old revision blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodTerminated(set, ordinal)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "Parallel/5 replicas maxUnavailable=3, pod-4 terminating + pod-3 crashlooping: only 1 more pods should be deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				if ordinal == 3 {
+					_, err := spc.setPodReadyCondition(set, ordinal, false)
+					return err
+				}
+				_, err := spc.setPodTerminated(set, ordinal)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 4},
+		},
+		{
+			name:                "Parallel/3 replicas, highest-ordinal pod ready but within minReadySeconds on old revision: pod gets deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			minReadySeconds:     30,
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodAvailable(set, ordinal, fakeClock.Now())
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1},
+		},
+		{
+			name:                "OrderedReady/3 replicas, highest-ordinal pod ready but within minReadySeconds on old revision blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            3,
+			maxUnavailable:      intstr.FromInt32(1),
+			minReadySeconds:     30,
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodAvailable(set, ordinal, fakeClock.Now())
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "Parallel/5 replicas, pod-3 unavailable + pod-4 terminating on old revision, only 1 more pods should be deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				if ordinal == 3 {
+					_, err := spc.setPodReadyCondition(set, ordinal, false)
+					return err
+				}
+				_, err := spc.setPodTerminated(set, ordinal)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 4},
+		},
+		{
+			name:                "Parallel/5 replicas, pod-3 terminating + pod-4 unavailable on old revision, only 1 more pods should be deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				if ordinal == 3 {
+					_, err := spc.setPodTerminated(set, ordinal)
+					return err
+				}
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 3},
+		},
+		{
+			name:                "OrderedReady/5 replicas, 1 pod unavailable(#3) + 1 pod terminating(#4) on old revision",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				if ordinal == 3 {
+					_, err := spc.setPodReadyCondition(set, ordinal, false)
+					return err
+				}
+				_, err := spc.setPodTerminated(set, ordinal)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 4},
+		},
+		{
+			name:                "OrderedReady/5 replicas, 1 pod terminating(#3) + 1 pod unavailable(#4) on old revision",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				if ordinal == 3 {
+					_, err := spc.setPodTerminated(set, ordinal)
+					return err
+				}
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3},
+		},
+		{
+			name:                "Parallel/5 replicas partition=2: unavailable pod in update range (#4) gets deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			partition:           2,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3},
+		},
+		{
+			name:                "Parallel/5 replicas partition=2: unavailable pod at partition boundary (#2) gets deleted, highest stale pod (#4) is unaffected",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			partition:           2,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{2},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 3, 4},
+		},
+		{
+			name:                "Parallel/5 replicas partition=2: unavailable pod below partition (#1) consumes budget, no update",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			partition:           2,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{1},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3, 4},
+		},
+		{
+			name:                "OrderedReady/5 replicas partition=2: unavailable pod in update range (#4) blocks update",
+			podManagementPolicy: apps.OrderedReadyPodManagement,
+			replicas:            5,
+			partition:           2,
+			maxUnavailable:      intstr.FromInt32(1),
+			unavailableOrdinals: []int{4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3, 4},
+		},
+		{
+			name:                "Parallel/5 replicas partition=3 maxUnavailable=2: both update-range pods unavailable, both get deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			partition:           3,
+			maxUnavailable:      intstr.FromInt32(2),
+			unavailableOrdinals: []int{3, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2},
+		},
+		{
+			name:                "Parallel/5 replicas partition=3 maxUnavailable=2: pod below partition (#1) + pod in range (#4) unavailable, one pod deleted",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			partition:           3,
+			maxUnavailable:      intstr.FromInt32(2),
+			unavailableOrdinals: []int{1, 4},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{0, 1, 2, 3},
+		},
+		{
+			name:                "Parallel/4 replicas maxUnavailable=2: lower-ordinal unavailable pods get deleted, higher-ordinal good pods must stay",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            4,
+			maxUnavailable:      intstr.FromInt32(2),
+			unavailableOrdinals: []int{0, 1},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{2, 3},
+		},
+		{
+			name:                "Parallel/5 replicas maxUnavailable=3: 2 lower-ordinal unavailable pods deleted first, 1 good pod from the top",
+			podManagementPolicy: apps.ParallelPodManagement,
+			replicas:            5,
+			maxUnavailable:      intstr.FromInt32(3),
+			unavailableOrdinals: []int{0, 1},
+			makeUnavailable: func(spc *fakeObjectManager, set *apps.StatefulSet, ordinal int) error {
+				_, err := spc.setPodReadyCondition(set, ordinal, false)
+				return err
+			},
+			expectedRemainingOrdinals: []int{2, 3},
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			set := newStatefulSet(tc.replicas)
+			set.Spec.PodManagementPolicy = tc.podManagementPolicy
+			set.Spec.UpdateStrategy = apps.StatefulSetUpdateStrategy{
+				Type: apps.RollingUpdateStatefulSetStrategyType,
+				RollingUpdate: &apps.RollingUpdateStatefulSetStrategy{
+					Partition:      &tc.partition,
+					MaxUnavailable: &tc.maxUnavailable,
+				},
+			}
+			client := fake.NewSimpleClientset()
+			spc, _, ssc := setupController(client)
+			if err := scaleUpStatefulSetControl(set, ssc, spc, assertBurstInvariants); err != nil {
+				t.Fatal(err)
+			}
+			set, err := spc.setsLister.StatefulSets(set.Namespace).Get(set.Name)
+			if err != nil {
+				t.Fatal(err)
+			}
+
+			// IsPodAvailable checks lastTransitionTime, so for those cases where
+			// we rely on minReadySeconds we need to ensure that pod report it
+			// with appropriate higher value
+			if tc.minReadySeconds > 0 {
+				pastTime := fakeClock.Now().Add(-time.Duration(tc.minReadySeconds+60) * time.Second)
+				for ordinal := 0; ordinal < int(tc.replicas); ordinal++ {
+					if _, err := spc.setPodAvailable(set, ordinal, pastTime); err != nil {
+						t.Fatalf("setPodAvailable(%d) pre-minReadySeconds setup: %v", ordinal, err)
+					}
+				}
+			}
+
+			for _, ordinal := range tc.unavailableOrdinals {
+				if err := tc.makeUnavailable(spc, set, ordinal); err != nil {
+					t.Fatalf("makeUnavailable(%d): %v", ordinal, err)
+				}
+			}
+
+			selector, err := metav1.LabelSelectorAsSelector(set.Spec.Selector)
+			if err != nil {
+				t.Fatal(err)
+			}
+			pods, err := spc.podsLister.Pods(set.Namespace).List(selector)
+			if err != nil {
+				t.Fatal(err)
+			}
+			sort.Sort(ascendingOrdinal(pods))
+
+			status := apps.StatefulSetStatus{Replicas: tc.replicas}
+			updateRevision := &apps.ControllerRevision{}
+			// set minReadySeconds only for the invariant check
+			set.Spec.MinReadySeconds = tc.minReadySeconds
+			if _, err = updateStatefulSetAfterInvariantEstablished(
+				t.Context(),
+				ssc.(*defaultStatefulSetControl),
+				set,
+				pods,
+				updateRevision,
+				status,
+				fakeClock.Now(),
+			); err != nil {
+				t.Fatal(err)
+			}
+
+			podsAfter, err := spc.podsLister.Pods(set.Namespace).List(selector)
+			if err != nil {
+				t.Fatal(err)
+			}
+			if len(podsAfter) != len(tc.expectedRemainingOrdinals) {
+				t.Errorf("got %d pods remaining, want %d", len(podsAfter), len(tc.expectedRemainingOrdinals))
+			}
+			for _, p := range podsAfter {
+				ordinal := getOrdinal(p)
+				if p.DeletionTimestamp != nil && !slices.Contains(tc.unavailableOrdinals, ordinal) {
+					t.Errorf("pod %s, has DeletionTimestamp set unexpectedly", p.Name)
+				}
+			}
+			remainingOrdinals := make([]int, 0, len(podsAfter))
+			for _, p := range podsAfter {
+				remainingOrdinals = append(remainingOrdinals, getOrdinal(p))
+			}
+			sort.Ints(remainingOrdinals)
+			if !slices.Equal(remainingOrdinals, tc.expectedRemainingOrdinals) {
+				t.Errorf("got remaining pod ordinals %v, want %v", remainingOrdinals, tc.expectedRemainingOrdinals)
+			}
+		})
+	}
+}
+
 func TestStatefulSetControlRollingUpdate(t *testing.T) {
 	type testcase struct {
 		name       string
@@ -2708,15 +3129,22 @@ func (om *fakeObjectManager) addTerminatingPod(set *apps.StatefulSet, ordinal in
 }
 
 func (om *fakeObjectManager) setPodTerminated(set *apps.StatefulSet, ordinal int) ([]*v1.Pod, error) {
-	pod := newStatefulSetPod(set, ordinal)
-	deleted := metav1.NewTime(time.Now())
-	pod.DeletionTimestamp = &deleted
-	fakeResourceVersion(pod)
-	om.podsIndexer.Update(pod)
 	selector, err := metav1.LabelSelectorAsSelector(set.Spec.Selector)
 	if err != nil {
 		return nil, err
 	}
+	pods, err := om.podsLister.Pods(set.Namespace).List(selector)
+	if err != nil {
+		return nil, err
+	}
+	pod := findPodByOrdinal(pods, ordinal)
+	if pod == nil {
+		return nil, fmt.Errorf("setPodTerminated: pod ordinal %d not found", ordinal)
+	}
+	deleted := metav1.NewTime(time.Now())
+	pod.DeletionTimestamp = &deleted
+	fakeResourceVersion(pod)
+	om.podsIndexer.Update(pod) //nolint:errcheck
 	return om.podsLister.Pods(set.Namespace).List(selector)
 }
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestStatefulSetControlRollingUpdateWithMaxUnavailableAndUnavailableStalePod"]

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
