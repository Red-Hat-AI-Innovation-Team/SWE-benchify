# The Dependency Changes workflow started failing after #9173 was merged. It looks like the admin-related packages no long

**Repository:** grpc/grpc-go
**Base Commit:** 1b37d1214eac44c0b14e63c885452cdf644cfb04

## Problem Statement

The Dependency Changes workflow started failing after #9173 was merged. It looks like the admin-related packages no longer build successfully, which means any server that registers administrative services for channelz or CSDS would be broken.

/cc @menghanl

```
ok  	google.golang.org/grpc	10.885s
FAIL	google.golang.org/grpc/admin [build failed]
FAIL	google.golang.org/grpc/admin/test [build failed]
ok  	google.golang.org/grpc/attributes	0.429s
ok  	google.golang.org/grpc/authz	1.050s
```

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
