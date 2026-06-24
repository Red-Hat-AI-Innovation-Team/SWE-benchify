#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/cmd/kube-proxy/app/server.go b/cmd/kube-proxy/app/server.go
index 3f3cc6571e88e..81aa2b7241a6a 100644
--- a/cmd/kube-proxy/app/server.go
+++ b/cmd/kube-proxy/app/server.go
@@ -34,7 +34,6 @@ import (
 	"k8s.io/apimachinery/pkg/fields"
 	"k8s.io/apimachinery/pkg/labels"
 	"k8s.io/apimachinery/pkg/selection"
-	"k8s.io/apimachinery/pkg/types"
 	utilerrors "k8s.io/apimachinery/pkg/util/errors"
 	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
 	"k8s.io/apimachinery/pkg/util/validation/field"
@@ -236,10 +235,10 @@ func newProxyServer(ctx context.Context, config *kubeproxyconfig.KubeProxyConfig
 	s.Recorder = s.Broadcaster.NewRecorder(proxyconfigscheme.Scheme, kubeProxy)
 
 	s.NodeRef = &v1.ObjectReference{
-		Kind:      "Node",
-		Name:      s.NodeName,
-		UID:       types.UID(s.NodeName),
-		Namespace: "",
+		APIVersion: "v1",
+		Kind:       "Node",
+		Name:       s.NodeName,
+		Namespace:  "",
 	}
 
 	if len(config.HealthzBindAddress) > 0 {
diff --git a/pkg/kubelet/cm/node_container_manager_linux.go b/pkg/kubelet/cm/node_container_manager_linux.go
index 7fa180cefdd72..8364c98ac8959 100644
--- a/pkg/kubelet/cm/node_container_manager_linux.go
+++ b/pkg/kubelet/cm/node_container_manager_linux.go
@@ -28,7 +28,6 @@ import (
 
 	v1 "k8s.io/api/core/v1"
 	"k8s.io/apimachinery/pkg/api/resource"
-	"k8s.io/apimachinery/pkg/types"
 	utilfeature "k8s.io/apiserver/pkg/util/feature"
 	"k8s.io/klog/v2"
 	kubefeatures "k8s.io/kubernetes/pkg/features"
@@ -320,9 +319,9 @@ func (cm *containerManagerImpl) validateNodeAllocatable() error {
 // Using ObjectReference for events as the node maybe not cached; refer to #42701 for detail.
 func nodeRefFromNode(nodeName string) *v1.ObjectReference {
 	return &v1.ObjectReference{
-		Kind:      "Node",
-		Name:      nodeName,
-		UID:       types.UID(nodeName),
-		Namespace: "",
+		APIVersion: "v1",
+		Kind:       "Node",
+		Name:       nodeName,
+		Namespace:  "",
 	}
 }
diff --git a/pkg/kubelet/kubelet.go b/pkg/kubelet/kubelet.go
index 13622516eecab..2b47fa184a4d2 100644
--- a/pkg/kubelet/kubelet.go
+++ b/pkg/kubelet/kubelet.go
@@ -548,10 +548,10 @@ func NewMainKubelet(ctx context.Context,
 
 	// construct a node reference used for events
 	nodeRef := &v1.ObjectReference{
-		Kind:      "Node",
-		Name:      string(nodeName),
-		UID:       types.UID(nodeName),
-		Namespace: "",
+		APIVersion: "v1",
+		Kind:       "Node",
+		Name:       string(nodeName),
+		Namespace:  "",
 	}
 
 	oomWatcher, err := oomwatcher.NewWatcher(kubeDeps.Recorder)
diff --git a/pkg/proxy/healthcheck/service_health.go b/pkg/proxy/healthcheck/service_health.go
index 0d4f066dd0b10..e470f94c36dcd 100644
--- a/pkg/proxy/healthcheck/service_health.go
+++ b/pkg/proxy/healthcheck/service_health.go
@@ -136,10 +136,10 @@ func (hcs *server) SyncServices(newServices map[types.NamespacedName]uint16) err
 			if hcs.recorder != nil {
 				hcs.recorder.Eventf(
 					&v1.ObjectReference{
-						Kind:      "Service",
-						Namespace: nsn.Namespace,
-						Name:      nsn.Name,
-						UID:       types.UID(nsn.String()),
+						APIVersion: "v1",
+						Kind:       "Service",
+						Namespace:  nsn.Namespace,
+						Name:       nsn.Name,
 					}, nil, api.EventTypeWarning, "FailedToStartServiceHealthcheck", "Listen", msg)
 			}
 			klog.ErrorS(err, "Failed to start healthcheck", "node", hcs.nodeName, "service", nsn, "port", port)
diff --git a/pkg/proxy/kubemark/hollow_proxy.go b/pkg/proxy/kubemark/hollow_proxy.go
index 34fdc94896c32..9f7b821b60f3d 100644
--- a/pkg/proxy/kubemark/hollow_proxy.go
+++ b/pkg/proxy/kubemark/hollow_proxy.go
@@ -24,7 +24,6 @@ import (
 	v1 "k8s.io/api/core/v1"
 	discoveryv1 "k8s.io/api/discovery/v1"
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
-	"k8s.io/apimachinery/pkg/types"
 	clientset "k8s.io/client-go/kubernetes"
 	v1core "k8s.io/client-go/kubernetes/typed/core/v1"
 	"k8s.io/client-go/tools/events"
@@ -76,10 +75,10 @@ func NewHollowProxy(
 			Broadcaster: broadcaster,
 			Recorder:    recorder,
 			NodeRef: &v1.ObjectReference{
-				Kind:      "Node",
-				Name:      nodeName,
-				UID:       types.UID(nodeName),
-				Namespace: "",
+				APIVersion: "v1",
+				Kind:       "Node",
+				Name:       nodeName,
+				Namespace:  "",
 			},
 		},
 	}
diff --git a/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller.go b/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller.go
index 836de29ffe238..2c8598b560c16 100644
--- a/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller.go
+++ b/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller.go
@@ -163,10 +163,11 @@ func (c *CloudNodeLifecycleController) MonitorNodes(ctx context.Context) {
 			klog.V(2).Infof("deleting node since it is no longer present in cloud provider: %s", node.Name)
 
 			ref := &v1.ObjectReference{
-				Kind:      "Node",
-				Name:      node.Name,
-				UID:       types.UID(node.UID),
-				Namespace: "",
+				APIVersion: "v1",
+				Kind:       "Node",
+				Name:       node.Name,
+				UID:        node.UID,
+				Namespace:  "",
 			}
 
 			c.recorder.Eventf(ref, v1.EventTypeNormal, deleteNodeEvent,
diff --git a/staging/src/k8s.io/cloud-provider/controllers/route/route_controller.go b/staging/src/k8s.io/cloud-provider/controllers/route/route_controller.go
index 96cf1a465ee91..fe13c5feda54b 100644
--- a/staging/src/k8s.io/cloud-provider/controllers/route/route_controller.go
+++ b/staging/src/k8s.io/cloud-provider/controllers/route/route_controller.go
@@ -307,10 +307,11 @@ func (rc *RouteController) reconcile(ctx context.Context, nodes []*v1.Node, rout
 						if rc.recorder != nil {
 							rc.recorder.Eventf(
 								&v1.ObjectReference{
-									Kind:      "Node",
-									Name:      string(nodeName),
-									UID:       types.UID(nodeName),
-									Namespace: "",
+									APIVersion: "v1",
+									Kind:       "Node",
+									Name:       string(nodeName),
+									UID:        node.UID,
+									Namespace:  "",
 								}, v1.EventTypeWarning, "FailedToCreateRoute", msg)
 							klog.V(4).Info(msg)
 							return err
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
