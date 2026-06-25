#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/endpointslice/reconciler_test.go b/staging/src/k8s.io/endpointslice/reconciler_test.go
index 22f3cde24f98a..ea4291c65a7c1 100644
--- a/staging/src/k8s.io/endpointslice/reconciler_test.go
+++ b/staging/src/k8s.io/endpointslice/reconciler_test.go
@@ -2209,6 +2209,49 @@ func TestReconcile_TrafficDistribution(t *testing.T) {
 	}
 }
 
+// TestReconcileHeadlessServiceNoPorts verifies that headless services with no ports
+// don'"'"'t cause EndpointSlice churn. Validates fix for https://github.com/kubernetes/kubernetes/issues/133474
+func TestReconcileHeadlessServiceNoPorts(t *testing.T) {
+	namespace := "test"
+	client := newClientset()
+	setupMetrics()
+
+	svc := corev1.Service{
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      "headless-no-ports",
+			Namespace: namespace,
+			UID:       "test-uid",
+		},
+		Spec: corev1.ServiceSpec{
+			ClusterIP:  corev1.ClusterIPNone,
+			Selector:   map[string]string{"foo": "bar"},
+			IPFamilies: []corev1.IPFamily{corev1.IPv4Protocol},
+		},
+	}
+
+	pod := newPod(1, namespace, true, 1, false)
+
+	r := newReconciler(client, []*corev1.Node{{ObjectMeta: metav1.ObjectMeta{Name: pod.Spec.NodeName}}}, defaultMaxEndpointsPerSlice)
+
+	reconcileHelper(t, r, &svc, []*corev1.Pod{pod}, []*discovery.EndpointSlice{}, time.Now())
+	assert.Len(t, client.Actions(), 1, "Expected 1 additional clientset action")
+	expectActions(t, client.Actions(), 1, "create", "endpointslices")
+
+	var existingSlices []*discovery.EndpointSlice
+	for _, slice := range fetchEndpointSlices(t, client, namespace) {
+		copy := slice.DeepCopy()
+		// replicate API server behavior which serializes this empty slice as nil
+		copy.Ports = nil
+		existingSlices = append(existingSlices, copy)
+	}
+	assert.Len(t, existingSlices, 1, "Expected 1 endpoint slices")
+
+	reconcileHelper(t, r, &svc, []*corev1.Pod{pod}, existingSlices, time.Now())
+
+	assert.Len(t, client.Actions(), 2, "Expected second reconcile to only list")
+	expectActions(t, client.Actions(), 1, "list", "endpointslices")
+}
+
 // Test Helpers
 
 func newReconciler(client *fake.Clientset, nodes []*corev1.Node, maxEndpointsPerSlice int32) *Reconciler {
diff --git a/staging/src/k8s.io/endpointslice/util/controller_utils_test.go b/staging/src/k8s.io/endpointslice/util/controller_utils_test.go
index c7705b66b618a..cf9f0122e5aec 100644
--- a/staging/src/k8s.io/endpointslice/util/controller_utils_test.go
+++ b/staging/src/k8s.io/endpointslice/util/controller_utils_test.go
@@ -948,3 +948,15 @@ func TestDeepObjectPointer(t *testing.T) {
 		}
 	}
 }
+
+func TestNewPortMapKey_NilVsEmptySlice(t *testing.T) {
+	var nilPorts []discovery.EndpointPort
+	emptyPorts := []discovery.EndpointPort{}
+
+	nilKey := NewPortMapKey(nilPorts)
+	emptyKey := NewPortMapKey(emptyPorts)
+
+	if nilKey != emptyKey {
+		t.Errorf("NewPortMapKey should return the same key for nil and empty slice, got nil=%q empty=%q", nilKey, emptyKey)
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestNewPortMapKey_NilVsEmptySlice", "TestReconcileHeadlessServiceNoPorts"]

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
