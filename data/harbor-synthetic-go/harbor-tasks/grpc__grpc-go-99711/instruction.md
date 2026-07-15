# When a request arrives over an older HTTP protocol version (not HTTP/2), the server handler transport should reject it w

**Repository:** grpc/grpc-go
**Base Commit:** b63ba9a6743d18eb646bbfbbcbbda9e053496822

## Problem Statement

When a request arrives over an older HTTP protocol version (not HTTP/2), the server handler transport should reject it with a clear error indicating that HTTP/2 is required. Instead, it appears to silently proceed, which eventually causes a nil pointer dereference panic downstream.

cc @eshitachandwani @lidizheng — this also crashes the relevant transport tests:

```
--- FAIL: Test (2.67s)
    --- FAIL: Test/HandlerTransport_NewServerHandlerTransport (0.00s)
panic: runtime error: invalid memory address or nil pointer dereference [recovered, repanicked]
[signal SIGSEGV: segmentation violation code=0x2 addr=0x18 pc=0x1012aa110]

goroutine 1635 [running]:
testing.tRunner.func1.2({0x1019b4560, 0x101b37a20})
	/usr/local/go/src/testing/testing.go:1974 +0x1a0
testing.tRunner.func1()
	/usr/local/go/src/testing/testing.go:1977 +0x318
panic({0x1019b4560?, 0x101b37a20?})
	/usr/local/go/src/runtime/panic.go:860 +0x12c
google.golang.org/grpc/internal/transport.s.TestHandlerTransport_NewServerHandlerTransport({{}}, 0xd2d632ee008)
	/home/jenny/projects/grpc-go/internal/transport/handler_server_test.go:210 +0xcc0
google.golang.org/grpc/internal/grpctest.RunSubTests.func1(0xd2d632ee008)
	/home/jenny/projects/grpc-go/internal/grpctest/grpctest.go:132 +0xac
testing.tRunner(0xd2d632ee008, 0xd2d6322e220)
	/usr/local/go/src/testing/testing.go:2036 +0xc4
created by testing.(*T).Run in goroutine 35
	/usr/local/go/src/testing/testing.go:2101 +0x3a8
FAIL	google.golang.org/grpc/internal/transport	3.384s
FAIL
```

The protocol version check should return an error before any further processing happens, rather than falling through and hitting a nil dereference.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
