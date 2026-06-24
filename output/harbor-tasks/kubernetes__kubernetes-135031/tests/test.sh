#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/config/common_test.go b/pkg/kubelet/config/common_test.go
index 19e26814d62be..8d60d269cad77 100644
--- a/pkg/kubelet/config/common_test.go
+++ b/pkg/kubelet/config/common_test.go
@@ -28,13 +28,16 @@ import (
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
 	"k8s.io/apimachinery/pkg/runtime"
 	"k8s.io/apimachinery/pkg/types"
+	utilfeature "k8s.io/apiserver/pkg/util/feature"
 	clientscheme "k8s.io/client-go/kubernetes/scheme"
+	featuregatetesting "k8s.io/component-base/featuregate/testing"
 	"k8s.io/klog/v2"
 	"k8s.io/klog/v2/ktesting"
 	"k8s.io/kubernetes/pkg/api/legacyscheme"
 	podtest "k8s.io/kubernetes/pkg/api/pod/testing"
 	"k8s.io/kubernetes/pkg/apis/core"
 	"k8s.io/kubernetes/pkg/apis/core/validation"
+	"k8s.io/kubernetes/pkg/features"
 	"k8s.io/kubernetes/pkg/securitycontext"
 	"k8s.io/utils/ptr"
 )
@@ -242,6 +245,45 @@ func TestDecodeSinglePodRejectsResourceClaims(t *testing.T) {
 	}
 }
 
+func TestDecodeSinglePodWithOptions(t *testing.T) {
+	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.ContainerRestartRules, true)
+	logger, _ := ktesting.NewTestContext(t)
+	restartPolicyAlways := v1.ContainerRestartPolicyAlways
+	pod := &v1.Pod{
+		TypeMeta: metav1.TypeMeta{
+			APIVersion: "",
+		},
+		ObjectMeta: metav1.ObjectMeta{
+			Name:      "test",
+			UID:       "12345",
+			Namespace: "mynamespace",
+		},
+		Spec: v1.PodSpec{
+			RestartPolicy: v1.RestartPolicyNever,
+			Containers: []v1.Container{{
+				Name:                     "image",
+				Image:                    "test/image",
+				ImagePullPolicy:          "IfNotPresent",
+				TerminationMessagePath:   "/dev/termination-log",
+				TerminationMessagePolicy: v1.TerminationMessageReadFile,
+				SecurityContext:          securitycontext.ValidSecurityContextWithContainerDefaults(),
+				RestartPolicy:            &restartPolicyAlways,
+			}},
+		},
+	}
+	json, err := runtime.Encode(clientscheme.Codecs.LegacyCodec(v1.SchemeGroupVersion), pod)
+	if err != nil {
+		t.Errorf("unexpected error: %v", err)
+	}
+	parsed, _, err := tryDecodeSinglePod(logger, json, noDefault)
+	if err != nil {
+		t.Errorf("unexpected error: %v (%s)", err, string(json))
+	}
+	if !parsed {
+		t.Errorf("expected to have parsed file: (%s)", string(json))
+	}
+}
+
 func TestDecodePodList(t *testing.T) {
 	logger, _ := ktesting.NewTestContext(t)
 	grace := int64(30)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestDecodeSinglePodWithOptions"]

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
