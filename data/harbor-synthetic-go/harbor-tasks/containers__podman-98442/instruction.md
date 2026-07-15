# ### Issue Description

**Repository:** containers/podman
**Base Commit:** e239f32ad720cb591d2548c50d1a20f70d9c1e81

## Problem Statement

### Issue Description

Something seems off with how column headers are handled in tabular output — headers are showing up when `noheader` is set, and being hidden when it's not. Feels like the logic got flipped somewhere. Seeing this on main, not sure about main.

Also noticing that some storage-related display operations (like listing store info) seem broken or incomplete, possibly missing fields or failing unexpectedly.

Tried building and hit this:

```
FAIL	go.podman.io/podman/v6/cmd/podman/machine [build failed]
FAIL

github.com/proglottis/gpgme: exec: "pkg-config": executable file not found in $PATH
```

@haircommander any ideas?

### Steps to reproduce the issue

Build or run tests on latest main.

### Describe the results you received

Build failures and inverted header behavior in formatted table output.

### Describe the results you expected

Headers shown by default, hidden when requested, and a clean build.

### podman info output

```yaml
N/A
```

### Privileged Or Rootless

None

### Upstream Latest Release

Yes

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
