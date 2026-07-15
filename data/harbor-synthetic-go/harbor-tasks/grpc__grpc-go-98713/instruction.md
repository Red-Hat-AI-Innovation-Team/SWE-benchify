# When the xDS client is set up without any custom service discovery authorities and a resource watch is initiated against

**Repository:** grpc/grpc-go
**Base Commit:** aff2688ded4fffd4ab3377df0b6721ddcd0ae502

## Problem Statement

When the xDS client is set up without any custom service discovery authorities and a resource watch is initiated against the default authority, the client crashes with a nil pointer dereference during cleanup instead of gracefully falling back. Stale bot is failing on main, and this is also reproducible locally:

```
panic: runtime error: invalid memory address or nil pointer dereference [recovered, repanicked]
[signal SIGSEGV: segmentation violation code=0x2 addr=0x28 pc=0x1057c556c]

goroutine 492 [running]:
testing.tRunner.func1.2({0x1062191c0, 0x10649f860})
	/usr/local/go/src/testing/testing.go:1974 +0x1a0
testing.tRunner.func1()
	/usr/local/go/src/testing/testing.go:1977 +0x318
panic({0x1062191c0?, 0x10649f860?})
	/usr/local/go/src/runtime/panic.go:860 +0x12c
```

It looks like the authority object being closed is nil — presumably it was never properly created when no explicit authorities are configured. There's also a leaked goroutine from the callback serializer that never gets cleaned up:

```
grpctest.go:45: Leaked goroutine: goroutine 493 [chan receive]:
```

The close path should handle the case where the default authority wasn't explicitly instantiated, rather than panicking.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
