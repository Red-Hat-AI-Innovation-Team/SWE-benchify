#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit.go b/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit.go
index d25bf35ae3af0..83537bd215e51 100644
--- a/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit.go
+++ b/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit.go
@@ -149,7 +149,6 @@ func evaluatePolicyAndCreateAuditEvent(req *http.Request, policy audit.PolicyRul
 
 // writeLatencyToAnnotation writes the latency incurred in different
 // layers of the apiserver to the annotations of the audit object.
-// it should be invoked after ev.StageTimestamp has been set appropriately.
 func writeLatencyToAnnotation(ctx context.Context) {
 	ac := audit.AuditContextFrom(ctx)
 	// we will track latency in annotation only when the total latency
@@ -157,7 +156,7 @@ func writeLatencyToAnnotation(ctx context.Context) {
 	// traces in rest/handlers for create, delete, update,
 	// get, list, and deletecollection.
 	const threshold = 500 * time.Millisecond
-	latency := ac.GetEventStageTimestamp().Sub(ac.GetEventRequestReceivedTimestamp().Time)
+	latency := time.Since(ac.GetEventRequestReceivedTimestamp().Time)
 	if latency <= threshold {
 		return
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
