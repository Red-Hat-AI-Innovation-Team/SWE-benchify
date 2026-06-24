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
go test -json -count=1 ./pkg/controller/statefulset/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestStatefulSetControlRollingUpdateWithMaxUnavailableAndUnavailableStalePod"]
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
