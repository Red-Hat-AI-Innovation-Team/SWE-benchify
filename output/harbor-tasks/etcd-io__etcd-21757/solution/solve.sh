#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/traceutil/trace.go b/pkg/traceutil/trace.go
index f89ba83c97cd..121add9b9b0a 100644
--- a/pkg/traceutil/trace.go
+++ b/pkg/traceutil/trace.go
@@ -200,7 +200,6 @@ func (t *Trace) logInfo(threshold time.Duration) (string, []zap.Field) {
 	endTime := time.Now()
 	totalDuration := endTime.Sub(t.startTime)
 	traceNum := rand.Int31()
-	msg := fmt.Sprintf("trace[%d] %s", traceNum, t.operation)
 
 	var steps []string
 	lastStepTime := t.startTime
@@ -228,13 +227,15 @@ func (t *Trace) logInfo(threshold time.Duration) (string, []zap.Field) {
 		}
 		stepDuration := tstep.time.Sub(lastStepTime)
 		if stepDuration > threshold {
-			steps = append(steps, fmt.Sprintf("trace[%d] '%v' %s (duration: %v)",
-				traceNum, tstep.msg, writeFields(tstep.fields), stepDuration))
+			steps = append(steps, fmt.Sprintf("'%v' %s (duration: %v)",
+				tstep.msg, writeFields(tstep.fields), stepDuration))
 		}
 		lastStepTime = tstep.time
 	}
 
 	fs := []zap.Field{
+		zap.Int32("trace_id", traceNum),
+		zap.String("operation", t.operation),
 		zap.String("detail", writeFields(t.fields)),
 		zap.Duration("duration", totalDuration),
 		zap.Time("start", t.startTime),
@@ -242,7 +243,7 @@ func (t *Trace) logInfo(threshold time.Duration) (string, []zap.Field) {
 		zap.Strings("steps", steps),
 		zap.Int("step_count", len(steps)),
 	}
-	return msg, fs
+	return "trace", fs
 }
 
 func (t *Trace) updateFieldIfExist(f Field) bool {
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
