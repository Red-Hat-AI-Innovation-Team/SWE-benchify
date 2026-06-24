#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/apis/batch/validation/validation.go b/pkg/apis/batch/validation/validation.go
index a11886703d47a..9209f699483aa 100644
--- a/pkg/apis/batch/validation/validation.go
+++ b/pkg/apis/batch/validation/validation.go
@@ -741,7 +741,7 @@ func ValidateJobStatusUpdate(job, oldJob *batch.Job, opts JobStatusValidationOpt
 		// Note that we check `oldJob.Status.StartTime != nil` to allow transitioning from
 		// startTime = nil to startTime != nil for unsuspended jobs, which is a desired transition.
 		if oldJob.Status.StartTime != nil && !ptr.Equal(oldJob.Status.StartTime, job.Status.StartTime) && !ptr.Deref(job.Spec.Suspend, false) {
-			allErrs = append(allErrs, field.Required(statusFld.Child("startTime"), "startTime cannot be removed for unsuspended job"))
+			allErrs = append(allErrs, field.Invalid(statusFld.Child("startTime"), job.Status.StartTime, "field is immutable for unsuspended job once set"))
 		}
 	}
 	if isJobSuccessCriteriaMet(oldJob) && !isJobSuccessCriteriaMet(job) {
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
