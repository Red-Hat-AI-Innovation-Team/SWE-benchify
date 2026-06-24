#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/podcertificate/podcertificatemanager.go b/pkg/kubelet/podcertificate/podcertificatemanager.go
index 7765b0fb42676..9d0048c8499ec 100644
--- a/pkg/kubelet/podcertificate/podcertificatemanager.go
+++ b/pkg/kubelet/podcertificate/podcertificatemanager.go
@@ -760,7 +760,7 @@ func (m *IssuingManager) createPodCertificateRequest(
 			GenerateName: "req-",
 			OwnerReferences: []metav1.OwnerReference{
 				{
-					APIVersion: "core/v1",
+					APIVersion: "v1",
 					Kind:       "Pod",
 					Name:       podName,
 					UID:        podUID,
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
