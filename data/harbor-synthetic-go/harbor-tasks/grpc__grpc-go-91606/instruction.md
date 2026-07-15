# When using a custom codec on the server side via the legacy codec interface, the server fails to build because the inter

**Repository:** grpc/grpc-go
**Base Commit:** e0344146cddba0abd0202916aa3483eee54b54e4

## Problem Statement

When using a custom codec on the server side via the legacy codec interface, the server fails to build because the internal bridge between the old and new codec interfaces doesn't satisfy the new interface — specifically, it's missing the method that returns the codec's name.

This means any server that relies on the older codec registration path can't compile at all. The codec name ends up empty, which would cause content-type negotiation to break even if the build issue were somehow worked around.

```
FAIL	google.golang.org/grpc [build failed]
FAIL

# google.golang.org/grpc [google.golang.org/grpc.test]
./codec.go:54:9: cannot use codecV0Bridge{…} (value of struct type codecV0Bridge) as "google.golang.org/grpc/encoding".CodecV2 value in return statement: codecV0Bridge does not implement "google.golang.org/grpc/encoding".CodecV2 (missing method Name)
```

The internal adapter that wraps the old-style codec into the newer codec interface needs to also provide the name of the serialization format. Without it, the adapter doesn't fully implement the required interface, and nothing compiles.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
