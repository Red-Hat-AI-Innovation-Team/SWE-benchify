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
go test -json -count=1 ./staging/src/k8s.io/apiserver/pkg/endpoints/filters/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestAudit"]
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
