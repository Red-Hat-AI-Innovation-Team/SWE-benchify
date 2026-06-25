#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit_test.go b/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit_test.go
index e2e77ac3742bd..03bac7a07b343 100644
--- a/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit_test.go
+++ b/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit_test.go
@@ -23,6 +23,7 @@ import (
 	"net/http/httptest"
 	"net/url"
 	"reflect"
+	"regexp"
 	"sync"
 	"testing"
 	"time"
@@ -224,7 +225,7 @@ func TestAudit(t *testing.T) {
 	shortRunningPath := "/api/v1/namespaces/default/pods/foo"
 	longRunningPath := "/api/v1/namespaces/default/pods?watch=true"
 
-	delay := 500 * time.Millisecond
+	delay := 501 * time.Millisecond
 
 	for _, test := range []struct {
 		desc       string
@@ -351,6 +352,10 @@ func TestAudit(t *testing.T) {
 					Verb:           "update",
 					RequestURI:     shortRunningPath,
 					ResponseStatus: &metav1.Status{Code: 200},
+					Annotations: map[string]string{
+						"apiserver.latency.k8s.io/response-write": "^[0-9.]+[µnm]s$",
+						"apiserver.latency.k8s.io/total":          "^[0-9.]+[µnm]s$",
+					},
 				},
 			},
 			true,
@@ -713,6 +718,7 @@ func TestAudit(t *testing.T) {
 				// simplified long-running check
 				return ri.Verb == "watch"
 			})
+			handler = WithLatencyTrackers(handler)
 			handler = WithAuditInit(handler)
 
 			req, _ := http.NewRequestWithContext(ctx, test.verb, test.path, nil)
@@ -772,6 +778,19 @@ func TestAudit(t *testing.T) {
 				if (event.ResponseStatus != nil) && (event.ResponseStatus.Code != expect.ResponseStatus.Code) {
 					t.Errorf("Unexpected status code : %d", event.ResponseStatus.Code)
 				}
+
+				for k, v := range expect.Annotations {
+					if actual, exists := event.Annotations[k]; !exists {
+						t.Errorf("Expect key %s in the annotations but it does not exist", k)
+					} else if matched, _ := regexp.MatchString(v, actual); !matched {
+						t.Errorf("Annotation %s value %q does not match regex %q", k, actual, v)
+					}
+				}
+				for k := range event.Annotations {
+					if _, exists := expect.Annotations[k]; !exists {
+						t.Errorf("Unexpected key %s in the annotations", k)
+					}
+				}
 			}
 		})
 	}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestAudit"]

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
