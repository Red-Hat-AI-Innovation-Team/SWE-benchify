# When creating a new pod without specifying any volumes, the infra container ends up with volume mounts that were never r

**Repository:** containers/podman
**Base Commit:** eca7d85562ce93cdd191f50d12d3bf982ba7fba1

## Problem Statement

When creating a new pod without specifying any volumes, the infra container ends up with volume mounts that were never requested. This causes volume-related operations to behave unexpectedly. Seeing this on main — noticed this in the Lock closed issues and PRs run.

The whole build is broken right now:

```
FAIL	go.podman.io/podman/v6/cmd/podman [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/containers [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/pods [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/volumes [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/images [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/system [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/networks [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/kube [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/machine [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/manifest [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman/quadlet [build failed]
FAIL	go.podman.io/podman/v6/cmd/podman-testing [build failed]
--- FAIL: TestStartAndStopMultipleRegistries (0.03s)
    registry_test.go:43: 
        	Error Trace:	/home/alex/projects/podman/hack/podman-registry-go/registry_test.go:43
        	Error:      	Received une
```

It looks like something changed in how pod infrastructure containers get their volume configuration populated — volumes are showing up from nowhere when none were requested.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
