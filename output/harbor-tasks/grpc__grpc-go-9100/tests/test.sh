#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/internal/xds/resolver/cluster_specifier_plugin_test.go b/internal/xds/resolver/cluster_specifier_plugin_test.go
index bd878b3b1773..7df61cc765dd 100644
--- a/internal/xds/resolver/cluster_specifier_plugin_test.go
+++ b/internal/xds/resolver/cluster_specifier_plugin_test.go
@@ -31,14 +31,17 @@ import (
 	"google.golang.org/grpc/internal/testutils/xds/e2e"
 	"google.golang.org/grpc/internal/xds/balancer/clustermanager"
 	"google.golang.org/grpc/internal/xds/clusterspecifier"
+	"google.golang.org/grpc/internal/xds/httpfilter"
 	"google.golang.org/grpc/resolver"
 	"google.golang.org/grpc/serviceconfig"
 	"google.golang.org/protobuf/proto"
 	"google.golang.org/protobuf/types/known/anypb"
 	"google.golang.org/protobuf/types/known/wrapperspb"
 
+	v3corepb "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
 	v3listenerpb "github.com/envoyproxy/go-control-plane/envoy/config/listener/v3"
 	v3routepb "github.com/envoyproxy/go-control-plane/envoy/config/route/v3"
+	v3httppb "github.com/envoyproxy/go-control-plane/envoy/extensions/filters/network/http_connection_manager/v3"
 )
 
 func init() {
@@ -337,3 +340,136 @@ func (s) TestXDSResolverDelayedOnCommittedCSP(t *testing.T) {
  }`
 	verifyUpdateFromResolver(ctx, t, stateCh, wantSC)
 }
+
+// TestResolverClusterSpecifierPlugin_WithFilters tests the case where a route
+// configuration containing cluster specifier plugins is sent by the management
+// server, and HTTP filters are configured. The test verifies that the
+// interceptor chain is built for routes matching cluster specifier plugins.
+func (s) TestResolverClusterSpecifierPlugin_WithFilters(t *testing.T) {
+	// Register custom httpFilter builders for the test.
+	testFilterTypeURL1 := "test-filter-type-url-1" + uuid.New().String()
+	testFilterTypeURL2 := "test-filter-type-url-2" + uuid.New().String()
+	newStreamChan := testutils.NewChannelWithSize(2)
+	fb1 := &testHTTPFilterWithRPCMetadata{
+		logger:        t,
+		typeURL:       testFilterTypeURL1,
+		newStreamChan: newStreamChan,
+	}
+	fb2 := &testHTTPFilterWithRPCMetadata{
+		logger:        t,
+		typeURL:       testFilterTypeURL2,
+		newStreamChan: newStreamChan,
+	}
+	httpfilter.Register(fb1)
+	httpfilter.Register(fb2)
+	defer httpfilter.UnregisterForTesting(fb1.typeURL)
+	defer httpfilter.UnregisterForTesting(fb2.typeURL)
+
+	// Spin up an xDS management server.
+	ctx, cancel := context.WithTimeout(context.Background(), defaultTestTimeout)
+	defer cancel()
+	nodeID := uuid.New().String()
+	mgmtServer, _, _, bc := setupManagementServerForTest(t, nodeID)
+
+	// Configure resources on the management server.
+	// We need a listener with the filter, and a route with ClusterSpecifierPlugin.
+	listeners := []*v3listenerpb.Listener{{
+		Name: defaultTestServiceName,
+		ApiListener: &v3listenerpb.ApiListener{
+			ApiListener: testutils.MarshalAny(t, &v3httppb.HttpConnectionManager{
+				RouteSpecifier: &v3httppb.HttpConnectionManager_Rds{Rds: &v3httppb.Rds{
+					ConfigSource: &v3corepb.ConfigSource{
+						ConfigSourceSpecifier: &v3corepb.ConfigSource_Ads{Ads: &v3corepb.AggregatedConfigSource{}},
+					},
+					RouteConfigName: defaultTestRouteConfigName,
+				}},
+				HttpFilters: []*v3httppb.HttpFilter{
+					newHTTPFilter(t, "test-filter-1", testFilterTypeURL1, "filter-path-1", ""),
+					newHTTPFilter(t, "test-filter-2", testFilterTypeURL2, "filter-path-2", ""),
+					e2e.RouterHTTPFilter,
+				},
+			}),
+		},
+	}}
+
+	routes := []*v3routepb.RouteConfiguration{e2e.RouteConfigResourceWithOptions(e2e.RouteConfigOptions{
+		RouteConfigName:              defaultTestRouteConfigName,
+		ListenerName:                 defaultTestServiceName,
+		ClusterSpecifierType:         e2e.RouteConfigClusterSpecifierTypeClusterSpecifierPlugin,
+		ClusterSpecifierPluginName:   "cspA",
+		ClusterSpecifierPluginConfig: testutils.MarshalAny(t, &wrapperspb.StringValue{Value: "anything"}),
+	})}
+	// Override the configuration for "test-filter-1" in the route.
+	routes[0].VirtualHosts[0].Routes[0].TypedPerFilterConfig = map[string]*anypb.Any{
+		"test-filter-1": newHTTPFilter(t, "test-filter-1", testFilterTypeURL1, "override-path-1", "").GetTypedConfig(),
+	}
+	configureResources(ctx, t, mgmtServer, nodeID, listeners, routes, nil, nil)
+
+	stateCh, _, _ := buildResolverForTarget(t, resolver.Target{URL: *testutils.MustParseURL("xds:///" + defaultTestServiceName)}, bc)
+
+	// Wait for an update from the resolver, and verify the service config.
+	wantSC := `
+ {
+	"loadBalancingConfig": [
+		{
+			"xds_cluster_manager_experimental": {
+			"children": {
+				"cluster_specifier_plugin:cspA": {
+				"childPolicy": [
+					{
+					"csp_experimental": {
+						"arbitrary_field": "anything"
+					}
+					}
+				]
+				}
+			}
+			}
+		}
+	]
+ }`
+	cs := verifyUpdateFromResolver(ctx, t, stateCh, wantSC)
+	res, err := cs.SelectConfig(iresolver.RPCInfo{Context: ctx, Method: "/service/method"})
+	if err != nil {
+		t.Fatalf("cs.SelectConfig(): %v", err)
+	}
+
+	// Verify that the interceptor is not nil.
+	if res.Interceptor == nil {
+		t.Fatal("RPCInfo does not contain interceptors list")
+	}
+
+	newStream := func(context.Context, func()) (iresolver.ClientStream, error) {
+		return nil, nil
+	}
+
+	if _, err = res.Interceptor.NewStream(ctx, iresolver.RPCInfo{Method: "/service/method", Context: ctx}, func() {}, newStream); err != nil {
+		t.Fatalf("NewStream() failed with error: %v", err)
+	}
+
+	// Verify that first filter receives the config.
+	cfg, err := newStreamChan.Receive(ctx)
+	if err != nil {
+		t.Fatalf("Timeout waiting for first filter to receive config: %v", err)
+	}
+	ofc := cfg.(overallFilterConfig)
+	if ofc.BasePath != "filter-path-1" {
+		t.Fatalf("Unexpected base path for first filter, got: %q, want: %q", ofc.BasePath, "filter-path-1")
+	}
+	if ofc.OverridePath != "override-path-1" {
+		t.Fatalf("Unexpected override path for first filter, got: %q, want: %q", ofc.OverridePath, "override-path-1")
+	}
+
+	// Verify that second filter receives the base path.
+	cfg, err = newStreamChan.Receive(ctx)
+	if err != nil {
+		t.Fatalf("Timeout waiting for second filter to receive config: %v", err)
+	}
+	ofc = cfg.(overallFilterConfig)
+	if ofc.BasePath != "filter-path-2" {
+		t.Fatalf("Unexpected base path for second filter, got: %q, want: %q", ofc.BasePath, "filter-path-2")
+	}
+	if ofc.OverridePath != "" {
+		t.Fatalf("Unexpected override path for second filter, got: %q, want: %q", ofc.OverridePath, "")
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./internal/xds/resolver/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["Test"]

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
