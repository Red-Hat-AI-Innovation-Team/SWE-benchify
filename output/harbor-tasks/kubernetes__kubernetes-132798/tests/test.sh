#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation_test.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation_test.go
index ea82e9a4fb086..60131b9b26742 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation_test.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation_test.go
@@ -2696,8 +2696,8 @@ func TestValidationExpressionsAtSchemaLevels(t *testing.T) {
 				},
 			},
 			errors: []string{
-				`root.myProperty[key]: Invalid value: "string": must be value2 or not value`,
-				`root.myProperty[key2]: Invalid value: "string": len must be 5`,
+				`root.myProperty[key]: Invalid value: "value": must be value2 or not value`,
+				`root.myProperty[key2]: Invalid value: "value2": len must be 5`,
 			},
 			schema: &schema.Structural{
 				Generic: schema.Generic{
@@ -2742,8 +2742,8 @@ func TestValidationExpressionsAtSchemaLevels(t *testing.T) {
 				"key2": "value2",
 			},
 			errors: []string{
-				`root.key: Invalid value: "string": must be value2 or not value`,
-				`root.key2: Invalid value: "string": len must be 5`,
+				`root.key: Invalid value: "value": must be value2 or not value`,
+				`root.key2: Invalid value: "value2": len must be 5`,
 			},
 			schema: &schema.Structural{
 				Generic: schema.Generic{
@@ -3924,7 +3924,7 @@ func TestRatcheting(t *testing.T) {
 						type: string
 						x-kubernetes-validations:
 						- rule: self == "bar"
-						  message: "gotta be baz"
+						  message: "gotta be bar"
 				`),
 			oldObj: mustUnstructured(`
 				foo: baz
@@ -3933,7 +3933,7 @@ func TestRatcheting(t *testing.T) {
 				foo: baz
 			`),
 			warnings: []string{
-				`root.foo: Invalid value: "string": gotta be baz`,
+				`root.foo: Invalid value: "baz": gotta be bar`,
 			},
 		},
 		{
@@ -3960,7 +3960,7 @@ func TestRatcheting(t *testing.T) {
 				- bar: bar
 			`),
 			warnings: []string{
-				`root[0].bar: Invalid value: "string": gotta be baz`,
+				`root[0].bar: Invalid value: "bar": gotta be baz`,
 			},
 		},
 		{
@@ -3986,7 +3986,7 @@ func TestRatcheting(t *testing.T) {
 				- 2
 			`),
 			warnings: []string{
-				`root[1]: Invalid value: "number": gotta be odd`,
+				`root[1]: Invalid value: 2: gotta be odd`,
 			},
 		},
 		{
@@ -4020,7 +4020,7 @@ func TestRatcheting(t *testing.T) {
 				- 2
 			`),
 			warnings: []string{
-				`root.setArray[2]: Invalid value: "number": gotta be odd`,
+				`root.setArray[2]: Invalid value: 2: gotta be odd`,
 			},
 		},
 		{
@@ -4055,8 +4055,8 @@ func TestRatcheting(t *testing.T) {
 				  value: baz
 			`),
 			warnings: []string{
-				`root[0].value: Invalid value: "string": gotta be baz`,
-				`root[1].value: Invalid value: "string": gotta be baz`,
+				`root[0].value: Invalid value: "notbaz": gotta be baz`,
+				`root[1].value: Invalid value: "notbaz": gotta be baz`,
 			},
 		},
 		{
@@ -4089,7 +4089,7 @@ func TestRatcheting(t *testing.T) {
 				  value: notbaz
 			`),
 			warnings: []string{
-				`root[1].value: Invalid value: "string": gotta be baz`,
+				`root[1].value: Invalid value: "notbaz": gotta be baz`,
 			},
 		},
 		{
@@ -4131,8 +4131,8 @@ func TestRatcheting(t *testing.T) {
 						bar: notbaz
 			`),
 			warnings: []string{
-				`root.mapField.foo: Invalid value: "string": gotta be baz`,
-				`root.mapField.mapField.bar: Invalid value: "string": gotta be nested baz`,
+				`root.mapField.foo: Invalid value: "notbaz": gotta be baz`,
+				`root.mapField.mapField.bar: Invalid value: "notbaz": gotta be nested baz`,
 			},
 		},
 		{
@@ -4182,11 +4182,11 @@ func TestRatcheting(t *testing.T) {
 			`),
 			errors: []string{
 				// Didn'"'"'t get ratcheted because we changed its value from baz to notbaz
-				`root.mapField.foo: Invalid value: "string": gotta be baz`,
+				`root.mapField.foo: Invalid value: "notbaz": gotta be baz`,
 			},
 			warnings: []string{
 				// Ratcheted because its value remained the same, even though it is invalid
-				`root.mapField.mapField.bar: Invalid value: "string": gotta be baz`,
+				`root.mapField.mapField.bar: Invalid value: "notbaz": gotta be baz`,
 			},
 		},
 		{
@@ -4219,7 +4219,7 @@ func TestRatcheting(t *testing.T) {
 				- bar: bar
 			`),
 			warnings: []string{
-				`root.atomicArray[0].bar: Invalid value: "string": gotta be baz`,
+				`root.atomicArray[0].bar: Invalid value: "bar": gotta be baz`,
 			},
 		},
 		{
@@ -4247,7 +4247,7 @@ func TestRatcheting(t *testing.T) {
 				- bar: baz
 			`),
 			errors: []string{
-				`root[0].bar: Invalid value: "string": gotta be baz`,
+				`root[0].bar: Invalid value: "bar": gotta be baz`,
 			},
 		},
 		{
@@ -4268,7 +4268,7 @@ func TestRatcheting(t *testing.T) {
 				foo: bar
 			`),
 			errors: []string{
-				`root.foo: Invalid value: "string": gotta be baz`,
+				`root.foo: Invalid value: "bar": gotta be baz`,
 			},
 		},
 		{
@@ -4351,8 +4351,8 @@ func TestRatcheting(t *testing.T) {
 				kind: Baz
 			`),
 			errors: []string{
-				`root.apiVersion: Invalid value: "string": failed rule: self == "v1"`,
-				`root.kind: Invalid value: "string": failed rule: self == "Pod"`,
+				`root.apiVersion: Invalid value: "v2": failed rule: self == "v1"`,
+				`root.kind: Invalid value: "Baz": failed rule: self == "Pod"`,
 			},
 		},
 		{
@@ -4420,12 +4420,12 @@ func TestRatcheting(t *testing.T) {
 				  otherField: newValue3
 			`),
 			warnings: []string{
-				`root.subField.apiVersion: Invalid value: "string": failed rule: self == "v1"`,
-				`root.subField.kind: Invalid value: "string": failed rule: self == "Pod"`,
-				`root.list[0].apiVersion: Invalid value: "string": failed rule: self == "v1"`,
-				`root.list[0].kind: Invalid value: "string": failed rule: self == "Pod"`,
-				`root.list[1].apiVersion: Invalid value: "string": failed rule: self == "v1"`,
-				`root.list[1].kind: Invalid value: "string": failed rule: self == "Pod"`,
+				`root.subField.apiVersion: Invalid value: "v2": failed rule: self == "v1"`,
+				`root.subField.kind: Invalid value: "Baz": failed rule: self == "Pod"`,
+				`root.list[0].apiVersion: Invalid value: "v2": failed rule: self == "v1"`,
+				`root.list[0].kind: Invalid value: "Baz": failed rule: self == "Pod"`,
+				`root.list[1].apiVersion: Invalid value: "v3": failed rule: self == "v1"`,
+				`root.list[1].kind: Invalid value: "Bar": failed rule: self == "Pod"`,
 			},
 		},
 	}
diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation_test.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation_test.go
index a35496b00f1a1..ff324c270533b 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation_test.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation_test.go
@@ -463,7 +463,7 @@ func TestValidateCustomResource(t *testing.T) {
 					object:    map[string]interface{}{"field": "y"},
 					oldObject: map[string]interface{}{"field": "x"},
 					expectErrs: []string{
-						`field: Invalid value: "string": failed rule: self == oldSelf`,
+						`field: Invalid value: "y": failed rule: self == oldSelf`,
 					}},
 			},
 		},
@@ -511,7 +511,7 @@ func TestValidateCustomResource(t *testing.T) {
 					object:    map[string]interface{}{"field": []interface{}{map[string]interface{}{"k1": "a", "k2": "b", "v1": 0.9}}},
 					oldObject: map[string]interface{}{"field": []interface{}{map[string]interface{}{"k1": "a", "k2": "b", "v1": 1.0}}},
 					expectErrs: []string{
-						`field[0].v1: Invalid value: "number": failed rule: self >= oldSelf`,
+						`field[0].v1: Invalid value: 0.9: failed rule: self >= oldSelf`,
 					}},
 			},
 		},
@@ -550,7 +550,7 @@ func TestValidateCustomResource(t *testing.T) {
 				{
 					object: map[string]interface{}{"field": []interface{}{map[string]interface{}{"x": "y"}}},
 					expectErrs: []string{
-						`field[0].x: Invalid value: "string": failed rule: self == '"'"'x'"'"'`,
+						`field[0].x: Invalid value: "y": failed rule: self == '"'"'x'"'"'`,
 					}},
 			},
 		},
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestRatcheting", "TestValidateCustomResource", "TestValidationExpressionsAtSchemaLevels"]

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
