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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestCloseIdleConnections"]

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
