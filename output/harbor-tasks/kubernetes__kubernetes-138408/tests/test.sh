#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/resourceclaim/controller_test.go b/pkg/controller/resourceclaim/controller_test.go
index 3badda6a751a0..7a11ec1c667c0 100644
--- a/pkg/controller/resourceclaim/controller_test.go
+++ b/pkg/controller/resourceclaim/controller_test.go
@@ -704,6 +704,36 @@ func TestSyncHandler(t *testing.T) {
 			}()},
 			expectedMetrics: expectedMetrics{0, 0, 0, 0},
 		},
+		{
+			name: "flapping-resourceclaim-statuses",
+			pods: func() []*v1.Pod {
+				pod := makePod(testPodName, testNamespace, testPodUID,
+					*makePodResourceClaim("claimA", templateName),
+					*makePodResourceClaim("claimB", templateName),
+				)
+				// Initially only claimA is in status
+				pod.Status.ResourceClaimStatuses = []v1.PodResourceClaimStatus{
+					{Name: "claimA", ResourceClaimName: ptr.To("claimA-object")},
+				}
+				return []*v1.Pod{pod}
+			}(),
+			templates: []*resourceapi.ResourceClaimTemplate{template},
+			claims: []*resourceapi.ResourceClaim{
+				makeClaim("claimA-object", testNamespace, className, makeOwnerReference(testPod, true)),
+			},
+			key: podKeyPrefix + testNamespace + "/" + testPodName,
+			expectedStatuses: map[string][]v1.PodResourceClaimStatus{
+				testPodName: {
+					{Name: "claimA", ResourceClaimName: ptr.To("claimA-object")},
+					{Name: "claimB", ResourceClaimName: ptr.To("test-pod-claimB--1")},
+				},
+			},
+			expectedClaims: []resourceapi.ResourceClaim{
+				*makeClaim("claimA-object", testNamespace, className, makeOwnerReference(testPod, true)),
+				*makeTemplatedClaim("claimB", testPodName+"-claimB-", testNamespace, className, 1, makeOwnerReference(testPod, true), nil),
+			},
+			expectedMetrics: expectedMetrics{1, 0, 0, 0},
+		},
 	}
 
 	for _, tc := range tests {
@@ -731,6 +761,14 @@ func TestSyncHandler(t *testing.T) {
 					return true, nil, apierrors.NewConflict(action.GetResource().GroupResource(), "fake name", errors.New("fake conflict"))
 				})
 			}
+			var appliedPatches []string
+			fakeKubeClient.PrependReactor("patch", "pods", func(action k8stesting.Action) (handled bool, ret runtime.Object, err error) {
+				patchAction := action.(k8stesting.PatchAction)
+				if patchAction.GetSubresource() == "status" {
+					appliedPatches = append(appliedPatches, string(patchAction.GetPatch()))
+				}
+				return false, nil, nil
+			})
 			informerFactory := informers.NewSharedInformerFactory(fakeKubeClient, controller.NoResyncPeriodFunc())
 			podInformer := informerFactory.Core().V1().Pods()
 			podGroupInformer := informerFactory.Scheduling().V1alpha2().PodGroups()
@@ -780,6 +818,12 @@ func TestSyncHandler(t *testing.T) {
 				t.Fatalf("expected error, got none")
 			}
 
+			if tc.name == "flapping-resourceclaim-statuses" {
+				assert.Len(t, appliedPatches, 1, "should have applied status once")
+				assert.Contains(t, appliedPatches[0], `"name":"claimA"`, "patch should contain claimA")
+				assert.Contains(t, appliedPatches[0], `"name":"claimB"`, "patch should contain claimB")
+			}
+
 			claims, err := fakeKubeClient.ResourceV1().ResourceClaims("").List(tCtx, metav1.ListOptions{})
 			if err != nil {
 				t.Fatalf("unexpected error while listing claims: %v", err)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/controller/resourceclaim/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestSyncHandler"]
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
