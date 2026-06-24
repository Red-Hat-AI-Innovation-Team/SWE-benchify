#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/printers/internalversion/printers_test.go b/pkg/printers/internalversion/printers_test.go
index bbf83082e3460..35ef05201402f 100644
--- a/pkg/printers/internalversion/printers_test.go
+++ b/pkg/printers/internalversion/printers_test.go
@@ -5843,6 +5843,140 @@ func TestPrintStorageClass(t *testing.T) {
 	}
 }
 
+func TestPrintStorageClassListEffectiveDefault(t *testing.T) {
+	now := time.Now()
+	earlier := now.Add(-1 * time.Hour)
+
+	tests := []struct {
+		name     string
+		scList   storage.StorageClassList
+		expected []metav1.TableRow
+	}{
+		{
+			name: "single default",
+			scList: storage.StorageClassList{
+				Items: []storage.StorageClass{
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "standard",
+							CreationTimestamp: metav1.Time{Time: now},
+							Annotations: map[string]string{
+								"storageclass.kubernetes.io/is-default-class": "true",
+							},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "fast",
+							CreationTimestamp: metav1.Time{Time: earlier},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+				},
+			},
+			expected: []metav1.TableRow{
+				{Cells: []interface{}{"standard (default)", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "0s"}},
+				{Cells: []interface{}{"fast", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "60m"}},
+			},
+		},
+		{
+			name: "multiple defaults - newest wins",
+			scList: storage.StorageClassList{
+				Items: []storage.StorageClass{
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "standard",
+							CreationTimestamp: metav1.Time{Time: earlier},
+							Annotations: map[string]string{
+								"storageclass.kubernetes.io/is-default-class": "true",
+							},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "fast",
+							CreationTimestamp: metav1.Time{Time: now},
+							Annotations: map[string]string{
+								"storageclass.kubernetes.io/is-default-class": "true",
+							},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+				},
+			},
+			expected: []metav1.TableRow{
+				{Cells: []interface{}{"standard", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "60m"}},
+				{Cells: []interface{}{"fast (default)", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "0s"}},
+			},
+		},
+		{
+			name: "multiple defaults same timestamp - alphabetically first wins",
+			scList: storage.StorageClassList{
+				Items: []storage.StorageClass{
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "zeta",
+							CreationTimestamp: metav1.Time{Time: now},
+							Annotations: map[string]string{
+								"storageclass.kubernetes.io/is-default-class": "true",
+							},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "alpha",
+							CreationTimestamp: metav1.Time{Time: now},
+							Annotations: map[string]string{
+								"storageclass.kubernetes.io/is-default-class": "true",
+							},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+				},
+			},
+			expected: []metav1.TableRow{
+				{Cells: []interface{}{"zeta", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "0s"}},
+				{Cells: []interface{}{"alpha (default)", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "0s"}},
+			},
+		},
+		{
+			name: "no defaults",
+			scList: storage.StorageClassList{
+				Items: []storage.StorageClass{
+					{
+						ObjectMeta: metav1.ObjectMeta{
+							Name:              "standard",
+							CreationTimestamp: metav1.Time{Time: now},
+						},
+						Provisioner: "kubernetes.io/gce-pd",
+					},
+				},
+			},
+			expected: []metav1.TableRow{
+				{Cells: []interface{}{"standard", "kubernetes.io/gce-pd", "Delete", "Immediate", false, "0s"}},
+			},
+		},
+	}
+
+	for _, test := range tests {
+		t.Run(test.name, func(t *testing.T) {
+			rows, err := printStorageClassList(&test.scList, printers.GenerateOptions{})
+			if err != nil {
+				t.Fatal(err)
+			}
+			for i := range rows {
+				rows[i].Object.Object = nil
+			}
+			if !reflect.DeepEqual(test.expected, rows) {
+				t.Errorf("mismatch: %s", cmp.Diff(test.expected, rows))
+			}
+		})
+	}
+}
+
 func TestPrintVolumeAttributesClass(t *testing.T) {
 	tests := []struct {
 		vac      storage.VolumeAttributesClass
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/printers/internalversion/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestPrintStorageClassListEffectiveDefault"]
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
