# Fractional seconds in duration parsing appear to be off by a factor of 10, and some invalid duration formats are being a

**Repository:** grpc/grpc-go
**Base Commit:** deaa9daf44c771a845a8bb9a8339dd29f4f47371

## Problem Statement

Fractional seconds in duration parsing appear to be off by a factor of 10, and some invalid duration formats are being accepted without error.

For example, a duration like `".050s"` parses as 500ms instead of 50ms, and `"-0.200s"` comes back as -2s instead of -200ms. It also looks like certain malformed inputs (like an empty JSON object for a balancer config) aren't being rejected when they should be.

```
--- FAIL: TestDuration_MarshalUnmarshal (0.00s)
    duration_test.go:75: UnmarshalJSON of "-100.700s" = -1m47s, <nil>; want -1m40.7s, <nil>
    duration_test.go:75: UnmarshalJSON of ".050s" = 500ms, <nil>; want 50ms, <nil>
    duration_test.go:75: UnmarshalJSON of "-.001s" = -10ms, <nil>; want -1ms, <nil>
    duration_test.go:75: UnmarshalJSON of "-0.200s" = -2s, <nil>; want -200ms, <nil>
--- FAIL: TestBalancerConfigUnmarshalJSON (0.00s)
    --- FAIL: TestBalancerConfigUnmarshalJSON/empty_json (0.00s)
        serviceconfig_test.go:130: UnmarshalJSON() error = <nil>, wantErr true
FAIL
FAIL	google.golang.org/grpc/internal/serviceconfig	0.623s
FAIL
```

Something seems broken in how the fractional part of the seconds string is being converted — every fractional value is consistently 10x what it should be. cc @dfawley @eshitachandwani

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
