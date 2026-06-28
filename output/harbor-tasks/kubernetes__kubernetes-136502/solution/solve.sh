#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/endpointslice/util/controller_utils.go b/staging/src/k8s.io/endpointslice/util/controller_utils.go
index 2d9a8746a19f3..170bb7e851b44 100644
--- a/staging/src/k8s.io/endpointslice/util/controller_utils.go
+++ b/staging/src/k8s.io/endpointslice/util/controller_utils.go
@@ -159,6 +159,10 @@ type PortMapKey string
 
 // NewPortMapKey generates a PortMapKey from endpoint ports.
 func NewPortMapKey(endpointPorts []discovery.EndpointPort) PortMapKey {
+	// Normalize nil to empty slice so they hash the same.
+	if endpointPorts == nil {
+		endpointPorts = []discovery.EndpointPort{}
+	}
 	sort.Sort(portsInOrder(endpointPorts))
 	return PortMapKey(deepHashObjectToString(endpointPorts))
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
