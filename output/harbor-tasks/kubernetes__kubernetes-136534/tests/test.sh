#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/kubectl/pkg/util/resource/resource_test.go b/staging/src/k8s.io/kubectl/pkg/util/resource/resource_test.go
new file mode 100644
index 0000000000000..a020c32a55a73
--- /dev/null
+++ b/staging/src/k8s.io/kubectl/pkg/util/resource/resource_test.go
@@ -0,0 +1,96 @@
+/*
+Copyright The Kubernetes Authors.
+
+Licensed under the Apache License, Version 2.0 (the "License");
+you may not use this file except in compliance with the License.
+You may obtain a copy of the License at
+
+    http://www.apache.org/licenses/LICENSE-2.0
+
+Unless required by applicable law or agreed to in writing, software
+distributed under the License is distributed on an "AS IS" BASIS,
+WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
+See the License for the specific language governing permissions and
+limitations under the License.
+*/
+
+package resource
+
+import (
+	"testing"
+
+	corev1 "k8s.io/api/core/v1"
+	"k8s.io/apimachinery/pkg/api/resource"
+)
+
+func TestMaxWithNilResourceList(t *testing.T) {
+	tests := []struct {
+		name string
+		a    corev1.ResourceList
+		b    []corev1.ResourceList
+		want corev1.ResourceList
+	}{
+		{
+			name: "nil first argument with non-nil second",
+			a:    nil,
+			b:    []corev1.ResourceList{{corev1.ResourceCPU: resource.MustParse("100m")}},
+			want: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("100m")},
+		},
+		{
+			name: "nil first argument with nil second",
+			a:    nil,
+			b:    []corev1.ResourceList{nil},
+			want: corev1.ResourceList{},
+		},
+		{
+			name: "nil first argument with empty second",
+			a:    nil,
+			b:    []corev1.ResourceList{{}},
+			want: corev1.ResourceList{},
+		},
+		{
+			name: "nil first argument with no second arguments",
+			a:    nil,
+			b:    nil,
+			want: corev1.ResourceList{},
+		},
+		{
+			name: "empty first argument with non-nil second",
+			a:    corev1.ResourceList{},
+			b:    []corev1.ResourceList{{corev1.ResourceCPU: resource.MustParse("100m")}},
+			want: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("100m")},
+		},
+		{
+			name: "non-nil first argument takes max",
+			a:    corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("200m")},
+			b:    []corev1.ResourceList{{corev1.ResourceCPU: resource.MustParse("100m")}},
+			want: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("200m")},
+		},
+		{
+			name: "second argument larger takes max",
+			a:    corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("100m")},
+			b:    []corev1.ResourceList{{corev1.ResourceCPU: resource.MustParse("200m")}},
+			want: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("200m")},
+		},
+	}
+
+	for _, tt := range tests {
+		t.Run(tt.name, func(t *testing.T) {
+			got := max(tt.a, tt.b...)
+			if len(got) != len(tt.want) {
+				t.Errorf("case %q, expected %d resources but got %d", tt.name, len(tt.want), len(got))
+				return
+			}
+			for name, wantQty := range tt.want {
+				gotQty, ok := got[name]
+				if !ok {
+					t.Errorf("case %q, expected resource %s but it was missing", tt.name, name)
+					continue
+				}
+				if gotQty.Cmp(wantQty) != 0 {
+					t.Errorf("case %q, expected resource %s to be %s but got %s", tt.name, name, wantQty.String(), gotQty.String())
+				}
+			}
+		})
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/kubectl/pkg/util/resource/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestMaxWithNilResourceList"]
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
