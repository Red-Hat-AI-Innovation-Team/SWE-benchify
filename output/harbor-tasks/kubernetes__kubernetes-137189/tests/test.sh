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
go test -json -count=1 ./staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestFakePodsGetLogsReactorError", "TestFakePodsGetLogsReactorInvalidObject", "TestFakePodsGetLogsReactorResponse"]
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
