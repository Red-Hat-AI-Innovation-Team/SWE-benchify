#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go b/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go
index c3c1d9be176c1..07180630b8d33 100644
--- a/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go
+++ b/staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go
@@ -306,18 +306,30 @@ func (le *LeaderElector) renew(ctx context.Context) {
 
 // release attempts to release the leader lease if we have acquired it.
 func (le *LeaderElector) release() bool {
+	ctx := context.Background()
+	timeoutCtx, timeoutCancel := context.WithTimeout(ctx, le.config.RenewDeadline)
+	defer timeoutCancel()
+	// update the resourceVersion of lease
+	oldLeaderElectionRecord, _, err := le.config.Lock.Get(timeoutCtx)
+	if err != nil {
+		if !errors.IsNotFound(err) {
+			klog.Errorf("error retrieving resource lock %v: %v", le.config.Lock.Describe(), err)
+			return false
+		}
+		klog.Infof("lease lock not found: %v", le.config.Lock.Describe())
+		return false
+	}
+
 	if !le.IsLeader() {
 		return true
 	}
 	now := metav1.NewTime(le.clock.Now())
 	leaderElectionRecord := rl.LeaderElectionRecord{
-		LeaderTransitions:    le.observedRecord.LeaderTransitions,
+		LeaderTransitions:    oldLeaderElectionRecord.LeaderTransitions,
 		LeaseDurationSeconds: 1,
 		RenewTime:            now,
 		AcquireTime:          now,
 	}
-	timeoutCtx, timeoutCancel := context.WithTimeout(context.Background(), le.config.RenewDeadline)
-	defer timeoutCancel()
 	if err := le.config.Lock.Update(timeoutCtx, leaderElectionRecord); err != nil {
 		klog.Errorf("Failed to release lock: %v", err)
 		return false
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
