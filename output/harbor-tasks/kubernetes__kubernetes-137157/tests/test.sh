#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller_test.go b/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller_test.go
index 20e62975dacaf..d0faad7a7099c 100644
--- a/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller_test.go
+++ b/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller_test.go
@@ -18,6 +18,7 @@ package remote
 
 import (
 	"fmt"
+	"net"
 	"net/http"
 	"net/http/httptest"
 	"net/url"
@@ -537,3 +538,75 @@ func TestUpdateAPIServiceStatus(t *testing.T) {
 func emptyCert() []byte {
 	return []byte{}
 }
+
+func TestCloseIdleConnections(t *testing.T) {
+	apiServiceName := "remote.group"
+	apiServices := []runtime.Object{newRemoteAPIService(apiServiceName)}
+	services := []*v1.Service{newService("foo", "bar", testServicePort, testServicePortName)}
+	endpointSlices := []*discoveryv1.EndpointSlice{newEndpointSliceWithAddress("foo", "bar", testServicePort, testServicePortName)}
+
+	fakeClient := fake.NewSimpleClientset(apiServices...)
+	apiServiceIndexer := cache.NewIndexer(cache.MetaNamespaceKeyFunc, cache.Indexers{cache.NamespaceIndex: cache.MetaNamespaceIndexFunc})
+	serviceIndexer := cache.NewIndexer(cache.MetaNamespaceKeyFunc, cache.Indexers{cache.NamespaceIndex: cache.MetaNamespaceIndexFunc})
+	endpointSliceIndexer := cache.NewIndexer(cache.MetaNamespaceKeyFunc, cache.Indexers{cache.NamespaceIndex: cache.MetaNamespaceIndexFunc})
+	for _, obj := range apiServices {
+		if err := apiServiceIndexer.Add(obj); err != nil {
+			t.Fatalf("failed to add APIService: %v", err)
+		}
+	}
+	for _, obj := range services {
+		if err := serviceIndexer.Add(obj); err != nil {
+			t.Fatalf("failed to add service: %v", err)
+		}
+	}
+	for _, obj := range endpointSlices {
+		if err := endpointSliceIndexer.Add(obj); err != nil {
+			t.Fatalf("failed to add endpointSlice: %v", err)
+		}
+	}
+
+	endpointSliceGetter, err := proxy.NewEndpointSliceListerGetter(discoveryv1listers.NewEndpointSliceLister(endpointSliceIndexer))
+	if err != nil {
+		t.Fatalf("error creating endpointSliceGetter: %v", err)
+	}
+
+	closed := make(chan struct{}, 1)
+	testServer := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
+		w.WriteHeader(http.StatusBadGateway)
+	}))
+	// We want to verify that the client closes the connection.
+	// httptest.Server doesn'"'"'t expose ConnState, but the underlying http.Server does.
+	testServer.Config.ConnState = func(c net.Conn, state http.ConnState) {
+		if state == http.StateClosed {
+			select {
+			case closed <- struct{}{}:
+			default:
+			}
+		}
+	}
+	testServer.Start()
+	defer testServer.Close()
+
+	c := AvailableConditionController{
+		apiServiceClient:           fakeClient.ApiregistrationV1(),
+		apiServiceLister:           listers.NewAPIServiceLister(apiServiceIndexer),
+		serviceLister:              v1listers.NewServiceLister(serviceIndexer),
+		endpointSliceGetter:        endpointSliceGetter,
+		serviceResolver:            &fakeServiceResolver{url: testServer.URL},
+		proxyCurrentCertKeyContent: func() ([]byte, []byte) { return emptyCert(), emptyCert() },
+		metrics:                    availabilitymetrics.New(),
+	}
+
+	// This should trigger the bad gateway response and (with the fix) close the connection.
+	err = c.sync(apiServiceName)
+	if err == nil {
+		t.Fatal("expected error from sync")
+	}
+
+	select {
+	case <-closed:
+		// success, connection was closed
+	case <-time.After(30 * time.Second):
+		t.Fatal("timeout waiting for connection to be closed")
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestCloseIdleConnections"]
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
