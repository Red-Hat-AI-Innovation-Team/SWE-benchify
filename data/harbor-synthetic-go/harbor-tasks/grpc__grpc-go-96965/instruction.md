# When setting up transport configurations with specific connection security settings and registering them by name, the bu

**Repository:** grpc/grpc-go
**Base Commit:** af8a7280c170f3f6af303ec2d27867e78fb1aac3

## Problem Statement

When setting up transport configurations with specific connection security settings and registering them by name, the builder fails to find those configurations at connection time. Every attempt to build a transport results in an error saying the config name is unknown, even though it was clearly registered beforehand. It's as if the lookup mechanism is searching in the wrong place — matching against the server address instead of the actual config name, or the registered configs simply aren't visible to the builder.

This reproduces on v1.63.x.

```
--- FAIL: Test (0.01s)
    --- FAIL: Test/Build_Success (0.00s)
        grpc_transport_test.go:152: Build(serverID1) call failed: grpctransport: unknown config name "server-address" specified in ServerIdentifierExtension
    --- FAIL: Test/NewStream_Error (0.00s)
        grpc_transport_test.go:343: Failed to build transport: grpctransport: unknown config name "invalid-server-uri" specified in ServerIdentifierExtension
    --- FAIL: Test/NewStream_Success (0.00s)
        grpc_transport_test.go:271: Failed to build transport: grpctransport: unknown config name "127.0.0.1:54696" specified in ServerIdentifierExtension
    --- FAIL: Test/NewStream_Success_WithCustomGRPCNewClient (0.00s)
        grpc_transport_test.go:314: builder.Build({ServerURI:127.0.0.1:54697 Extensions:{ConfigName:custom-dialer-config}}) failed: grpctransport: unknown config name "127.0.0.1:54697" specified in ServerIdentifierExtension
    --- FAIL: Test/Build_Multiple (0.00s)
        grpc_transport_ext_test.go:192: Failed to build transport: grpctransport: unknown config name "127.0.0.1:54699" specified in ServerIdentifierExtension
```

It looks like the config name resolution is completely broken — configs that are properly registered and named are silently not found, causing all transport builds to fail.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
