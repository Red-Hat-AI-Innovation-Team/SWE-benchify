# When out-of-band load reporting is active, the system panics due to a nil map access while trying to record incoming loa

**Repository:** grpc/grpc-go
**Base Commit:** 2ad2ee78e01c86ad53dde4dce4d5bbcab3444a90

## Problem Statement

When out-of-band load reporting is active, the system panics due to a nil map access while trying to record incoming load reports. This happens during normal operation when the load balancing policy receives and processes ORCA reports from backends.

```
panic: assignment to entry in nil map

goroutine 66 [running]:
google.golang.org/grpc/interop.(*orcaOOBListener).OnLoadReport(0x77fff3d080c0?, 0x77fff3a26a80)
	/home/alex/projects/grpc-go/interop/orcalb.go:187 +0xcc
google.golang.org/grpc/orca.(*producer).runStream(0x77fff3d34000, {0x1019b5560?, 0x77fff3d34050?}, 0x3b9aca00)
	/home/alex/projects/grpc-go/orca/producer.go:221 +0x218
google.golang.org/grpc/orca.(*producer).run.func1()
	/home/alex/projects/grpc-go/orca/producer.go:176 +0x24
google.golang.org/grpc/internal/backoff.RunF({0x1019b5560, 0x77fff3d34050}, 0x77fff3a3df48, 0x77fff3ac43c0)
	/home/alex/projects/grpc-go/internal/backoff/backoff.go:97 +0xb4
google.golang.org/grpc/orca.(*producer).run(0x0?, {0x1019b5560?, 0x77fff3d34050?}, 0x0?, 0x0?)
	/home/alex/projects/grpc-go/orca/producer.go:197 +0x6c
created by google.golang.org/grpc/orca.(*producer).updateRunLocked in goroutine 32
	/home/alex/projects/grpc-go/orca/producer.go:167 +0x160
FAIL	google.golang.org/grpc/interop	3.040s
FAIL
```

It looks like the map used to accumulate load report data isn't being initialized before reports start arriving. This is a straightforward crash that should be easy to reproduce with the interop tests.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
