# Binary metadata values with standard base64 padding are not being decoded correctly when received as header values. This

**Repository:** grpc/grpc-go
**Base Commit:** d83274d1cdc076294e9c79248d628e9bd227f578

## Problem Statement

Binary metadata values with standard base64 padding are not being decoded correctly when received as header values. This used to work fine but started seeing this after upgrading to v1.83.0-dev. Values that contain padding characters (`=`) appear to get truncated or garbled during decoding.

Reproduces on v1.12.x as well, so this might be a regression that was reintroduced. Possibly related to #9210.

```
--- FAIL: Test (10.99s)
    --- FAIL: Test/DecodeMetadataHeader (0.00s)
        http_util_test.go:217: decodeMetadataHeader("key-bin", "Zm9vAGJhcg==") = "foo\x00ba", illegal base64 data at input byte 10, want "foo\x00bar", <nil>
FAIL
FAIL	google.golang.org/grpc/internal/transport	12.809s
FAIL
```

The input is a validly padded base64 string, and the expected output should be the full decoded binary value. Instead, the last byte is dropped and an error about illegal base64 data is returned. This breaks any binary metadata exchange where the encoded value happens to include standard padding.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
