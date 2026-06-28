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

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestFieldManagerUpdateNoErrors"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
