#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/apis/networking/util/helpers.go b/pkg/apis/networking/util/helpers.go
new file mode 100644
index 0000000000000..1e2864f2e4c50
--- /dev/null
+++ b/pkg/apis/networking/util/helpers.go
@@ -0,0 +1,27 @@
+/*
+Copyright 2025 The Kubernetes Authors.
+
+Licensed under the Apache License, Version 2.0 (the "License");
+you may not use this file except in compliance with the License.
+You may obtain a copy of the License at
+
+    http://www.apache.org/licenses/LICENSE-2.0
+
+Unless required by applicable law or agreed to in writing, software
+distributed under the License is distributed on an "AS IS" BASIS,
+WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
+See the License for the specific language governing permissions and
+limitations under the License.
+*/
+
+package util
+
+import (
+	networkingv1 "k8s.io/api/networking/v1"
+	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
+)
+
+// HasDefaultAnnotation returns true if the object metadata has the default annotation set.
+func HasDefaultAnnotation(obj metav1.ObjectMeta) bool {
+	return obj.Annotations[networkingv1.AnnotationIsDefaultIngressClass] == "true"
+}
diff --git a/pkg/printers/internalversion/printers.go b/pkg/printers/internalversion/printers.go
index 2207c1a18a9db..e8979c761cc8d 100644
--- a/pkg/printers/internalversion/printers.go
+++ b/pkg/printers/internalversion/printers.go
@@ -68,6 +68,7 @@ import (
 	"k8s.io/kubernetes/pkg/apis/flowcontrol"
 	apihelpers "k8s.io/kubernetes/pkg/apis/flowcontrol/util"
 	"k8s.io/kubernetes/pkg/apis/networking"
+	networkingutil "k8s.io/kubernetes/pkg/apis/networking/util"
 	nodeapi "k8s.io/kubernetes/pkg/apis/node"
 	"k8s.io/kubernetes/pkg/apis/policy"
 	"k8s.io/kubernetes/pkg/apis/rbac"
@@ -1494,6 +1495,11 @@ func printIngressClass(obj *networking.IngressClass, options printers.GenerateOp
 	row := metav1.TableRow{
 		Object: runtime.RawExtension{Object: obj},
 	}
+
+	name := obj.Name
+	if networkingutil.HasDefaultAnnotation(obj.ObjectMeta) {
+		name += " (default)"
+	}
 	parameters := "<none>"
 	if obj.Spec.Parameters != nil {
 		parameters = obj.Spec.Parameters.Kind
@@ -1503,7 +1509,7 @@ func printIngressClass(obj *networking.IngressClass, options printers.GenerateOp
 		parameters = parameters + "/" + obj.Spec.Parameters.Name
 	}
 	createTime := translateTimestampSince(obj.CreationTimestamp)
-	row.Cells = append(row.Cells, obj.Name, obj.Spec.Controller, parameters, createTime)
+	row.Cells = append(row.Cells, name, obj.Spec.Controller, parameters, createTime)
 	return []metav1.TableRow{row}, nil
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
