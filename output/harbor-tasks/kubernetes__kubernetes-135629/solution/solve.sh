#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/controller/volume/selinuxwarning/cache/volumecache.go b/pkg/controller/volume/selinuxwarning/cache/volumecache.go
index dfa129dae9064..4b19c985c866e 100644
--- a/pkg/controller/volume/selinuxwarning/cache/volumecache.go
+++ b/pkg/controller/volume/selinuxwarning/cache/volumecache.go
@@ -114,11 +114,19 @@ func (c *volumeCache) AddVolume(logger klog.Logger, volumeName v1.UniqueVolumeNa
 	}
 
 	// The volume is already known
-	// Add the pod to the cache or update its properties
-	volume.pods[podKey] = podInfo{
+	podInfo := podInfo{
 		seLinuxLabel: label,
 		changePolicy: changePolicy,
 	}
+	oldPodInfo, found := volume.pods[podKey]
+	if found && oldPodInfo == podInfo {
+		// The Pod is already known too and nothing changed since the last update.
+		// All conflicts were already reported when the Pod was added / updated in the cache last time.
+		return conflicts
+	}
+
+	// Add the updated pod info to the cache
+	volume.pods[podKey] = podInfo
 
 	// Emit conflicts for the pod
 	for otherPodKey, otherPodInfo := range volume.pods {
diff --git a/pkg/controller/volume/selinuxwarning/selinux_warning_controller.go b/pkg/controller/volume/selinuxwarning/selinux_warning_controller.go
index 7e9d0e01ccfe4..1281074dc06af 100644
--- a/pkg/controller/volume/selinuxwarning/selinux_warning_controller.go
+++ b/pkg/controller/volume/selinuxwarning/selinux_warning_controller.go
@@ -141,9 +141,9 @@ func NewController(
 
 	logger := klog.FromContext(ctx)
 	_, err = podInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
-		AddFunc:    func(obj interface{}) { c.addPod(logger, obj) },
-		DeleteFunc: func(obj interface{}) { c.deletePod(logger, obj) },
-		// Not watching updates: Pod volumes and SecurityContext are immutable after creation
+		AddFunc:    func(obj interface{}) { c.enqueuePod(logger, obj) },
+		UpdateFunc: func(oldObj, newObj interface{}) { c.updatePod(logger, oldObj, newObj) },
+		DeleteFunc: func(obj interface{}) { c.enqueuePod(logger, obj) },
 	})
 	if err != nil {
 		return nil, err
@@ -179,7 +179,7 @@ func NewController(
 	return c, nil
 }
 
-func (c *Controller) addPod(_ klog.Logger, obj interface{}) {
+func (c *Controller) enqueuePod(_ klog.Logger, obj interface{}) {
 	podRef, err := cache.DeletionHandlingObjectToName(obj)
 	if err != nil {
 		utilruntime.HandleError(fmt.Errorf("couldn't get key for pod %#v: %w", obj, err))
@@ -187,12 +187,29 @@ func (c *Controller) addPod(_ klog.Logger, obj interface{}) {
 	c.queue.Add(podRef)
 }
 
-func (c *Controller) deletePod(_ klog.Logger, obj interface{}) {
-	podRef, err := cache.DeletionHandlingObjectToName(obj)
-	if err != nil {
-		utilruntime.HandleError(fmt.Errorf("couldn't get key for pod %#v: %w", obj, err))
+func (c *Controller) updatePod(logger klog.Logger, oldObj, newObj interface{}) {
+	// Pod.Spec fields that are relevant to this controller are immutable after creation (i.e.
+	// pod volumes, SELinux labels, privileged flag). React to update only when the Pod
+	// reaches its final state - kubelet will unmount the Pod volumes and the controller should
+	// therefore remove them from the cache.
+	oldPod, ok := oldObj.(*v1.Pod)
+	if !ok {
+		return
 	}
-	c.queue.Add(podRef)
+	newPod, ok := newObj.(*v1.Pod)
+	if !ok {
+		return
+	}
+
+	// This is an optimization. In theory, passing most pod updates to the controller queue should lead to noop.
+	// To save some CPU, pass only pod updates that can cause any action in the controller
+	if oldPod.Status.Phase == newPod.Status.Phase {
+		return
+	}
+	if newPod.Status.Phase != v1.PodFailed && newPod.Status.Phase != v1.PodSucceeded {
+		return
+	}
+	c.enqueuePod(logger, newObj)
 }
 
 func (c *Controller) addPVC(logger klog.Logger, obj interface{}) {
@@ -278,11 +295,7 @@ func (c *Controller) enqueueAllPodsForPVC(logger klog.Logger, namespace, name st
 		return
 	}
 	for _, obj := range objs {
-		podRef, err := cache.DeletionHandlingObjectToName(obj)
-		if err != nil {
-			utilruntime.HandleError(fmt.Errorf("couldn't get key for pod %#v: %w", obj, err))
-		}
-		c.queue.Add(podRef)
+		c.enqueuePod(logger, obj)
 	}
 }
 
@@ -409,6 +422,11 @@ func (c *Controller) sync(ctx context.Context, podRef cache.ObjectName) error {
 		logger.V(5).Info("Error getting pod from informer", "pod", klog.KObj(pod), "podUID", pod.UID, "err", err)
 		return err
 	}
+	if pod.Status.Phase == v1.PodFailed || pod.Status.Phase == v1.PodSucceeded {
+		// The pod has reached its final state and kubelet is unmounting is volumes.
+		// Remove them from the cache.
+		return c.syncPodDelete(ctx, podRef)
+	}
 
 	return c.syncPod(ctx, pod)
 }
@@ -489,8 +507,15 @@ func (c *Controller) syncVolume(logger klog.Logger, pod *v1.Pod, spec *volume.Sp
 	changePolicy := v1.SELinuxChangePolicyMountOption
 	if pod.Spec.SecurityContext != nil && pod.Spec.SecurityContext.SELinuxChangePolicy != nil {
 		changePolicy = *pod.Spec.SecurityContext.SELinuxChangePolicy
+		logger.V(5).Info("Using Pod SELinux change policy", "pod", klog.KObj(pod), "changePolicy", changePolicy)
 	}
-	if !pluginSupportsSELinuxContextMount {
+	if !pluginSupportsSELinuxContextMount && changePolicy != v1.SELinuxChangePolicyRecursive {
+		logger.V(5).Info("Volume does not support SELinux context mount, setting changePolicy to Recursive", "pod", klog.KObj(pod), "volume", spec.Name())
+		changePolicy = v1.SELinuxChangePolicyRecursive
+	}
+
+	if seLinuxLabel == "" && changePolicy != v1.SELinuxChangePolicyRecursive {
+		logger.V(5).Info("Pod has empty SELinux label, setting changePolicy to Recursive", "pod", klog.KObj(pod))
 		changePolicy = v1.SELinuxChangePolicyRecursive
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
