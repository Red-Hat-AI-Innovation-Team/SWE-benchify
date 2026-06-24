#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/internal/xds/resolver/xds_resolver.go b/internal/xds/resolver/xds_resolver.go
index 70ba351ca9e5..3d4932bc29cd 100644
--- a/internal/xds/resolver/xds_resolver.go
+++ b/internal/xds/resolver/xds_resolver.go
@@ -415,9 +415,26 @@ func (r *xdsResolver) newConfigSelector() (_ *configSelector, err error) {
 	for i, rt := range r.xdsConfig.VirtualHost.Routes {
 		clusters := rinternal.NewWRR.(func() wrr.WRR)()
 		interceptors := []iresolver.ClientInterceptor{}
+		// TODO: Carve out the common logic between the ClusterSpecifierPlugin
+		// and WeightedClusters.
 		if rt.ClusterSpecifierPlugin != "" {
 			clusterName := clusterSpecifierPluginPrefix + rt.ClusterSpecifierPlugin
-			clusters.Add(&routeCluster{name: clusterName}, 1)
+			interceptor, err := r.newInterceptor(r.xdsConfig.Listener.APIListener.HTTPFilters, nil, rt.HTTPFilterConfigOverride, r.xdsConfig.VirtualHost.HTTPFilterConfigOverride)
+			if err != nil {
+				// Clean up any interceptors that were successfully built
+				// for the current route before this error occurred. Note
+				// that this is not handled by the call to cs.stop() in the
+				// deferred function.
+				for _, i := range interceptors {
+					i.Close()
+				}
+				return nil, err
+			}
+			clusters.Add(&routeCluster{
+				name:        clusterName,
+				interceptor: interceptor,
+			}, 1)
+			interceptors = append(interceptors, interceptor)
 			ci := r.addOrGetActiveClusterInfo(clusterName, "")
 			ci.cfg = xdsChildConfig{ChildPolicy: balancerConfig(r.xdsConfig.RouteConfig.ClusterSpecifierPlugins[rt.ClusterSpecifierPlugin])}
 			cs.plugins[clusterName] = ci
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
