#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/registry/core/service/ipallocator/ipallocator_test.go b/pkg/registry/core/service/ipallocator/ipallocator_test.go
index 62e5409b54f18..9a3d5bfd7bfc2 100644
--- a/pkg/registry/core/service/ipallocator/ipallocator_test.go
+++ b/pkg/registry/core/service/ipallocator/ipallocator_test.go
@@ -198,6 +198,58 @@ func TestAllocateIPAllocator(t *testing.T) {
 	}
 }
 
+func TestAddOffsetAddress(t *testing.T) {
+	baseAddr := netip.MustParseAddr("fd54:ceea:51ad:2f00::0")
+	for _, tc := range []struct {
+		offset   uint64
+		wantAddr netip.Addr
+	}{
+		{
+			offset:   0,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00::0"),
+		},
+		{
+			offset:   1,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00::1"),
+		},
+		{
+			offset:   math.MaxInt64,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00:7fff:ffff:ffff:ffff"),
+		},
+		{
+			offset:   math.MaxInt64 + 1,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00:8000::"),
+		},
+		{
+			offset:   math.MaxUint64,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00:ffff:ffff:ffff:ffff"),
+		},
+		{
+			offset:   math.MaxUint64 - 1,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00:ffff:ffff:ffff:fffe"),
+		},
+		{
+			offset:   math.MaxUint64>>13 - 1,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00:7:ffff:ffff:fffe"),
+		},
+		{
+			offset:   math.MaxUint64 >> 59,
+			wantAddr: netip.MustParseAddr("fd54:ceea:51ad:2f00::1f"),
+		},
+	} {
+		t.Run(fmt.Sprintf("base:%s,offset:%x,want:%s", baseAddr, tc.offset, tc.wantAddr), func(t *testing.T) {
+			gotAddr, err := addOffsetAddress(baseAddr, tc.offset)
+			if err != nil {
+				t.Fatalf("err: %v", err)
+			}
+
+			if gotAddr.Compare(tc.wantAddr) != 0 {
+				t.Fatalf("compareAddr: got %s, want %s", gotAddr, tc.wantAddr)
+			}
+		})
+	}
+}
+
 func TestAllocateTinyIPAllocator(t *testing.T) {
 	_, cidr, err := netutils.ParseCIDRSloppy("192.168.1.0/32")
 	if err != nil {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/registry/core/service/ipallocator/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestAddOffsetAddress"]
passed = set()
with open("/tmp/test_output.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action == "pass":
            passed.add(test)
            # Also add the bare test name (no subtest suffix)
            passed.add(test.split("/")[0])

all_pass = all(
    t in passed or t.split("/")[0] in passed
    for t in f2p
)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if t not in passed and t.split("/")[0] not in passed]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
