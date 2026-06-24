#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion.go b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion.go
index ad85840fc2b33..2289c7993ae53 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion.go
@@ -58,6 +58,7 @@ func Convert_v1beta1_DeviceRequest_To_v1_DeviceRequest(in *resourcev1beta1.Devic
 			tolerations = append(tolerations, toleration)
 		}
 		exactDeviceRequest.Tolerations = tolerations
+		exactDeviceRequest.Capacity = (*resourceapi.CapacityRequirements)(unsafe.Pointer(in.Capacity))
 		out.Exactly = &exactDeviceRequest
 	}
 	return nil
@@ -69,7 +70,8 @@ func hasAnyMainRequestFieldsSet(deviceRequest *resourcev1beta1.DeviceRequest) bo
 		deviceRequest.AllocationMode != "" ||
 		deviceRequest.Count != 0 ||
 		deviceRequest.AdminAccess != nil ||
-		deviceRequest.Tolerations != nil
+		deviceRequest.Tolerations != nil ||
+		deviceRequest.Capacity != nil
 }
 
 func Convert_v1_DeviceRequest_To_v1beta1_DeviceRequest(in *resourceapi.DeviceRequest, out *resourcev1beta1.DeviceRequest, s conversion.Scope) error {
@@ -102,6 +104,7 @@ func Convert_v1_DeviceRequest_To_v1beta1_DeviceRequest(in *resourceapi.DeviceReq
 			tolerations = append(tolerations, toleration)
 		}
 		out.Tolerations = tolerations
+		out.Capacity = (*resourcev1beta1.CapacityRequirements)(unsafe.Pointer(in.Exactly.Capacity))
 	}
 	return nil
 }
@@ -181,6 +184,10 @@ func Convert_v1beta1_Device_To_v1_Device(in *resourcev1beta1.Device, out *resour
 			taints = append(taints, taint)
 		}
 		out.Taints = taints
+		out.BindsToNode = basic.BindsToNode
+		out.BindingConditions = basic.BindingConditions
+		out.BindingFailureConditions = basic.BindingFailureConditions
+		out.AllowMultipleAllocations = basic.AllowMultipleAllocations
 	}
 	return nil
 }
@@ -226,6 +233,10 @@ func Convert_v1_Device_To_v1beta1_Device(in *resourceapi.Device, out *resourcev1
 		taints = append(taints, taint)
 	}
 	out.Basic.Taints = taints
+	out.Basic.BindsToNode = in.BindsToNode
+	out.Basic.BindingConditions = in.BindingConditions
+	out.Basic.BindingFailureConditions = in.BindingFailureConditions
+	out.Basic.AllowMultipleAllocations = in.AllowMultipleAllocations
 	return nil
 }
 
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/go.mod b/staging/src/k8s.io/dynamic-resource-allocation/go.mod
index 43e0235eaf944..2ba332ddcd688 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/go.mod
+++ b/staging/src/k8s.io/dynamic-resource-allocation/go.mod
@@ -23,6 +23,7 @@ require (
 	k8s.io/klog/v2 v2.130.1
 	k8s.io/kubelet v0.0.0
 	k8s.io/utils v0.0.0-20260210185600-b8788abfbbc2
+	sigs.k8s.io/randfill v1.0.0
 )
 
 require (
@@ -78,7 +79,6 @@ require (
 	k8s.io/component-base v0.0.0 // indirect
 	k8s.io/kube-openapi v0.0.0-20260127142750-a19766b6e2d4 // indirect
 	sigs.k8s.io/json v0.0.0-20250730193827-2d320260d730 // indirect
-	sigs.k8s.io/randfill v1.0.0 // indirect
 	sigs.k8s.io/structured-merge-diff/v6 v6.3.2 // indirect
 	sigs.k8s.io/yaml v1.6.0 // indirect
 )
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
