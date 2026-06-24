#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement.go b/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement.go
index 44a5ddcc5e417..81e4899f0850d 100644
--- a/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement.go
+++ b/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement.go
@@ -106,10 +106,22 @@ func (s *APIEnablementOptions) ApplyTo(c *server.Config, defaultResourceConfig *
 
 	c.MergedResourceConfig = mergedResourceConfig
 
-	if binVersion, emulatedVersion := c.EffectiveVersion.BinaryVersion(), c.EffectiveVersion.EmulationVersion(); !binVersion.EqualTo(emulatedVersion) {
+	binVersion, emulatedVersion := c.EffectiveVersion.BinaryVersion(), c.EffectiveVersion.EmulationVersion()
+	if binVersion != nil && emulatedVersion != nil && (binVersion.Major() != emulatedVersion.Major() || binVersion.Minor() != emulatedVersion.Minor()) {
 		for _, version := range registry.PrioritizedVersionsAllGroups() {
 			if strings.Contains(version.Version, "alpha") {
-				klog.Warningf("alpha api enabled with emulated version %s instead of the binary's version %s, this is unsupported, proceed at your own risk: api=%s", emulatedVersion, binVersion, version.String())
+				// Check if this alpha API is actually enabled before warning
+				entireVersionEnabled := c.MergedResourceConfig.ExplicitGroupVersionConfigs[version]
+				individualResourceEnabled := false
+				for resource, enabled := range c.MergedResourceConfig.ExplicitResourceConfigs {
+					if enabled && resource.Group == version.Group && resource.Version == version.Version {
+						individualResourceEnabled = true
+						break
+					}
+				}
+				if entireVersionEnabled || individualResourceEnabled {
+					klog.Warningf("alpha api enabled with emulated version %s instead of the binary's version %s, this is unsupported, proceed at your own risk: api=%s", emulatedVersion, binVersion, version.String())
+				}
 			}
 		}
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
