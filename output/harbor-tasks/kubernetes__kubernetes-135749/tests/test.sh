#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/server/server_test.go b/pkg/kubelet/server/server_test.go
index 4f96be6b32c01..b77b07b190ba0 100644
--- a/pkg/kubelet/server/server_test.go
+++ b/pkg/kubelet/server/server_test.go
@@ -62,6 +62,7 @@ import (
 	"k8s.io/apiserver/pkg/server/healthz"
 	utilfeature "k8s.io/apiserver/pkg/util/feature"
 	featuregatetesting "k8s.io/component-base/featuregate/testing"
+	"k8s.io/component-base/metrics/testutil"
 	zpagesfeatures "k8s.io/component-base/zpages/features"
 	"k8s.io/kubelet/pkg/cri/streaming"
 	"k8s.io/kubelet/pkg/cri/streaming/portforward"
@@ -70,6 +71,7 @@ import (
 	"k8s.io/kubernetes/pkg/features"
 	kubeletconfiginternal "k8s.io/kubernetes/pkg/kubelet/apis/config"
 	"k8s.io/kubernetes/pkg/kubelet/cm"
+	servermetrics "k8s.io/kubernetes/pkg/kubelet/server/metrics"
 	"k8s.io/kubernetes/pkg/kubelet/server/stats"
 	"k8s.io/kubernetes/pkg/volume"
 )
@@ -2021,3 +2023,47 @@ func TestNewServerRegistersMetricsSLIsEndpointTwice(t *testing.T) {
 	assert.Contains(t, server1.restfulCont.RegisteredHandlePaths(), "/metrics/slis", "First server should register /metrics/slis")
 	assert.Contains(t, server2.restfulCont.RegisteredHandlePaths(), "/metrics/slis", "Second server should register /metrics/slis")
 }
+
+// This test verifies that the HTTP request duration metric captures the actual
+// request handling time.
+func TestServeHTTPRequestDurationMetric(t *testing.T) {
+	tCtx := ktesting.Init(t)
+	fw := newServerTest(tCtx)
+	defer fw.testHTTPServer.Close()
+
+	// Register and reset the metric before the test
+	servermetrics.Register()
+	servermetrics.HTTPRequestsDuration.Reset()
+
+	// Add a delay to the pods handler to simulate request processing time.
+	// We use 50ms which is long enough to be clearly distinguishable from
+	// the ~2 microsecond bug, but short enough to not slow down tests.
+	handlerDelay := 50 * time.Millisecond
+	fw.fakeKubelet.podsFunc = func() []*v1.Pod {
+		time.Sleep(handlerDelay)
+		return []*v1.Pod{}
+	}
+
+	// Make a request to the pods endpoint
+	resp, err := http.Get(fw.testHTTPServer.URL + "/pods/")
+	require.NoError(t, err)
+	defer resp.Body.Close() //nolint:errcheck
+	require.Equal(t, http.StatusOK, resp.StatusCode)
+
+	// Read the body to ensure the request is fully processed
+	_, err = io.ReadAll(resp.Body)
+	require.NoError(t, err)
+
+	// Get the recorded duration from the metric
+	observerMetric := servermetrics.HTTPRequestsDuration.WithLabelValues("GET", "pods", "readwrite", "false")
+	metricValue, err := testutil.GetHistogramMetricValue(observerMetric)
+	require.NoError(t, err)
+
+	// Use the handler delay as the minimum expected duration. This avoids any
+	// timing-sensitive percentage-based checks.
+	minExpectedDuration := handlerDelay.Seconds()
+	assert.GreaterOrEqual(t, metricValue, minExpectedDuration,
+		"HTTP request duration metric recorded %v seconds, expected at least %v seconds. ",
+		metricValue, minExpectedDuration,
+	)
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/server/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestServeHTTPRequestDurationMetric"]
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
