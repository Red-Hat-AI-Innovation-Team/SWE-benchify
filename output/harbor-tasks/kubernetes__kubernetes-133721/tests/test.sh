#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy_test.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy_test.go
index 97538054286cd..c0c521ccae604 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy_test.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy_test.go
@@ -23,6 +23,7 @@ import (
 
 	"k8s.io/apiextensions-apiserver/pkg/apis/apiextensions"
 	apiextensionsv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
+	apiextensionsv1beta1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1"
 	structuralschema "k8s.io/apiextensions-apiserver/pkg/apiserver/schema"
 	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
 	"k8s.io/apimachinery/pkg/runtime/schema"
@@ -244,3 +245,142 @@ func TestStatusStrategyValidateUpdate(t *testing.T) {
 		}
 	}
 }
+
+const listTypeResourceSchemaForLegacyV1beta1 = `
+apiVersion: apiextensions.k8s.io/v1beta1
+kind: CustomResourceDefinition
+metadata:
+  name: foos.test
+spec:
+  group: test
+  names:
+    kind: Foo
+    listKind: FooList
+    plural: foos
+    singular: foo
+  scope: Cluster
+  versions:
+  - name: v1
+    served: true
+    storage: true
+  - name: v2
+    served: true
+    storage: true
+    subresources:
+      status: {}
+  - name: v3
+    served: true
+    storage: true
+    schema:
+      openAPIV3Schema:
+        type: object
+        properties:
+          spec:
+            type: object
+            properties:
+              data:
+                type: string
+  - name: v4
+    served: true
+    storage: true
+    schema:
+      openAPIV3Schema:
+        type: object
+        properties:
+          spec:
+            type: object
+            properties:
+              data:
+                type: string
+    subresources:
+      status: {}
+`
+
+// TestStatusStrategyValidateUpdateForLegacyV1beta1 legacy test the crd with subresource and without .Schema.OpenAPIV3Schema,
+func TestStatusStrategyValidateUpdateForLegacyV1beta1(t *testing.T) {
+	crdV1beta1 := &apiextensionsv1beta1.CustomResourceDefinition{}
+	err := yaml.Unmarshal([]byte(listTypeResourceSchemaForLegacyV1beta1), &crdV1beta1)
+	if err != nil {
+		t.Fatalf("unexpected decoding error: %v", err)
+	}
+	t.Logf("crd details: %v", crdV1beta1)
+	crd := &apiextensions.CustomResourceDefinition{}
+	if err = apiextensionsv1beta1.Convert_v1beta1_CustomResourceDefinition_To_apiextensions_CustomResourceDefinition(crdV1beta1, crd, nil); err != nil {
+		t.Fatalf("unexpected convert error: %v", err)
+	}
+	t.Logf("crd details: %v", crd)
+
+	ctx := context.TODO()
+
+	tcs := []struct {
+		name                string
+		old                 *unstructured.Unstructured
+		obj                 *unstructured.Unstructured
+		version             int
+		hasStructuralSchema bool
+		isValid             bool
+	}{
+		{
+			name:                "the CRD does not have a schema at all",
+			old:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v1", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			obj:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v1", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{"phase": "ready"}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			version:             0,
+			hasStructuralSchema: false,
+			isValid:             true,
+		},
+		{
+			name:                "the CRD does not have a schema at all but declares the status property",
+			old:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v2", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			obj:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v2", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{"phase": "ready"}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			version:             1,
+			hasStructuralSchema: false,
+			isValid:             true,
+		},
+		{
+			name:                "the CRD has a schema",
+			old:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v3", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			obj:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v3", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{"phase": "ready"}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			version:             2,
+			hasStructuralSchema: true,
+			isValid:             true,
+		},
+		{
+			name:                "the CRD has a schema and has declares the status property",
+			old:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v4", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			obj:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v4", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{"phase": "ready"}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			version:             3,
+			hasStructuralSchema: true,
+			isValid:             true,
+		},
+		{
+			name:                "the CRD has a schema but it not being structural",
+			old:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v4", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			obj:                 &unstructured.Unstructured{Object: map[string]interface{}{"apiVersion": "test/v4", "kind": "Foo", "numArray": []interface{}{1, 2}, "status": map[string]interface{}{"phase": "ready"}, "metadata": map[string]interface{}{"resourceVersion": "1"}}},
+			version:             3,
+			hasStructuralSchema: false,
+			isValid:             true,
+		},
+	}
+
+	for _, tc := range tcs {
+		strategy := statusStrategy{}
+		kind := schema.GroupVersionKind{
+			Version: crd.Spec.Versions[tc.version].Name,
+			Kind:    crd.Spec.Names.Kind,
+			Group:   crd.Spec.Group,
+		}
+		strategy.customResourceStrategy.validator.kind = kind
+		if tc.hasStructuralSchema {
+			ss, _ := structuralschema.NewStructural(crd.Spec.Versions[tc.version].Schema.OpenAPIV3Schema)
+			strategy.structuralSchema = ss
+		}
+		t.Logf("case: %v", tc.name)
+		errs := strategy.ValidateUpdate(ctx, tc.obj, tc.old)
+		if tc.isValid && len(errs) > 0 {
+			t.Errorf("%v: unexpected error: %v", tc.name, errs)
+		}
+		if !tc.isValid && len(errs) == 0 {
+			t.Errorf("%v: unexpected non-error", tc.name)
+		}
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestStatusStrategyValidateUpdateForLegacyV1beta1"]
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
