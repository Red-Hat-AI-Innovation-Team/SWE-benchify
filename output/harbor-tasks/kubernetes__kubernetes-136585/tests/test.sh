#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/apis/batch/validation/validation_test.go b/pkg/apis/batch/validation/validation_test.go
index 3bf0791852db1..63b36dd86e386 100644
--- a/pkg/apis/batch/validation/validation_test.go
+++ b/pkg/apis/batch/validation/validation_test.go
@@ -21,6 +21,7 @@ import (
 	"fmt"
 	"strings"
 	"testing"
+	"time"
 	_ "time/tzdata"
 
 	"github.com/google/go-cmp/cmp"
@@ -2583,12 +2584,16 @@ func TestValidateJobUpdate(t *testing.T) {
 }
 
 func TestValidateJobUpdateStatus(t *testing.T) {
+	now := time.Now()
+
 	cases := map[string]struct {
 		opts JobStatusValidationOptions
 
 		old      batch.Job
 		update   batch.Job
 		wantErrs field.ErrorList
+
+		cmpopts cmp.Options
 	}{
 		"valid": {
 			old: batch.Job{
@@ -2680,6 +2685,7 @@ func TestValidateJobUpdateStatus(t *testing.T) {
 				{Type: field.ErrorTypeInvalid, Field: "status.ready"},
 				{Type: field.ErrorTypeInvalid, Field: "status.terminating"},
 			},
+			cmpopts: cmp.Options{ignoreErrValueDetail},
 		},
 		"empty and duplicated uncounted pods": {
 			old: batch.Job{
@@ -2709,12 +2715,105 @@ func TestValidateJobUpdateStatus(t *testing.T) {
 				{Type: field.ErrorTypeDuplicate, Field: "status.uncountedTerminatedPods.failed[3]"},
 				{Type: field.ErrorTypeInvalid, Field: "status.uncountedTerminatedPods.failed[4]"},
 			},
+			cmpopts: cmp.Options{ignoreErrValueDetail},
+		},
+		"immutable startTime for unsuspended job: with non-nil startTime": {
+			opts: JobStatusValidationOptions{
+				RejectStartTimeUpdateForUnsuspendedJob: true,
+			},
+			old: batch.Job{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:            "abc",
+					Namespace:       metav1.NamespaceDefault,
+					ResourceVersion: "1",
+				},
+				Spec: batch.JobSpec{
+					Suspend: ptr.To(false),
+				},
+				Status: batch.JobStatus{
+					StartTime: &metav1.Time{
+						Time: now,
+					},
+					Active: 1,
+				},
+			},
+			update: batch.Job{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:            "abc",
+					Namespace:       metav1.NamespaceDefault,
+					ResourceVersion: "1",
+				},
+				Spec: batch.JobSpec{
+					Suspend: ptr.To(false),
+				},
+				Status: batch.JobStatus{
+					StartTime: &metav1.Time{
+						Time: now.Add(time.Second), // Attempt to change startTime
+					},
+					Active: 1,
+				},
+			},
+			wantErrs: field.ErrorList{
+				{
+					Type:  field.ErrorTypeInvalid,
+					Field: "status.startTime",
+					BadValue: &metav1.Time{
+						Time: now.Add(time.Second),
+					},
+					Detail: "field is immutable for unsuspended job once set",
+				},
+			},
+			cmpopts: cmp.Options{cmpopts.IgnoreFields(field.Error{}, "Origin")},
+		},
+		"immutable startTime for unsuspended job: with nil startTime": {
+			opts: JobStatusValidationOptions{
+				RejectStartTimeUpdateForUnsuspendedJob: true,
+			},
+			old: batch.Job{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:            "abc",
+					Namespace:       metav1.NamespaceDefault,
+					ResourceVersion: "1",
+				},
+				Spec: batch.JobSpec{
+					Suspend: ptr.To(false),
+				},
+				Status: batch.JobStatus{
+					StartTime: &metav1.Time{
+						Time: now,
+					},
+					Active: 1,
+				},
+			},
+			update: batch.Job{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:            "abc",
+					Namespace:       metav1.NamespaceDefault,
+					ResourceVersion: "1",
+				},
+				Spec: batch.JobSpec{
+					Suspend: ptr.To(false),
+				},
+				Status: batch.JobStatus{
+					StartTime: nil,
+					Active:    1,
+				},
+			},
+			wantErrs: field.ErrorList{
+				{
+					Type:     field.ErrorTypeInvalid,
+					Field:    "status.startTime",
+					BadValue: (*metav1.Time)(nil),
+					Detail:   "field is immutable for unsuspended job once set",
+				},
+			},
+			cmpopts: cmp.Options{cmpopts.IgnoreFields(field.Error{}, "Origin")},
 		},
 	}
 	for name, tc := range cases {
 		t.Run(name, func(t *testing.T) {
 			errs := ValidateJobUpdateStatus(&tc.update, &tc.old, tc.opts)
-			if diff := cmp.Diff(tc.wantErrs, errs, ignoreErrValueDetail); diff != "" {
+			if diff := cmp.Diff(tc.wantErrs, errs, tc.cmpopts); diff != "" {
 				t.Errorf("Unexpected errors (-want,+got):\n%s", diff)
 			}
 		})
diff --git a/pkg/registry/batch/job/strategy_test.go b/pkg/registry/batch/job/strategy_test.go
index deafa30ef5c12..1b7aa1585585e 100644
--- a/pkg/registry/batch/job/strategy_test.go
+++ b/pkg/registry/batch/job/strategy_test.go
@@ -2844,7 +2844,7 @@ func TestStatusStrategy_ValidateUpdate(t *testing.T) {
 				},
 			},
 			wantErrs: field.ErrorList{
-				{Type: field.ErrorTypeRequired, Field: "status.startTime"},
+				{Type: field.ErrorTypeInvalid, Field: "status.startTime"},
 			},
 		},
 		"verify startTime cannot be updated for unsuspended job": {
@@ -2862,7 +2862,7 @@ func TestStatusStrategy_ValidateUpdate(t *testing.T) {
 				},
 			},
 			wantErrs: field.ErrorList{
-				{Type: field.ErrorTypeRequired, Field: "status.startTime"},
+				{Type: field.ErrorTypeInvalid, Field: "status.startTime"},
 			},
 		},
 		"verify startTime can be updated when resuming job (JobSuspended: True -> False)": {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/apis/batch/validation/... ./pkg/registry/batch/job/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestStatusStrategy_ValidateUpdate", "TestValidateJobUpdateStatus"]

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
