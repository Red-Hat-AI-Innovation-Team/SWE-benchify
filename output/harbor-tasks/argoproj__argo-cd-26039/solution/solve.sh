#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/util/healthz/healthz.go b/util/healthz/healthz.go
index 921facea97c2a..1b677906e3ef0 100644
--- a/util/healthz/healthz.go
+++ b/util/healthz/healthz.go
@@ -3,6 +3,7 @@ package healthz
 import (
 	"fmt"
 	"net/http"
+	"time"
 
 	log "github.com/sirupsen/logrus"
 )
@@ -11,9 +12,13 @@ import (
 // ServeHealthCheck relies on the provided function to return an error if unhealthy and nil otherwise.
 func ServeHealthCheck(mux *http.ServeMux, f func(r *http.Request) error) {
 	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
+		startTs := time.Now()
 		if err := f(r); err != nil {
 			w.WriteHeader(http.StatusServiceUnavailable)
-			log.Errorln(w, err)
+			log.WithFields(log.Fields{
+				"duration":  time.Since(startTs),
+				"component": "healthcheck",
+			}).WithError(err).Error("Error serving health check request")
 		} else {
 			fmt.Fprintln(w, "ok")
 		}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
