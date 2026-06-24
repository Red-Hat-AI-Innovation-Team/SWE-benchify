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
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestMaxWithNilResourceList"]

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

def parse_junit_xml(text):
    # Minimal XML parser for JUnit format (no lxml dependency)
    results = {}
    for m in re.finditer(r'<testcase[^>]*name="([^"]*)"[^>]*classname="([^"]*)"[^>]*(/?>)', text):
        name, classname, close = m.groups()
        test_id = f"{classname}.{name}"
        # Check for failure/error child elements
        if close == "/>":
            results[test_id] = "passed"
        else:
            # Find the matching </testcase> and check contents
            start = m.end()
            end = text.find("</testcase>", start)
            block = text[start:end] if end != -1 else ""
            if "<failure" in block or "<error" in block:
                results[test_id] = "failed"
            elif "<skipped" in block:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results

def parse_cargo_test(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            test_id = m.group(1)
            status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_tap(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"(ok|not ok)\s+\d+\s*-?\s*(.*)", line)
        if m:
            status = "passed" if m.group(1) == "ok" else "failed"
            desc = m.group(2).strip()
            if "# SKIP" in desc:
                status = "skipped"
                desc = desc.split("# SKIP")[0].strip()
            results[desc] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
    "junit-xml": parse_junit_xml,
    "cargo-test": parse_cargo_test,
    "tap": parse_tap,
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
