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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestNodeRefFromNode", "TestReconcile"]

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
