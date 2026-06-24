#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/registry/core/resourcequota/strategy_test.go b/pkg/registry/core/resourcequota/strategy_test.go
index c571c2a336dc3..4066ec9407a48 100644
--- a/pkg/registry/core/resourcequota/strategy_test.go
+++ b/pkg/registry/core/resourcequota/strategy_test.go
@@ -17,6 +17,8 @@ limitations under the License.
 package resourcequota
 
 import (
+	"context"
+	"reflect"
 	"testing"
 
 	"k8s.io/apimachinery/pkg/api/resource"
@@ -58,3 +60,84 @@ func TestResourceQuotaStrategy(t *testing.T) {
 		t.Errorf("ResourceQuota does not allow setting status on create")
 	}
 }
+
+func Test_WarningsOnCreate(t *testing.T) {
+	tests := []struct {
+		name         string
+		args         *api.ResourceQuota
+		wantWarnings []string
+	}{
+		{
+			name:         "Empty Hard Spec",
+			args:         &api.ResourceQuota{},
+			wantWarnings: []string{},
+		},
+		{
+			name: "Request less than limit",
+			args: &api.ResourceQuota{
+				Spec: api.ResourceQuotaSpec{
+					Hard: api.ResourceList{
+						api.ResourceName("requests.cpu"):               resource.MustParse("500m"),
+						api.ResourceName("limits.cpu"):                 resource.MustParse("1"),
+						api.ResourceName("requests.memory"):            resource.MustParse("1Gi"),
+						api.ResourceName("limits.memory"):              resource.MustParse("2Gi"),
+						api.ResourceName("requests.storage"):           resource.MustParse("1Gi"),
+						api.ResourceName("limits.storage"):             resource.MustParse("2Gi"),
+						api.ResourceName("requests.ephemeral-storage"): resource.MustParse("1Gi"),
+						api.ResourceName("limits.ephemeral-storage"):   resource.MustParse("2Gi"),
+					},
+				},
+			},
+			wantWarnings: []string{},
+		},
+		{
+			name: "Request greater than limit",
+			args: &api.ResourceQuota{
+				Spec: api.ResourceQuotaSpec{
+					Hard: api.ResourceList{
+						api.ResourceName("requests.cpu"):               resource.MustParse("2"),
+						api.ResourceName("limits.cpu"):                 resource.MustParse("1"),
+						api.ResourceName("requests.memory"):            resource.MustParse("3Gi"),
+						api.ResourceName("limits.memory"):              resource.MustParse("2Gi"),
+						api.ResourceName("requests.storage"):           resource.MustParse("3Gi"),
+						api.ResourceName("limits.storage"):             resource.MustParse("2Gi"),
+						api.ResourceName("requests.ephemeral-storage"): resource.MustParse("3Gi"),
+						api.ResourceName("limits.ephemeral-storage"):   resource.MustParse("2Gi"),
+					},
+				},
+			},
+			wantWarnings: []string{
+				"ResourceQuota requests.cpu (2) should be less than limits.cpu (1)",
+				"ResourceQuota requests.memory (3Gi) should be less than limits.memory (2Gi)",
+				"ResourceQuota requests.storage (3Gi) should be less than limits.storage (2Gi)",
+				"ResourceQuota requests.ephemeral-storage (3Gi) should be less than limits.ephemeral-storage (2Gi)",
+			},
+		},
+		{
+			name: "Request greater than limit, bare names",
+			args: &api.ResourceQuota{
+				Spec: api.ResourceQuotaSpec{
+					Hard: api.ResourceList{
+						api.ResourceName("cpu"):           resource.MustParse("2"),
+						api.ResourceName("limits.cpu"):    resource.MustParse("1"),
+						api.ResourceName("memory"):        resource.MustParse("3Gi"),
+						api.ResourceName("limits.memory"): resource.MustParse("2Gi"),
+					},
+				},
+			},
+			wantWarnings: []string{
+				"ResourceQuota cpu (2) should be less than limits.cpu (1)",
+				"ResourceQuota memory (3Gi) should be less than limits.memory (2Gi)",
+			},
+		},
+	}
+
+	for _, tt := range tests {
+		t.Run(tt.name, func(t *testing.T) {
+			warnings := Strategy.WarningsOnCreate(context.Background(), tt.args)
+			if len(warnings)+len(tt.wantWarnings) > 0 && !reflect.DeepEqual(warnings, tt.wantWarnings) {
+				t.Errorf("WarningsOnCreate()\n   got: %q\n  want: %q", warnings, tt.wantWarnings)
+			}
+		})
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/registry/core/resourcequota/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["Test_WarningsOnCreate"]
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
