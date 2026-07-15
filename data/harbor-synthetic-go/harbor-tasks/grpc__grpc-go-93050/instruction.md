# When a name resolver encounters an error, the error is forwarded down to the balancing layer. If the active balancer doe

**Repository:** grpc/grpc-go
**Base Commit:** 4f890c3971bbb01c4a12d84b40b26c7136660c31

## Problem Statement

When a name resolver encounters an error, the error is forwarded down to the balancing layer. If the active balancer doesn't provide its own error-handling logic, this results in a nil pointer dereference and a crash instead of being handled gracefully. This seems like the kind of thing that should fall back to some safe default behavior rather than panicking.

Might be a duplicate of #9207 but the symptoms are slightly different — here it's specifically the lazy balancer that triggers it.

```
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x2 addr=0x0 pc=0x104a9f8d4]

goroutine 170 [running]:
google.golang.org/grpc/internal/balancer/stub.(*bal).ResolverError(0x2713e1dbc200?, {0x10518f6f8?, 0x2713e1dbc6b0?})
	/home/alex/projects/grpc-go/internal/balancer/stub/stub.go:69 +0x24
google.golang.org/grpc/internal/balancer/gracefulswitch.(*Balancer).ResolverError(0x2713e1d14280, {0x10518f6f8, 0x2713e1dbc6b0})
	/home/alex/projects/grpc-go/internal/balancer/gracefulswitch/gracefulswitch.go:217 +0xac
google.golang.org/grpc.(*ccBalancerWrapper).resolverError.func1({0x105197120?, 0x2713e1b66140?})
	/home/alex/projects/grpc-go/balancer_wrapper.go:148 +0x68
FAIL	google.golang.org/grpc/balancer/lazy	5.492s
```

cc @atollena @markdroth

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
