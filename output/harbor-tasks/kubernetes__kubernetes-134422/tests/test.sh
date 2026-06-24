#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/printers/internalversion/printers_test.go b/pkg/printers/internalversion/printers_test.go
index cc0700be31f6a..e4376ec66e684 100644
--- a/pkg/printers/internalversion/printers_test.go
+++ b/pkg/printers/internalversion/printers_test.go
@@ -26,6 +26,7 @@ import (
 
 	"github.com/google/go-cmp/cmp"
 	apiv1 "k8s.io/api/core/v1"
+	networkingv1 "k8s.io/api/networking/v1"
 	"k8s.io/apimachinery/pkg/api/resource"
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
 	"k8s.io/apimachinery/pkg/runtime/schema"
@@ -1055,6 +1056,21 @@ func TestPrintIngressClass(t *testing.T) {
 			},
 		},
 		expected: []metav1.TableRow{{Cells: []interface{}{"test2", "example.com/controller2", "<none>", "11y"}}},
+	}, {
+		name: "example with default annotation",
+		ingressClass: &networking.IngressClass{
+			ObjectMeta: metav1.ObjectMeta{
+				Name:              "test-default",
+				CreationTimestamp: metav1.Time{Time: time.Now().Add(time.Duration(-9 * 365 * 24 * time.Hour))},
+				Annotations: map[string]string{
+					networkingv1.AnnotationIsDefaultIngressClass: "true",
+				},
+			},
+			Spec: networking.IngressClassSpec{
+				Controller: "example.com/controller",
+			},
+		},
+		expected: []metav1.TableRow{{Cells: []interface{}{"test-default (default)", "example.com/controller", "<none>", "9y"}}},
 	}}
 
 	for _, testCase := range testCases {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/printers/internalversion/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestPrintIngressClass"]
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
