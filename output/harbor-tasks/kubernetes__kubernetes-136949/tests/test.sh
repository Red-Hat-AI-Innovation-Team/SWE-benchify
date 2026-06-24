#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/capmanagers_test.go b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/capmanagers_test.go
index 9b139f93e23dd..1ce682dd7e8f9 100644
--- a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/capmanagers_test.go
+++ b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/capmanagers_test.go
@@ -35,15 +35,24 @@ import (
 	"sigs.k8s.io/structured-merge-diff/v6/fieldpath"
 )
 
-type fakeManager struct{}
+type fakeManager struct {
+	Manager internal.Manager
+	Error   error
+}
 
 var _ internal.Manager = &fakeManager{}
 
-func (*fakeManager) Update(_, newObj runtime.Object, managed internal.Managed, _ string) (runtime.Object, internal.Managed, error) {
+func (f *fakeManager) Update(liveObj, newObj runtime.Object, managed internal.Managed, manager string) (runtime.Object, internal.Managed, error) {
+	if f.Error != nil {
+		return nil, nil, f.Error
+	}
+	if f.Manager != nil {
+		return f.Manager.Update(liveObj, newObj, managed, manager)
+	}
 	return newObj, managed, nil
 }
 
-func (*fakeManager) Apply(_, _ runtime.Object, _ internal.Managed, _ string, _ bool) (runtime.Object, internal.Managed, error) {
+func (f *fakeManager) Apply(_, _ runtime.Object, _ internal.Managed, _ string, _ bool) (runtime.Object, internal.Managed, error) {
 	panic("not implemented")
 }
 
diff --git a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager_test.go b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager_test.go
index 1ae01dab6e91e..67ec62153288c 100644
--- a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager_test.go
+++ b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager_test.go
@@ -18,14 +18,67 @@ package internal_test
 
 import (
 	"encoding/json"
+	"errors"
 	"os"
 	"path/filepath"
 	"strings"
+	"testing"
 
+	apiequality "k8s.io/apimachinery/pkg/api/equality"
+	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
+	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
+	"k8s.io/apimachinery/pkg/runtime"
+	"k8s.io/apimachinery/pkg/runtime/schema"
 	"k8s.io/apimachinery/pkg/util/managedfields/internal"
+	internaltesting "k8s.io/apimachinery/pkg/util/managedfields/internal/testing"
 	"k8s.io/kube-openapi/pkg/validation/spec"
 )
 
+func TestFieldManagerUpdateNoErrors(t *testing.T) {
+	fm := &fakeManager{}
+	f := internaltesting.NewTestFieldManagerImpl(fakeTypeConverter, schema.FromAPIVersionAndKind("v1", "Pod"),
+		"",
+		func(m internal.Manager) internal.Manager {
+			fm.Manager = m
+			return fm
+		})
+
+	podWithLabels := func(labels ...string) runtime.Object {
+		labelMap := map[string]interface{}{}
+		for _, key := range labels {
+			labelMap[key] = "true"
+		}
+		obj := &unstructured.Unstructured{
+			Object: map[string]interface{}{
+				"metadata": map[string]interface{}{
+					"labels": labelMap,
+				},
+			},
+		}
+		obj.SetKind("Pod")
+		obj.SetAPIVersion("v1")
+		return obj
+	}
+
+	f.UpdateNoErrors(podWithLabels("one"), "fieldmanager_test_update_1")
+	if len(f.ManagedFields()) == 0 {
+		t.Fatalf("expected managedFields to be set, but they are empty")
+	}
+
+	before := []metav1.ManagedFieldsEntry{}
+	for _, m := range f.ManagedFields() {
+		before = append(before, *m.DeepCopy())
+	}
+
+	// Inject an error so UpdateNoErrors will hit the error code path.
+	fm.Error = errors.New("test error")
+	f.UpdateNoErrors(podWithLabels("one", "two"), "fieldmanager_test_update_1")
+
+	if after := f.ManagedFields(); !apiequality.Semantic.DeepEqual(before, after) {
+		t.Fatalf("expected idempotence, but managedFields changed:\nbefore: %v\n after: %v", mustMarshal(before), mustMarshal(after))
+	}
+}
+
 var fakeTypeConverter = func() internal.TypeConverter {
 	data, err := os.ReadFile(filepath.Join(
 		strings.Repeat(".."+string(filepath.Separator), 8),
diff --git a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/testing/testfieldmanager.go b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/testing/testfieldmanager.go
index 1799896b57715..07558232abd4d 100644
--- a/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/testing/testfieldmanager.go
+++ b/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/testing/testfieldmanager.go
@@ -106,6 +106,11 @@ func (f *TestFieldManagerImpl) Update(obj runtime.Object, manager string) error
 	return err
 }
 
+// UpdateNoErrors is the same as Update, but it will not return errors.
+func (f *TestFieldManagerImpl) UpdateNoErrors(obj runtime.Object, manager string) {
+	f.liveObj = f.fieldManager.UpdateNoErrors(f.liveObj, obj, manager)
+}
+
 // ManagedFields returns the list of existing managed fields for the
 // liveObj.
 func (f *TestFieldManagerImpl) ManagedFields() []metav1.ManagedFieldsEntry {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/... ./staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/testing/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestFieldManagerUpdateNoErrors"]
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
