#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/stats/opentelemetry/e2e_test.go b/stats/opentelemetry/e2e_test.go
index 7c0ecf4df957..dda883f71bc9 100644
--- a/stats/opentelemetry/e2e_test.go
+++ b/stats/opentelemetry/e2e_test.go
@@ -2204,3 +2204,146 @@ func runDisconnectScenario(t *testing.T, name, wantLabel string, action func(*st
 		t.Fatalf("Metric verification failed for case %s: %v", name, err)
 	}
 }
+
+// TestRelayContextCollisionMetrics verifies that when an application acts as
+// both a server and a client using the same context, the client metrics do not
+// inherit or overwrite the server'"'"'s telemetry metadata (e.g., grpc.method).
+func (s) TestRelayContextCollisionMetrics(t *testing.T) {
+	backendMetricsOpts, _ := defaultMetricsOptions(t, nil)
+	backendServer := setupStubServer(t, backendMetricsOpts, nil)
+	backendServer.EmptyCallF = func(_ context.Context, _ *testpb.Empty) (*testpb.Empty, error) {
+		return nil, status.Error(codes.Unimplemented, "EmptyCall not implemented")
+	}
+	defer backendServer.Stop()
+
+	relayMetricsOpts, relayMetricsReader := defaultMetricsOptions(t, nil)
+	otelOpts := opentelemetry.Options{MetricsOptions: *relayMetricsOpts}
+
+	relayServer := &stubserver.StubServer{
+		UnaryCallF: func(ctx context.Context, _ *testpb.SimpleRequest) (*testpb.SimpleResponse, error) {
+			relayCC, err := grpc.NewClient(
+				backendServer.Address,
+				grpc.WithTransportCredentials(insecure.NewCredentials()),
+				opentelemetry.DialOption(otelOpts),
+			)
+			if err != nil {
+				return nil, fmt.Errorf("failed to create relay client: %v", err)
+			}
+			defer relayCC.Close()
+			client := testpb.NewTestServiceClient(relayCC)
+			_, err = client.EmptyCall(ctx, &testpb.Empty{})
+			if status.Code(err) != codes.Unimplemented {
+				t.Errorf("Expected Unimplemented error, got: %v", err)
+			}
+			return &testpb.SimpleResponse{}, nil
+		},
+	}
+	if err := relayServer.Start([]grpc.ServerOption{opentelemetry.ServerOption(otelOpts)}, opentelemetry.DialOption(otelOpts)); err != nil {
+		t.Fatalf("Failed to start relay server: %v", err)
+	}
+	defer relayServer.Stop()
+
+	ctx, cancel := context.WithTimeout(context.Background(), defaultTestTimeout)
+	defer cancel()
+
+	if _, err := relayServer.Client.UnaryCall(ctx, &testpb.SimpleRequest{}); err != nil {
+		t.Fatalf("Unexpected UnaryCall error: %v", err)
+	}
+
+	// Verify Server Metric Identity is retained.
+	if err := checkMetricWithMethod(ctx, relayMetricsReader, "grpc.server.call.started", "grpc.testing.TestService/UnaryCall"); err != nil {
+		t.Fatal(err)
+	}
+
+	// Verify Client Metric Identity correctly resolved to "grpc.testing.TestService/EmptyCall".
+	if err := checkMetricWithMethod(ctx, relayMetricsReader, "grpc.client.attempt.started", "grpc.testing.TestService/EmptyCall"); err != nil {
+		t.Fatal(err)
+	}
+}
+
+// TestRelayContextCollisionTracing verifies that span context is correctly
+// propagated from incoming server requests to outgoing client requests without
+// the client span accidentally adopting the server'"'"'s identity or breaking the
+// trace chain.
+func (s) TestRelayContextCollisionTracing(t *testing.T) {
+	backendTraceOpts, _ := defaultTraceOptions(t)
+	backendServer := setupStubServer(t, nil, backendTraceOpts)
+	backendServer.EmptyCallF = func(_ context.Context, _ *testpb.Empty) (*testpb.Empty, error) {
+		return nil, status.Error(codes.Unimplemented, "EmptyCall not implemented")
+	}
+	defer backendServer.Stop()
+
+	relayTraceOpts, relayTraceExporter := defaultTraceOptions(t)
+	otelOpts := opentelemetry.Options{TraceOptions: *relayTraceOpts}
+
+	relayServer := &stubserver.StubServer{
+		UnaryCallF: func(ctx context.Context, _ *testpb.SimpleRequest) (*testpb.SimpleResponse, error) {
+			relayCC, err := grpc.NewClient(
+				backendServer.Address,
+				grpc.WithTransportCredentials(insecure.NewCredentials()),
+				opentelemetry.DialOption(otelOpts),
+			)
+			if err != nil {
+				return nil, fmt.Errorf("failed to create relay client: %v", err)
+			}
+			defer relayCC.Close()
+			client := testpb.NewTestServiceClient(relayCC)
+			_, err = client.EmptyCall(ctx, &testpb.Empty{})
+			if status.Code(err) != codes.Unimplemented {
+				t.Errorf("Expected Unimplemented error, got: %v", err)
+			}
+			return &testpb.SimpleResponse{}, nil
+		},
+	}
+	if err := relayServer.Start([]grpc.ServerOption{opentelemetry.ServerOption(otelOpts)}, opentelemetry.DialOption(otelOpts)); err != nil {
+		t.Fatalf("Failed to start relay server: %v", err)
+	}
+	defer relayServer.Stop()
+
+	ctx, cancel := context.WithTimeout(context.Background(), defaultTestTimeout)
+	defer cancel()
+
+	_, _ = relayServer.Client.UnaryCall(ctx, &testpb.SimpleRequest{})
+
+	wantSpans := []traceSpanInfo{
+		{name: "Recv.", spanKind: "server"},
+		{name: "Sent.grpc.testing.TestService.EmptyCall", spanKind: "client"},
+	}
+	spans, err := waitForTraceSpans(ctx, relayTraceExporter, wantSpans)
+	if err != nil {
+		t.Fatalf("Failed to wait for spans: %v", err)
+	}
+
+	var srvTraceID, cliTraceID oteltrace.TraceID
+	for _, span := range spans {
+		if span.Name == "Recv." && span.SpanKind == oteltrace.SpanKindServer {
+			srvTraceID = span.SpanContext.TraceID()
+		}
+		if span.Name == "Sent.grpc.testing.TestService.EmptyCall" && span.SpanKind == oteltrace.SpanKindClient {
+			cliTraceID = span.SpanContext.TraceID()
+		}
+	}
+	if !srvTraceID.IsValid() || !cliTraceID.IsValid() {
+		t.Fatalf("Invalid trace IDs found. Server: %s, Client: %s", srvTraceID, cliTraceID)
+	}
+
+	if srvTraceID != cliTraceID {
+		t.Errorf("Trace continuity broken: Server TraceID %s != Client TraceID %s", srvTraceID, cliTraceID)
+	}
+}
+
+// checkMetricWithMethod verifies that a metric with the specified name contains
+// a data point matching the target grpc.method. It does not poll.
+func checkMetricWithMethod(ctx context.Context, reader *metric.ManualReader, metricName, method string) error {
+	metrics := metricsDataFromReader(ctx, reader)
+	if m, ok := metrics[metricName]; ok {
+		if sum, ok := m.Data.(metricdata.Sum[int64]); ok {
+			for _, dp := range sum.DataPoints {
+				if val, ok := dp.Attributes.Value("grpc.method"); ok && val.AsString() == method {
+					return nil
+				}
+			}
+		}
+	}
+	return fmt.Errorf("metric %q with method %q not found", metricName, method)
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./stats/opentelemetry/... 2>&1 | tee /tmp/test_output.txt || true

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
