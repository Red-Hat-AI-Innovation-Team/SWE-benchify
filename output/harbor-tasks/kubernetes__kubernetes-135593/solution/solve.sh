#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/proxy/endpointslicecache.go b/pkg/proxy/endpointslicecache.go
index 1d1eea4f40a7c..abccefd43dd9f 100644
--- a/pkg/proxy/endpointslicecache.go
+++ b/pkg/proxy/endpointslicecache.go
@@ -232,10 +232,19 @@ func (cache *EndpointSliceCache) addEndpoints(svcPortName *ServicePortName, port
 		endpointInfo := newBaseEndpointInfo(endpointIP, portNum, isLocal,
 			ready, serving, terminating, zoneHints, nodeHints)
 
-		// This logic ensures we're deduplicating potential overlapping endpoints
-		// isLocal should not vary between matching endpoints, but if it does, we
-		// favor a true value here if it exists.
-		if _, exists := endpointSet[endpointInfo.String()]; !exists || isLocal {
+		// If an Endpoint gets moved from one slice to another, we may temporarily
+		// see it in both slices. Ideally we want to prefer the Endpoint from the
+		// more-recently-updated EndpointSlice, since it may have newer
+		// conditions. But we can't easily figure that out, and the situation will
+		// resolve itself once we receive the second EndpointSlice update anyway.
+		//
+		// On the other hand, there maybe also be two *different* Endpoints (i.e.,
+		// with different targetRefs) that point to the same IP, if the pod
+		// network reuses the IP from a terminating pod before the Pod object is
+		// fully deleted. In this case we want to prefer the running pod over the
+		// terminating one. (If there are multiple non-terminating pods with the
+		// same podIP, then the result is undefined.)
+		if _, exists := endpointSet[endpointInfo.String()]; !exists || !terminating {
 			endpointSet[endpointInfo.String()] = cache.makeEndpointInfo(endpointInfo, svcPortName)
 		}
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
