grpc Server Metrics rpcInfo gets overwritten by grpc client invocations
### What version of gRPC are you using?
google.golang.org/grpc v1.80.0 

### What version of Go are you using (`go version`)?

go1.25.0 linux/amd64

### What operating system (Linux, Windows, …) and version?
Linux Debian

### What did you do?

I have a server that makes a grpc call as part of serving a request. The call goes to a completely different server. However, I propagate the incoming server context to better propagate deadlines and other metadata. This is however resulting in the server grpc metrics getting modified -- instad of reporting the server method, the metrics are attributed to the client method instead.

I have this demo to illustrate the issue:
```golang
func TestOpenTelemetrySharedContextBug(t *testing.T) {
	ctx := context.Background()

	// 1. Set up an OpenTelemetry Manual Reader to inspect the recorded metrics in-memory.
	reader := metric.NewManualReader()
	meterProvider := metric.NewMeterProvider(metric.WithReader(reader))

	otelOptions := opentelemetry.Options{
		MetricsOptions: opentelemetry.MetricsOptions{
			MeterProvider: meterProvider,
		},
	}

	// 2. Define a minimal gRPC Service without requiring protoc generation.
	dummyServiceDesc := grpc.ServiceDesc{
		ServiceName: "test.DummyService",
		HandlerType: (*any)(nil),
		Methods: []grpc.MethodDesc{
			{
				MethodName: "ServerMethod",
				Handler: func(srv any, incomingCtx context.Context, dec func(any) error, interceptor grpc.UnaryServerInterceptor) (any, error) {
					// Inside the server method, construct an outgoing client connection.
					cc, err := grpc.NewClient(
						"passthrough:///localhost:12345",
						grpc.WithTransportCredentials(insecure.NewCredentials()),
						opentelemetry.DialOption(otelOptions),
					)
					if err != nil {
						return nil, err
					}
					defer cc.Close()

					// BUG TRIGGER: Make the outgoing client RPC using the incoming server context.
					_ = cc.Invoke(incomingCtx, "/test.DummyService/ClientMethod", nil, nil)

					return nil, nil
				},
			},
		},
		Streams:  []grpc.StreamDesc{},
		Metadata: "dummy.proto",
	}

	// 3. Start the gRPC Server with the ServerOption configured.
	lis := bufconn.Listen(1024 * 1024)
	server := grpc.NewServer(opentelemetry.ServerOption(otelOptions))
	server.RegisterService(&dummyServiceDesc, nil)
	go server.Serve(lis)
	defer server.Stop()

	// 4. Trigger the server method via an external client.
	dialer := func(context.Context, string) (net.Conn, error) {
		return lis.Dial()
	}
	cc, err := grpc.NewClient(
		"passthrough:///bufnet",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(dialer),
	)
	if err != nil {
		t.Fatalf("Failed to dial server: %v", err)
	}
	defer cc.Close()

	_ = cc.Invoke(ctx, "/test.DummyService/ServerMethod", nil, nil)

	// 5. Collect and inspect the OpenTelemetry metrics.
	var rm metricdata.ResourceMetrics
	if err := reader.Collect(ctx, &rm); err != nil {
		t.Fatalf("Failed to collect metrics: %v", err)
	}

	var found bool
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name == "grpc.server.call.duration" {
				data, ok := m.Data.(metricdata.Histogram[float64])
				if !ok {
					continue
				}
				for _, dp := range data.DataPoints {
					found = true
					gotAttrs := dp.Attributes.ToSlice()
					fmt.Printf("Recorded attributes for grpc.server.call.duration: %v\n", gotAttrs)

					var methodVal string
					for _, kv := range gotAttrs {
						if string(kv.Key) == "grpc.method" {
							methodVal = kv.Value.AsString()
						}
					}
					if methodVal != "test.DummyService/ClientMethod" {
						t.Errorf("Expected bug to mutate method to test.DummyService/ClientMethod, got %q", methodVal)
					}
				}
			}
		}
	}

	if !found {
		t.Fatalf("Metric grpc.server.call.duration not found in recorded metrics")
	}
}
```

### What did you expect to see?

I expected to see the grpc.server.call.duration recording with grpc.method test.DummyService/ServerMethod.

I don't want to be forced to create a child context for every single RPC call if possible.

### What did you see instead?

Metric gets recorded with the ClientMethod instead.

```
Recorded attributes for grpc.server.call.duration: [{grpc.method {4 0 test.DummyService/ClientMethod <nil>}} {grpc.status {4 0 OK <nil>}}]
```

From what I can tell, this is because both the server and client interceptors use the same contextKey so the outbound client call overwrites `aiInfo.method`

**Repository:** `grpc/grpc-go`
**Base commit:** `a481b8f755bccf5c0308f1530e785bb58a770150`

## Hints

Hi @rahulkjoshi , Thanks for raising the issue.
We are looking into it and will get back to you soon.

Hi @rahulkjoshi , thanks for your patience. I will be publishing a fix PR for this soon.
