# When a gRPC channel is created and later becomes idle or is no longer needed, the underlying transport connections are n

**Repository:** grpc/grpc-go
**Base Commit:** 78ed9ee2ed6bd32fe2084f01a732ed5326acefa9

## Problem Statement

When a gRPC channel is created and later becomes idle or is no longer needed, the underlying transport connections are never cleaned up. Over time this causes the process to accumulate open connections and leaked goroutines, eventually exhausting system resources.

It appears that the shutdown path for the connection management layer isn't properly closing things out — goroutines responsible for serializing callbacks remain running indefinitely, waiting on channels that are never closed.

```
--- FAIL: Test (10.29s)
    --- FAIL: Test/Build_Success (10.03s)
        tlogger.go:133: INFO clientconn.go:1837 [core] original dial target is: "server-address"  (t=+292.875µs)
        tlogger.go:133: INFO clientconn.go:516 [core] [Channel #1] Channel created for target "server-address"  (t=+371.667µs)
        tlogger.go:133: INFO clientconn.go:516 [core] [Channel #2] Channel created for target "server-address"  (t=+442.167µs)
        grpctest.go:45: Leaked goroutine: goroutine 50 [chan receive]:
            google.golang.org/grpc/internal/grpcsync.(*CallbackSerializer).run(0x5c4c61712350, {0x101abcc20, 0x5c4c61710050})
            	/home/alex/projects/grpc-go/internal/grpcsync/callback_serializer.go:88 +0xcc
            created by google.golang.org/grpc/internal/grpcsync.NewCallbackSerializer in goroutine 49
            	/home/alex/projects/grpc-go/internal/grpcsync/callback_serializer.go:52 +0x10c
        grpctest.go:45: Leaked goroutine: goroutine 51 [chan receive]:
```

The callback serializer goroutine is never terminated, which suggests the teardown sequence for the channel or its subcomponents is missing a cleanup step somewhere.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
