#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux.go b/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux.go
index 5b1f2f5aa0530..8a78f874cb94b 100644
--- a/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux.go
+++ b/pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux.go
@@ -27,6 +27,7 @@ import (
 	"time"
 
 	v1 "k8s.io/api/core/v1"
+	"k8s.io/apimachinery/pkg/util/wait"
 	utilfeature "k8s.io/apiserver/pkg/util/feature"
 	"k8s.io/client-go/tools/record"
 	"k8s.io/klog/v2"
@@ -191,15 +192,38 @@ func (m *managerImpl) start() (chan struct{}, error) {
 			return nil, err
 		}
 
-		// Read the current inhibitDelay again, if the override was successful, currentInhibitDelay will be equal to shutdownGracePeriodRequested.
-		updatedInhibitDelay, err := m.dbusCon.CurrentInhibitDelay()
+		// The ReloadLogindConf call is asynchronous. Poll with exponential backoff until the configuration is updated.
+		backoff := wait.Backoff{
+			Duration: 100 * time.Millisecond,
+			Factor:   2.0,
+			Steps:    5,
+		}
+		var updatedInhibitDelay time.Duration
+		attempt := 0
+		err = wait.ExponentialBackoff(backoff, func() (bool, error) {
+			attempt += 1
+			// Read the current inhibitDelay again, if the override was successful, currentInhibitDelay will be equal to shutdownGracePeriodRequested.
+			updatedInhibitDelay, err = m.dbusCon.CurrentInhibitDelay()
+			if err != nil {
+				return false, err
+			}
+			if periodRequested <= updatedInhibitDelay {
+				return true, nil
+			}
+			if attempt < backoff.Steps {
+				m.logger.V(3).Info("InhibitDelayMaxSec still less than requested, retrying", "attempt", attempt, "current", updatedInhibitDelay, "requested", periodRequested)
+			}
+			return false, nil
+		})
 		if err != nil {
-			return nil, err
+			if !wait.Interrupted(err) {
+				return nil, err
+			}
+			if periodRequested > updatedInhibitDelay {
+				return nil, fmt.Errorf("node shutdown manager was timed out after %d attempts waiting for logind InhibitDelayMaxSec to update to %v (ShutdownGracePeriod), current value is %v", attempt, periodRequested, updatedInhibitDelay)
+			}
 		}
 
-		if periodRequested > updatedInhibitDelay {
-			return nil, fmt.Errorf("node shutdown manager was unable to update logind InhibitDelayMaxSec to %v (ShutdownGracePeriod), current value of InhibitDelayMaxSec (%v) is less than requested ShutdownGracePeriod", periodRequested, updatedInhibitDelay)
-		}
 	}
 
 	err = m.acquireInhibitLock()
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
