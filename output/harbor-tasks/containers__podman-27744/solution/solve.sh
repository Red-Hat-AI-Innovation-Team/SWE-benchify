#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/libpod/container.go b/libpod/container.go
index 6e94bbd4cb0..65cf7604378 100644
--- a/libpod/container.go
+++ b/libpod/container.go
@@ -1321,7 +1321,20 @@ func (c *Container) HostNetwork() bool {
 // HasHealthCheck returns bool as to whether there is a health check
 // defined for the container
 func (c *Container) HasHealthCheck() bool {
-	return c.config.HealthCheckConfig != nil
+	// Consider a healthcheck present only when a HealthCheckConfig exists
+	// and the Test field contains a meaningful command. Treat an empty
+	// Test slice or the special ["NONE"] sentinel as "no healthcheck".
+	if c.config.HealthCheckConfig == nil {
+		return false
+	}
+	test := c.config.HealthCheckConfig.Test
+	if len(test) == 0 {
+		return false
+	}
+	if len(test) == 1 && strings.ToUpper(test[0]) == define.HealthConfigTestNone {
+		return false
+	}
+	return true
 }
 
 // HealthCheckConfig returns the command and timing attributes of the health check
diff --git a/libpod/container_inspect.go b/libpod/container_inspect.go
index 9e9e9977f17..b6e08259bef 100644
--- a/libpod/container_inspect.go
+++ b/libpod/container_inspect.go
@@ -192,10 +192,7 @@ func (c *Container) getContainerInspectData(size bool, driverData *define.Driver
 		data.OCIConfigPath = c.state.ConfigPath
 	}
 
-	// Check if healthcheck is not nil and --no-healthcheck option is not set.
-	// If --no-healthcheck is set Test will be always set to `[NONE]`, so the
-	// inspect status should be set to nil.
-	if c.config.HealthCheckConfig != nil && (len(c.config.HealthCheckConfig.Test) != 1 || c.config.HealthCheckConfig.Test[0] != "NONE") {
+	if c.HasHealthCheck() {
 		// This container has a healthcheck defined in it; we need to add its state
 		healthCheckState, err := c.readHealthCheckLog()
 		if err != nil {
diff --git a/libpod/container_internal.go b/libpod/container_internal.go
index fe33b5a5af3..671d7086b59 100644
--- a/libpod/container_internal.go
+++ b/libpod/container_internal.go
@@ -1310,10 +1310,7 @@ func (c *Container) start() error {
 		}
 	}
 
-	// Check if healthcheck is not nil and --no-healthcheck option is not set.
-	// If --no-healthcheck is set Test will be always set to `[NONE]` so no need
-	// to update status in such case.
-	if c.config.HealthCheckConfig != nil && (len(c.config.HealthCheckConfig.Test) != 1 || c.config.HealthCheckConfig.Test[0] != "NONE") {
+	if c.HasHealthCheck() {
 		if err := c.updateHealthStatus(define.HealthCheckStarting); err != nil {
 			return fmt.Errorf("update healthcheck status: %w", err)
 		}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
