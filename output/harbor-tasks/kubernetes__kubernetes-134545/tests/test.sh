#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/cm/node_container_manager_linux_test.go b/pkg/kubelet/cm/node_container_manager_linux_test.go
index a74e1c7cb231e..bd3b9d616a920 100644
--- a/pkg/kubelet/cm/node_container_manager_linux_test.go
+++ b/pkg/kubelet/cm/node_container_manager_linux_test.go
@@ -402,6 +402,54 @@ func getEphemeralStorageResourceList(storage string) v1.ResourceList {
 	return res
 }
 
+func TestNodeRefFromNode(t *testing.T) {
+	testCases := []struct {
+		name     string
+		nodeName string
+		expected *v1.ObjectReference
+	}{
+		{
+			name:     "normal node name",
+			nodeName: "test-node",
+			expected: &v1.ObjectReference{
+				APIVersion: "v1",
+				Kind:       "Node",
+				Name:       "test-node",
+				Namespace:  "",
+			},
+		},
+		{
+			name:     "empty node name",
+			nodeName: "",
+			expected: &v1.ObjectReference{
+				APIVersion: "v1",
+				Kind:       "Node",
+				Name:       "",
+				UID:        "",
+				Namespace:  "",
+			},
+		},
+		{
+			name:     "node name with special characters",
+			nodeName: "test-node-123.domain.local",
+			expected: &v1.ObjectReference{
+				APIVersion: "v1",
+				Kind:       "Node",
+				Name:       "test-node-123.domain.local",
+				Namespace:  "",
+			},
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			result := nodeRefFromNode(tc.nodeName)
+
+			assert.Equal(t, tc.expected, result, "test case %q failed", tc.name)
+		})
+	}
+}
+
 func TestGetCgroupConfig(t *testing.T) {
 	cases := []struct {
 		name                  string
diff --git a/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller_test.go b/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller_test.go
index 3356b6c2f685b..7442f13433e1d 100644
--- a/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller_test.go
+++ b/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller_test.go
@@ -909,8 +909,14 @@ func Test_NodesShutdown(t *testing.T) {
 				nodeMonitorPeriod: 1 * time.Second,
 			}
 
-			w := eventBroadcaster.StartStructuredLogging(0)
-			defer w.Stop()
+			e := eventBroadcaster.StartEventWatcher(func(e *v1.Event) {
+				loggerV := klog.FromContext(t.Context()).V(0)
+				loggerV.Info("Event occurred", "object", klog.KRef(e.InvolvedObject.Namespace, e.InvolvedObject.Name), "fieldPath", e.InvolvedObject.FieldPath, "kind", e.InvolvedObject.Kind, "apiVersion", e.InvolvedObject.APIVersion, "type", e.Type, "reason", e.Reason, "message", e.Message)
+				if e.InvolvedObject.APIVersion == "" {
+					t.Fatalf("event involvedObject.apiVersion is empty")
+				}
+			})
+			defer e.Stop()
 			cloudNodeLifecycleController.MonitorNodes(ctx)
 
 			updatedNode, err := clientset.CoreV1().Nodes().Get(ctx, testcase.existingNode.Name, metav1.GetOptions{})
diff --git a/staging/src/k8s.io/cloud-provider/controllers/route/route_controller_test.go b/staging/src/k8s.io/cloud-provider/controllers/route/route_controller_test.go
index 265fb048ce1b2..b103c4b4d5526 100644
--- a/staging/src/k8s.io/cloud-provider/controllers/route/route_controller_test.go
+++ b/staging/src/k8s.io/cloud-provider/controllers/route/route_controller_test.go
@@ -27,7 +27,9 @@ import (
 	"k8s.io/apimachinery/pkg/types"
 	"k8s.io/client-go/informers"
 	"k8s.io/client-go/kubernetes/fake"
+	"k8s.io/client-go/kubernetes/scheme"
 	core "k8s.io/client-go/testing"
+	"k8s.io/client-go/tools/record"
 	cloudprovider "k8s.io/cloud-provider"
 	fakecloud "k8s.io/cloud-provider/fake"
 	nodeutil "k8s.io/component-helpers/node/util"
@@ -93,6 +95,7 @@ func TestReconcile(t *testing.T) {
 
 	node3 := v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-3", UID: "03"}, Spec: v1.NodeSpec{PodCIDR: "10.120.0.0/24", PodCIDRs: []string{"10.120.0.0/24", "a00:100::/24"}}, Status: v1.NodeStatus{Addresses: []v1.NodeAddress{{Type: v1.NodeInternalIP, Address: "10.0.3.1"}}}}
 	node4 := v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-4", UID: "04"}, Spec: v1.NodeSpec{PodCIDR: "10.120.1.0/24", PodCIDRs: []string{"10.120.1.0/24", "a00:200::/24"}}, Status: v1.NodeStatus{Addresses: []v1.NodeAddress{{Type: v1.NodeInternalIP, Address: "10.0.4.1"}}}}
+	nodeDuplicateCIDR := v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-4", UID: "04"}, Spec: v1.NodeSpec{PodCIDR: "10.120.1.0/24", PodCIDRs: []string{"10.120.1.0/24", "10.120.1.0/24"}}, Status: v1.NodeStatus{Addresses: []v1.NodeAddress{{Type: v1.NodeInternalIP, Address: "10.0.4.1"}}}}
 
 	testCases := []struct {
 		description                string
@@ -102,6 +105,7 @@ func TestReconcile(t *testing.T) {
 		expectedNetworkUnavailable []bool
 		clientset                  *fake.Clientset
 		dualStack                  bool
+		expectError                bool
 	}{
 		{
 			description: "routes have no TargetNodeAddresses at the beginning",
@@ -414,6 +418,17 @@ func TestReconcile(t *testing.T) {
 			expectedNetworkUnavailable: []bool{true, true},
 			clientset:                  fake.NewSimpleClientset(&v1.NodeList{Items: []v1.Node{node1, node2}}),
 		},
+		{
+			description: "duplicate pod cidr",
+			nodes: []*v1.Node{
+				&nodeDuplicateCIDR,
+			},
+			initialRoutes:              []*cloudprovider.Route{},
+			expectedRoutes:             []*cloudprovider.Route{},
+			expectedNetworkUnavailable: []bool{true, false},
+			expectError:                true,
+			clientset:                  fake.NewClientset(&v1.NodeList{Items: []v1.Node{nodeDuplicateCIDR}}),
+		},
 	}
 	for _, testCase := range testCases {
 		t.Run(testCase.description, func(t *testing.T) {
@@ -439,6 +454,16 @@ func TestReconcile(t *testing.T) {
 
 			informerFactory := informers.NewSharedInformerFactory(testCase.clientset, 0)
 			rc := New(routes, testCase.clientset, informerFactory.Core().V1().Nodes(), cluster, cidrs)
+
+			recorder := record.NewBroadcaster(record.WithContext(ctx))
+			rc.recorder = recorder.NewRecorder(scheme.Scheme, v1.EventSource{Component: "route_controller"})
+			e := recorder.StartEventWatcher(func(e *v1.Event) {
+				if e.InvolvedObject.APIVersion == "" {
+					t.Fatalf("event involvedObject.apiVersion is empty")
+				}
+			})
+			defer e.Stop()
+
 			rc.nodeListerSynced = alwaysReady
 			require.NoError(t, rc.reconcile(ctx, testCase.nodes, testCase.initialRoutes), "failed to reconcile")
 			for _, action := range testCase.clientset.Actions() {
@@ -476,8 +501,10 @@ func TestReconcile(t *testing.T) {
 						break poll
 					}
 				case <-timeoutChan:
-					t.Errorf("rc.reconcile() err is %v,\nfound routes:\n%v\nexpected routes:\n%v\n",
-						err, flatten(finalRoutes), flatten(testCase.expectedRoutes))
+					if !testCase.expectError {
+						t.Errorf("rc.reconcile() err is %v,\nfound routes:\n%v\nexpected routes:\n%v\n",
+							err, flatten(finalRoutes), flatten(testCase.expectedRoutes))
+					}
 					break poll
 				}
 			}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/cm/... ./staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/... ./staging/src/k8s.io/cloud-provider/controllers/route/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestNodeRefFromNode", "TestReconcile"]
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
