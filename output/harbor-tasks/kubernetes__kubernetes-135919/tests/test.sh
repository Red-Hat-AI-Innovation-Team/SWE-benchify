#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/cm/dra/manager_test.go b/pkg/kubelet/cm/dra/manager_test.go
index ab10ca414175f..58fe6ab5337c7 100644
--- a/pkg/kubelet/cm/dra/manager_test.go
+++ b/pkg/kubelet/cm/dra/manager_test.go
@@ -65,8 +65,9 @@ const (
 )
 
 var (
-	shareID  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
-	shareUID = types.UID(shareID)
+	shareID        = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
+	shareUID       = types.UID(shareID)
+	testPodCounter atomic.Uint32
 )
 
 type fakeDRADriverGRPCServer struct {
@@ -300,6 +301,23 @@ func setupFakeDRADriverGRPCServer(ctx context.Context, shouldTimeout bool, plugi
 	}, nil
 }
 
+func genPrepareResourcesResponse(claimUID types.UID) *drapb.NodePrepareResourcesResponse {
+	return &drapb.NodePrepareResourcesResponse{
+		Claims: map[string]*drapb.NodePrepareResourceResponse{
+			string(claimUID): {
+				Devices: []*drapb.Device{
+					{
+						PoolName:     poolName,
+						DeviceName:   deviceName,
+						RequestNames: []string{requestName},
+						CdiDeviceIds: []string{cdiID},
+					},
+				},
+			},
+		},
+	}
+}
+
 func TestNewManagerImpl(t *testing.T) {
 	kubeClient := fake.NewSimpleClientset()
 	for _, test := range []struct {
@@ -363,6 +381,45 @@ func genTestPod() *v1.Pod {
 	}
 }
 
+func genTestPodWithClaims(claimNames ...string) *v1.Pod {
+	podCounter := testPodCounter.Add(1)
+
+	podName := fmt.Sprintf("test-pod-%d", podCounter)
+	podUID := types.UID(fmt.Sprintf("test-pod-uid-%d", podCounter))
+
+	resourceClaims := make([]v1.PodResourceClaim, 0, len(claimNames))
+	containerClaims := make([]v1.ResourceClaim, 0, len(claimNames))
+
+	for _, claimName := range claimNames {
+		cn := claimName
+		resourceClaims = append(resourceClaims, v1.PodResourceClaim{
+			Name:              cn,
+			ResourceClaimName: &cn,
+		})
+		containerClaims = append(containerClaims, v1.ResourceClaim{
+			Name: cn,
+		})
+	}
+
+	return &v1.Pod{
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      podName,
+			Namespace: namespace,
+			UID:       podUID,
+		},
+		Spec: v1.PodSpec{
+			ResourceClaims: resourceClaims,
+			Containers: []v1.Container{
+				{
+					Resources: v1.ResourceRequirements{
+						Claims: containerClaims,
+					},
+				},
+			},
+		},
+	}
+}
+
 // genTestPodWithExtendedResource generates pod object
 func genTestPodWithExtendedResource() *v1.Pod {
 	return &v1.Pod{
@@ -787,18 +844,7 @@ dra_operations_duration_seconds_sum{is_error="false",operation_name="PrepareReso
 dra_operations_duration_seconds_count{is_error="false",operation_name="PrepareResources"} 1
 `,
 			expectedClaimInfoState: genClaimInfoState(cdiID),
-			resp: &drapb.NodePrepareResourcesResponse{Claims: map[string]*drapb.NodePrepareResourceResponse{
-				string(claimUID): {
-					Devices: []*drapb.Device{
-						{
-							PoolName:     poolName,
-							DeviceName:   deviceName,
-							RequestNames: []string{requestName},
-							CdiDeviceIds: []string{cdiID},
-						},
-					},
-				},
-			}},
+			resp:                   genPrepareResourcesResponse(claimUID),
 		},
 		{
 			description:            "resource already prepared",
@@ -807,18 +853,7 @@ dra_operations_duration_seconds_count{is_error="false",operation_name="PrepareRe
 			claim:                  genTestClaim(claimName, driverName, deviceName, podUID),
 			claimInfo:              genTestClaimInfo(claimUID, []string{podUID}, true),
 			expectedClaimInfoState: genClaimInfoState(cdiID),
-			resp: &drapb.NodePrepareResourcesResponse{Claims: map[string]*drapb.NodePrepareResourceResponse{
-				string(claimUID): {
-					Devices: []*drapb.Device{
-						{
-							PoolName:     poolName,
-							DeviceName:   deviceName,
-							RequestNames: []string{requestName},
-							CdiDeviceIds: []string{cdiID},
-						},
-					},
-				},
-			}},
+			resp:                   genPrepareResourcesResponse(claimUID),
 			expectedMetric: `# HELP dra_operations_duration_seconds [ALPHA] Latency histogram in seconds for the duration of handling all ResourceClaims referenced by a pod when the pod starts or stops. Identified by the name of the operation (PrepareResources or UnprepareResources) and separated by the success of the operation. The number of failed operations is provided through the histogram'"'"'s overall count.
 # TYPE dra_operations_duration_seconds histogram
 dra_operations_duration_seconds_bucket{is_error="false",operation_name="PrepareResources",le="+Inf"} 1
@@ -852,19 +887,8 @@ dra_operations_duration_seconds_count{is_error="true",operation_name="PrepareRes
 			pod:                    genTestPod(),
 			claim:                  genTestClaim(claimName, driverName, deviceName, podUID),
 			expectedClaimInfoState: genClaimInfoState(cdiID),
-			resp: &drapb.NodePrepareResourcesResponse{Claims: map[string]*drapb.NodePrepareResourceResponse{
-				string(claimUID): {
-					Devices: []*drapb.Device{
-						{
-							PoolName:     poolName,
-							DeviceName:   deviceName,
-							RequestNames: []string{requestName},
-							CdiDeviceIds: []string{cdiID},
-						},
-					},
-				},
-			}},
-			expectedPrepareCalls: 1,
+			resp:                   genPrepareResourcesResponse(claimUID),
+			expectedPrepareCalls:   1,
 			expectedMetric: `# HELP dra_grpc_operations_duration_seconds [ALPHA] Duration in seconds of the DRA gRPC operations
 # TYPE dra_grpc_operations_duration_seconds histogram
 dra_grpc_operations_duration_seconds_bucket{driver_name="test-driver",grpc_status_code="OK",method_name="/k8s.io.kubelet.pkg.apis.dra.v1.DRAPlugin/NodePrepareResources",le="+Inf"} 1
@@ -1053,6 +1077,74 @@ dra_operations_duration_seconds_count{is_error="false",operation_name="PrepareRe
 	}
 }
 
+// TestPrepareResourcesWithPreparedAndNewClaim verifies that PrepareResources
+// correctly handles a pod that references a mix of ResourceClaims:
+// - first claim already prepared by a previous pod
+// - second claim is new and needs to be prepared
+func TestPrepareResourcesWithPreparedAndNewClaim(t *testing.T) {
+	logger, tCtx := ktesting.NewTestContext(t)
+	fakeKubeClient := fake.NewClientset()
+
+	manager, err := NewManager(logger, fakeKubeClient, t.TempDir())
+	require.NoError(t, err)
+	manager.initDRAPluginManager(tCtx, getFakeNode, time.Second)
+
+	secondClaimName := fmt.Sprintf("%s-second", claimName)
+
+	// Generate two pods where the second pod reuses an existing claim and adds a new one
+	firstPod := genTestPodWithClaims(claimName)
+	secondPod := genTestPodWithClaims(claimName, secondClaimName)
+
+	firstClaim := genTestClaim(claimName, driverName, deviceName, string(firstPod.ObjectMeta.UID))
+	secondClaim := genTestClaim(secondClaimName, driverName, deviceName, string(secondPod.ObjectMeta.UID))
+
+	// Make firstClaim reserved for first and second pod
+	firstClaim.Status.ReservedFor = append(
+		firstClaim.Status.ReservedFor,
+		resourceapi.ResourceClaimConsumerReference{UID: secondPod.ObjectMeta.UID},
+	)
+
+	_, err = fakeKubeClient.ResourceV1().ResourceClaims(namespace).Create(tCtx, firstClaim, metav1.CreateOptions{})
+	require.NoError(t, err)
+
+	_, err = fakeKubeClient.ResourceV1().ResourceClaims(namespace).Create(tCtx, secondClaim, metav1.CreateOptions{})
+	require.NoError(t, err)
+
+	respFirst := genPrepareResourcesResponse(firstClaim.UID)
+	draServerInfo, err := setupFakeDRADriverGRPCServer(tCtx, false, nil, respFirst, nil, nil)
+	require.NoError(t, err)
+	defer draServerInfo.teardownFn()
+
+	plg := manager.GetWatcherHandler()
+	require.NoError(t, plg.RegisterPlugin(driverName, draServerInfo.socketName, []string{drapb.DRAPluginService}, nil))
+
+	err = manager.PrepareResources(tCtx, firstPod)
+	require.NoError(t, err)
+
+	assert.Equal(t, uint32(1),
+		draServerInfo.server.prepareResourceCalls.Load(),
+		"first pod should trigger one prepare call",
+	)
+
+	respSecond := genPrepareResourcesResponse(secondClaim.UID)
+	draServerInfo.server.prepareResourcesResponse = respSecond
+
+	err = manager.PrepareResources(tCtx, secondPod)
+	require.NoError(t, err)
+
+	// second pod triggered exactly one prepare call (new claim only) + previous one call
+	assert.Equal(t, uint32(2),
+		draServerInfo.server.prepareResourceCalls.Load(),
+		"second pod should trigger one prepare call for the new claim",
+	)
+
+	for _, claimName := range []string{firstClaim.Name, secondClaim.Name} {
+		claimInfo, exists := manager.cache.get(claimName, namespace)
+		require.True(t, exists, "claim %s should exist in cache", claimName)
+		assert.True(t, claimInfo.prepared, "claim %s should be marked as prepared", claimName)
+	}
+}
+
 func TestUnprepareResources(t *testing.T) {
 	fakeKubeClient := fake.NewSimpleClientset()
 	for _, test := range []struct {
diff --git a/test/e2e/dra/dra.go b/test/e2e/dra/dra.go
index fb95a790fecb8..03ef637e1df7c 100644
--- a/test/e2e/dra/dra.go
+++ b/test/e2e/dra/dra.go
@@ -1098,6 +1098,54 @@ var _ = framework.SIGDescribe("node")(framework.WithLabel("DRA"), func() {
 		}
 	}
 
+	singleNodeMultipleClaimsTests := func() {
+		nodes := drautils.NewNodes(f, 1, 1)
+		// Allow allocating more than one device so that multiple claims can be prepared on the same node.
+		maxAllocations := 2
+		driver := drautils.NewDriver(f, nodes, drautils.DriverResources(maxAllocations)) // All tests get their own driver instance.
+		driver.WithKubelet = true
+		b := drautils.NewBuilder(f, driver)
+
+		// https://github.com/kubernetes/kubernetes/issues/135901 was fixed in master for Kubernetes 1.35 and not backported
+		// so this test only passes for kubelet >= 1.35.
+		f.It("requests an already allocated and a new claim for a pod", f.WithLabel("KubeletMinVersion:1.35"), func(ctx context.Context) {
+			// This test covers a situation when a pod references a mix of already-prepared and new claims.
+			tCtx := f.TContext(ctx)
+
+			firstClaim := b.ExternalClaim()
+			secondClaim := b.ExternalClaim()
+
+			b.Create(tCtx, firstClaim, secondClaim)
+
+			// First pod uses only firstClaim
+			firstPod := b.PodExternal()
+			b.Create(tCtx, firstPod)
+			b.TestPod(tCtx, firstPod)
+
+			// Second pod uses firstClaim (already prepared) + secondClaim (new)
+			secondPod := b.PodExternal()
+
+			secondPod.Spec.ResourceClaims = []v1.PodResourceClaim{
+				{
+					Name:              "first",
+					ResourceClaimName: &firstClaim.Name,
+				},
+				{
+					Name:              "second",
+					ResourceClaimName: &secondClaim.Name,
+				},
+			}
+
+			secondPod.Spec.Containers[0].Resources.Claims = []v1.ResourceClaim{
+				{Name: "first"},
+				{Name: "second"},
+			}
+
+			b.Create(tCtx, secondPod)
+			b.TestPod(tCtx, secondPod)
+		})
+	}
+
 	// The following tests only make sense when there is more than one node.
 	// They get skipped when there'"'"'s only one node.
 	multiNodeTests := func(withKubelet bool) {
@@ -1975,6 +2023,7 @@ var _ = framework.SIGDescribe("node")(framework.WithLabel("DRA"), func() {
 
 	framework.Context("control plane", func() { singleNodeTests(false) })
 	framework.Context("kubelet", feature.DynamicResourceAllocation, "on single node", func() { singleNodeTests(true) })
+	framework.Context("kubelet", feature.DynamicResourceAllocation, "on single node with multiple claims allocation", singleNodeMultipleClaimsTests)
 
 	framework.Context("control plane", func() { multiNodeTests(false) })
 	framework.Context("kubelet", feature.DynamicResourceAllocation, "on multiple nodes", func() { multiNodeTests(true) })
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestPrepareResourcesWithPreparedAndNewClaim"]

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
