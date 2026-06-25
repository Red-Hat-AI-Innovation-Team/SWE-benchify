#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion_test.go b/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion_test.go
index 03bf42a9cfdc1..15a4fe473ae13 100644
--- a/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion_test.go
+++ b/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion_test.go
@@ -19,10 +19,13 @@ package fake
 import (
 	"bytes"
 	"context"
+	"errors"
 	"io"
+	"strings"
 	"testing"
 
 	corev1 "k8s.io/api/core/v1"
+	"k8s.io/apimachinery/pkg/runtime"
 	cgtesting "k8s.io/client-go/testing"
 )
 
@@ -46,3 +49,74 @@ func TestFakePodsGetLogs(t *testing.T) {
 		t.Fatal("Close response body:", err)
 	}
 }
+
+func TestFakePodsGetLogsReactorError(t *testing.T) {
+	fake := &cgtesting.Fake{}
+	fp := newFakePods(&FakeCoreV1{Fake: fake}, "default")
+	expectedErr := errors.New("reactor get logs failure")
+	fake.PrependReactor("get", "pods/log", func(action cgtesting.Action) (bool, runtime.Object, error) {
+		genericAction, ok := action.(cgtesting.GenericAction)
+		if !ok {
+			t.Fatalf("expected GenericAction, got %T", action)
+		}
+		opts, ok := genericAction.GetValue().(*corev1.PodLogOptions)
+		if !ok {
+			t.Fatalf("expected *corev1.PodLogOptions, got %T", genericAction.GetValue())
+		}
+		if opts.Container != "ctr" {
+			t.Fatalf("expected container ctr, got %q", opts.Container)
+		}
+		return true, nil, expectedErr
+	})
+
+	req := fp.GetLogs("foo", &corev1.PodLogOptions{Container: "ctr"})
+	_, err := req.Stream(context.Background())
+	if !errors.Is(err, expectedErr) {
+		t.Fatalf("expected stream error %v, got %v", expectedErr, err)
+	}
+}
+
+func TestFakePodsGetLogsReactorResponse(t *testing.T) {
+	fake := &cgtesting.Fake{}
+	fp := newFakePods(&FakeCoreV1{Fake: fake}, "default")
+	expectedLogs := "reactor logs"
+	fake.PrependReactor("get", "pods/log", func(action cgtesting.Action) (bool, runtime.Object, error) {
+		return true, &runtime.Unknown{Raw: []byte(expectedLogs)}, nil
+	})
+
+	req := fp.GetLogs("foo", &corev1.PodLogOptions{})
+	body, err := req.Stream(context.Background())
+	if err != nil {
+		t.Fatalf("Stream pod logs: %v", err)
+	}
+	defer func() {
+		if err := body.Close(); err != nil {
+			t.Fatalf("Close response body: %v", err)
+		}
+	}()
+
+	logs, err := io.ReadAll(body)
+	if err != nil {
+		t.Fatalf("Read pod logs: %v", err)
+	}
+	if string(logs) != expectedLogs {
+		t.Fatalf("expected logs %q, got %q", expectedLogs, string(logs))
+	}
+}
+
+func TestFakePodsGetLogsReactorInvalidObject(t *testing.T) {
+	fake := &cgtesting.Fake{}
+	fp := newFakePods(&FakeCoreV1{Fake: fake}, "default")
+	fake.PrependReactor("get", "pods/log", func(action cgtesting.Action) (bool, runtime.Object, error) {
+		return true, &corev1.Pod{}, nil
+	})
+
+	req := fp.GetLogs("foo", &corev1.PodLogOptions{})
+	_, err := req.Stream(context.Background())
+	if err == nil {
+		t.Fatal("expected stream error")
+	}
+	if !strings.Contains(err.Error(), "expected reactor to return *runtime.Unknown") {
+		t.Fatalf("expected helpful reactor object type error, got: %v", err)
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
f2p = ["TestFakePodsGetLogsReactorError", "TestFakePodsGetLogsReactorInvalidObject", "TestFakePodsGetLogsReactorResponse"]

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
