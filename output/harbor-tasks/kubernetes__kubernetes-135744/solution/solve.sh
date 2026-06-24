#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/kubectl/pkg/describe/describe.go b/staging/src/k8s.io/kubectl/pkg/describe/describe.go
index 578bc94c2c558..4d0634760e51a 100644
--- a/staging/src/k8s.io/kubectl/pkg/describe/describe.go
+++ b/staging/src/k8s.io/kubectl/pkg/describe/describe.go
@@ -3025,6 +3025,9 @@ func describeService(service *corev1.Service, endpointSlices []discoveryv1.Endpo
 			} else {
 				w.Write(LEVEL_0, "TargetPort:\t%s/%s\n", sp.TargetPort.StrVal, sp.Protocol)
 			}
+			if sp.AppProtocol != nil {
+				w.Write(LEVEL_0, "AppProtocol:\t%s\n", *sp.AppProtocol)
+			}
 			if sp.NodePort != 0 {
 				w.Write(LEVEL_0, "NodePort:\t%s\t%d/%s\n", name, sp.NodePort, sp.Protocol)
 			}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
