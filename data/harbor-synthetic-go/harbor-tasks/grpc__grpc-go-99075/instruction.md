# Secure connections from clients using older (but still valid) TLS versions are being rejected by the server, even though

**Repository:** grpc/grpc-go
**Base Commit:** 330be41c954b852f12c949381931c7788444b1c2

## Problem Statement

Secure connections from clients using older (but still valid) TLS versions are being rejected by the server, even though no explicit minimum or maximum TLS version has been configured. The expectation is that the default behavior accepts a reasonable range of TLS versions, but it seems like the server is now only accepting the latest version and refusing everything else.

This appears to have regressed — bisected to around the time #9184 landed. Previously, these connections worked fine without any special configuration.

```
FAIL	./security/advancedtls [setup failed]
FAIL

# ./security/advancedtls
main module (google.golang.org/grpc) does not contain package google.golang.org/grpc/security/advancedtls
```

The default TLS version range should allow clients on supported-but-older versions to connect successfully. Instead, they're getting rejected outright, which breaks backward compatibility for deployments that don't pin specific TLS versions.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
