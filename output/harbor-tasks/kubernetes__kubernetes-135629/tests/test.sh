#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/volume/selinuxwarning/selinux_warning_controller_test.go b/pkg/controller/volume/selinuxwarning/selinux_warning_controller_test.go
index cd61f20f36b3f..9d9998bc62a9f 100644
--- a/pkg/controller/volume/selinuxwarning/selinux_warning_controller_test.go
+++ b/pkg/controller/volume/selinuxwarning/selinux_warning_controller_test.go
@@ -56,31 +56,34 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 		existingCSIDrivers []*storagev1.CSIDriver
 		existingPods       []*v1.Pod
 
-		pod                  cache.ObjectName
-		conflicts            []volumecache.Conflict
-		expectError          bool
-		expectedAddedVolumes []addedVolume
-		expectedEvents       []string
-		expectedDeletedPods  []cache.ObjectName
+		pod                     cache.ObjectName
+		csiDriverSELinuxEnabled bool
+		conflicts               []volumecache.Conflict
+		expectError             bool
+		expectedAddedVolumes    []addedVolume
+		expectedEvents          []string
+		expectedDeletedPods     []cache.ObjectName
 	}{
 		{
 			name: "existing pod with no volumes",
 			existingPods: []*v1.Pod{
-				pod("pod1", "s0:c1,c2", nil),
+				pod("pod1", "s0:c1,c2", nil).build(),
 			},
-			pod:                  cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectedEvents:       nil,
-			expectedAddedVolumes: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
+			expectedAddedVolumes:    nil,
 		},
 		{
 			name: "existing pod with unbound PVC",
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", nil, "non-existing-pvc", "vol1"),
+				pod("pod1", "s0:c1,c2", nil).withPVC("non-existing-pvc", "vol1").build(),
 			},
-			pod:                  cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectError:          true, // PVC is missing, add back to queue with exp. backoff
-			expectedEvents:       nil,
-			expectedAddedVolumes: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectError:             true, // PVC is missing, add back to queue with exp. backoff
+			expectedEvents:          nil,
+			expectedAddedVolumes:    nil,
 		},
 		{
 			name: "existing pod with fully bound PVC",
@@ -91,10 +94,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", nil, "pvc1", "vol1"),
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").build(),
 			},
-			pod:            cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectedEvents: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
 			expectedAddedVolumes: []addedVolume{
 				{
 					volumeName:   "fake-plugin/pv1",
@@ -114,10 +118,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive), "pvc1", "vol1"),
+				pod("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive)).withPVC("pvc1", "vol1").build(),
 			},
-			pod:            cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectedEvents: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
 			expectedAddedVolumes: []addedVolume{
 				{
 					volumeName:   "fake-plugin/pv1",
@@ -137,10 +142,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				addInlineVolume(pod("pod1", "s0:c1,c2", nil)),
+				pod("pod1", "s0:c1,c2", nil).withInlineVolume().build(),
 			},
-			pod:            cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectedEvents: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
 			expectedAddedVolumes: []addedVolume{
 				{
 					volumeName:   "fake-plugin/ebs.csi.aws.com-inlinevol1",
@@ -160,10 +166,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				addInlineVolume(podWithPVC("pod1", "s0:c1,c2", nil, "pvc1", "vol1")),
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").withInlineVolume().build(),
 			},
-			pod:            cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectedEvents: nil,
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
 			expectedAddedVolumes: []addedVolume{
 				{
 					volumeName:   "fake-plugin/pv1",
@@ -190,10 +197,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", nil, "pvc1", "vol1"),
-				pod("pod2", "s0:c98,c99", nil),
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").build(),
+				pod("pod2", "s0:c98,c99", nil).build(),
 			},
-			pod: cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
 			conflicts: []volumecache.Conflict{
 				{
 					PropertyName:       "SELinuxLabel",
@@ -235,11 +243,12 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive), "pvc1", "vol1"),
-				pod("pod2", "s0:c98,c99", ptr.To(v1.SELinuxChangePolicyRecursive)),
+				pod("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive)).withPVC("pvc1", "vol1").build(),
+				pod("pod2", "s0:c98,c99", ptr.To(v1.SELinuxChangePolicyRecursive)).build(),
 			},
-			pod:       cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			conflicts: []volumecache.Conflict{},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			conflicts:               []volumecache.Conflict{},
 			expectedAddedVolumes: []addedVolume{
 				{
 					volumeName:   "fake-plugin/pv1",
@@ -259,10 +268,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive), "pvc1", "vol1"),
-				podWithPVC("pod2", "s0:c98,c99", ptr.To(v1.SELinuxChangePolicyMountOption), "pvc1", "vol1"),
+				pod("pod1", "s0:c1,c2", ptr.To(v1.SELinuxChangePolicyRecursive)).withPVC("pvc1", "vol1").build(),
+				pod("pod2", "s0:c98,c99", ptr.To(v1.SELinuxChangePolicyMountOption)).withPVC("pvc1", "vol1").build(),
 			},
-			pod: cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
 			conflicts: []volumecache.Conflict{
 				{
 					PropertyName:       "SELinuxChangePolicy",
@@ -304,10 +314,11 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				pvBoundToPVC("pv1", "pvc1"),
 			},
 			existingPods: []*v1.Pod{
-				podWithPVC("pod1", "s0:c1,c2", nil, "pvc1", "vol1"),
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").build(),
 				// "pod2" does not exist
 			},
-			pod: cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
 			conflicts: []volumecache.Conflict{
 				{
 					PropertyName:       "SELinuxLabel",
@@ -340,16 +351,147 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 				`Normal SELinuxLabelConflict SELinuxLabel ":::s0:c1,c2" conflicts with pod pod2 that uses the same volume as this pod with SELinuxLabel ":::s0:c98,c99". If both pods land on the same node, only one of them may access the volume.`,
 			},
 		},
+		{
+			name: "empty label implies Recursive policy",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "", ptr.To(v1.SELinuxChangePolicyMountOption)).withPVC("pvc1", "vol1").build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			conflicts:               []volumecache.Conflict{},
+			expectedAddedVolumes: []addedVolume{
+				{
+					volumeName:   "fake-plugin/pv1",
+					podKey:       cache.ObjectName{Namespace: namespace, Name: "pod1"},
+					label:        "",
+					changePolicy: v1.SELinuxChangePolicyRecursive, // Reset to Recursive when the label is empty
+					csiDriver:    "ebs.csi.aws.com",
+				},
+			},
+		},
+		{
+			name: "pending pod is processed",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").withPhase(v1.PodPending).build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
+			expectedAddedVolumes: []addedVolume{
+				{
+					volumeName:   "fake-plugin/pv1",
+					podKey:       cache.ObjectName{Namespace: namespace, Name: "pod1"},
+					label:        ":::s0:c1,c2",
+					changePolicy: v1.SELinuxChangePolicyMountOption,
+					csiDriver:    "ebs.csi.aws.com",
+				},
+			},
+		},
+		{
+			name: "unknown pod is processed",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").withPhase(v1.PodUnknown).build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
+			expectedAddedVolumes: []addedVolume{
+				{
+					volumeName:   "fake-plugin/pv1",
+					podKey:       cache.ObjectName{Namespace: namespace, Name: "pod1"},
+					label:        ":::s0:c1,c2",
+					changePolicy: v1.SELinuxChangePolicyMountOption,
+					csiDriver:    "ebs.csi.aws.com",
+				},
+			},
+		},
+		{
+			name: "succeeded pod is removed from the cache",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").withPhase(v1.PodSucceeded).build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
+			expectedAddedVolumes:    nil,
+			expectedDeletedPods:     []cache.ObjectName{{Namespace: namespace, Name: "pod1"}},
+		},
+		{
+			name: "failed pod is removed from the cache",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").withPhase(v1.PodFailed).build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectedEvents:          nil,
+			expectedAddedVolumes:    nil,
+			expectedDeletedPods:     []cache.ObjectName{{Namespace: namespace, Name: "pod1"}},
+		},
 		{
 			name:         "deleted pod",
 			existingPods: []*v1.Pod{
 				// "pod1" does not exist in the informer
 			},
-			pod:                  cache.ObjectName{Namespace: namespace, Name: "pod1"},
-			expectError:          false,
-			expectedEvents:       nil,
-			expectedAddedVolumes: nil,
-			expectedDeletedPods:  []cache.ObjectName{{Namespace: namespace, Name: "pod1"}},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: true,
+			expectError:             false,
+			expectedEvents:          nil,
+			expectedAddedVolumes:    nil,
+			expectedDeletedPods:     []cache.ObjectName{{Namespace: namespace, Name: "pod1"}},
+		},
+		{
+			name: "existing pod with fully bound PVC and CSIDriver.SELinuxMount disabled",
+			existingPVCs: []*v1.PersistentVolumeClaim{
+				pvcBoundToPV("pv1", "pvc1"),
+			},
+			existingPVs: []*v1.PersistentVolume{
+				pvBoundToPVC("pv1", "pvc1"),
+			},
+			existingPods: []*v1.Pod{
+				pod("pod1", "s0:c1,c2", nil).withPVC("pvc1", "vol1").build(),
+			},
+			pod:                     cache.ObjectName{Namespace: namespace, Name: "pod1"},
+			csiDriverSELinuxEnabled: false,
+			expectedEvents:          nil,
+			expectedAddedVolumes: []addedVolume{
+				{
+					volumeName:   "fake-plugin/pv1",
+					podKey:       cache.ObjectName{Namespace: namespace, Name: "pod1"},
+					label:        "",                              // Label is cleared when the CSI driver does not support SELinuxMount
+					changePolicy: v1.SELinuxChangePolicyRecursive, // Reset to Recursive when the CSI driver does not support SELinuxMount
+					csiDriver:    "ebs.csi.aws.com",               // The PV is a fake EBS volume
+				},
+			},
 		},
 	}
 
@@ -364,7 +506,7 @@ func TestSELinuxWarningController_Sync(t *testing.T) {
 			defer cancel()
 
 			_, plugin := volumetesting.GetTestKubeletVolumePluginMgr(t)
-			plugin.SupportsSELinux = true
+			plugin.SupportsSELinux = tt.csiDriverSELinuxEnabled
 
 			fakeClient := fake.NewClientset()
 			fakeInformerFactory := informers.NewSharedInformerFactory(fakeClient, controller.NoResyncPeriodFunc())
@@ -499,49 +641,63 @@ func pvcBoundToPV(pvName, pvcName string) *v1.PersistentVolumeClaim {
 	return pvc
 }
 
-func pod(podName, level string, changePolicy *v1.PodSELinuxChangePolicy) *v1.Pod {
+type podBuilder struct {
+	pod *v1.Pod
+}
+
+func pod(podName, level string, changePolicy *v1.PodSELinuxChangePolicy) *podBuilder {
 	var opts *v1.SELinuxOptions
 	if level != "" {
 		opts = &v1.SELinuxOptions{
 			Level: level,
 		}
 	}
-	return &v1.Pod{
-		ObjectMeta: metav1.ObjectMeta{
-			Namespace: "ns1",
-			Name:      podName,
-		},
-		Spec: v1.PodSpec{
-			Containers: []v1.Container{
-				{
-					Name:  "container1",
-					Image: "image1",
-					VolumeMounts: []v1.VolumeMount{
-						{
-							Name:      "vol1",
-							MountPath: "/mnt",
+	return &podBuilder{
+		pod: &v1.Pod{
+			ObjectMeta: metav1.ObjectMeta{
+				Namespace: "ns1",
+				Name:      podName,
+			},
+			Spec: v1.PodSpec{
+				Containers: []v1.Container{
+					{
+						Name:  "container1",
+						Image: "image1",
+						VolumeMounts: []v1.VolumeMount{
+							{
+								Name:      "vol1",
+								MountPath: "/mnt",
+							},
 						},
 					},
 				},
-			},
-			SecurityContext: &v1.PodSecurityContext{
-				SELinuxChangePolicy: changePolicy,
-				SELinuxOptions:      opts,
-			},
-			Volumes: []v1.Volume{
-				{
-					Name: "emptyDir1",
-					VolumeSource: v1.VolumeSource{
-						EmptyDir: &v1.EmptyDirVolumeSource{},
+				SecurityContext: &v1.PodSecurityContext{
+					SELinuxChangePolicy: changePolicy,
+					SELinuxOptions:      opts,
+				},
+				Volumes: []v1.Volume{
+					{
+						Name: "emptyDir1",
+						VolumeSource: v1.VolumeSource{
+							EmptyDir: &v1.EmptyDirVolumeSource{},
+						},
 					},
 				},
 			},
+			Status: v1.PodStatus{
+				Phase: v1.PodRunning,
+			},
 		},
 	}
 }
 
-func addInlineVolume(pod *v1.Pod) *v1.Pod {
-	pod.Spec.Volumes = append(pod.Spec.Volumes, v1.Volume{
+func (b *podBuilder) withPhase(phase v1.PodPhase) *podBuilder {
+	b.pod.Status.Phase = phase
+	return b
+}
+
+func (b *podBuilder) withInlineVolume() *podBuilder {
+	b.pod.Spec.Volumes = append(b.pod.Spec.Volumes, v1.Volume{
 		Name: "inlineVolume",
 		VolumeSource: v1.VolumeSource{
 			AWSElasticBlockStore: &v1.AWSElasticBlockStoreVolumeSource{
@@ -549,17 +705,15 @@ func addInlineVolume(pod *v1.Pod) *v1.Pod {
 			},
 		},
 	})
-	pod.Spec.Containers[0].VolumeMounts = append(pod.Spec.Containers[0].VolumeMounts, v1.VolumeMount{
+	b.pod.Spec.Containers[0].VolumeMounts = append(b.pod.Spec.Containers[0].VolumeMounts, v1.VolumeMount{
 		Name:      "inlineVolume",
 		MountPath: "/mnt",
 	})
-
-	return pod
+	return b
 }
 
-func podWithPVC(podName, label string, changePolicy *v1.PodSELinuxChangePolicy, pvcName, volumeName string) *v1.Pod {
-	pod := pod(podName, label, changePolicy)
-	pod.Spec.Volumes = append(pod.Spec.Volumes, v1.Volume{
+func (b *podBuilder) withPVC(pvcName, volumeName string) *podBuilder {
+	b.pod.Spec.Volumes = append(b.pod.Spec.Volumes, v1.Volume{
 		Name: volumeName,
 		VolumeSource: v1.VolumeSource{
 			PersistentVolumeClaim: &v1.PersistentVolumeClaimVolumeSource{
@@ -567,11 +721,15 @@ func podWithPVC(podName, label string, changePolicy *v1.PodSELinuxChangePolicy,
 			},
 		},
 	})
-	pod.Spec.Containers[0].VolumeMounts = append(pod.Spec.Containers[0].VolumeMounts, v1.VolumeMount{
+	b.pod.Spec.Containers[0].VolumeMounts = append(b.pod.Spec.Containers[0].VolumeMounts, v1.VolumeMount{
 		Name:      volumeName,
 		MountPath: "/mnt",
 	})
-	return pod
+	return b
+}
+
+func (b *podBuilder) build() *v1.Pod {
+	return b.pod
 }
 
 type addedVolume struct {
diff --git a/test/e2e/storage/csimock/base.go b/test/e2e/storage/csimock/base.go
index 35854b7f67868..5d261ec04fc46 100644
--- a/test/e2e/storage/csimock/base.go
+++ b/test/e2e/storage/csimock/base.go
@@ -150,6 +150,7 @@ const (
 var (
 	errPodCompleted   = fmt.Errorf("pod ran to completion")
 	errNotEnoughSpace = errors.New(errReasonNotEnoughSpace)
+	sleepCommand      = []string{"sleep", "infinity"}
 )
 
 func newMockDriverSetup(f *framework.Framework) *mockDriverSetup {
@@ -476,7 +477,15 @@ func (m *mockDriverSetup) createPodWithFSGroup(ctx context.Context, fsGroup *int
 	return class, claim, pod
 }
 
-func (m *mockDriverSetup) createPodWithSELinux(ctx context.Context, accessModes []v1.PersistentVolumeAccessMode, mountOptions []string, seLinuxOpts *v1.SELinuxOptions, policy *v1.PodSELinuxChangePolicy, privileged bool) (*storagev1.StorageClass, *v1.PersistentVolumeClaim, *v1.Pod) {
+func (m *mockDriverSetup) createPodWithSELinux(
+	ctx context.Context,
+	accessModes []v1.PersistentVolumeAccessMode,
+	mountOptions []string,
+	seLinuxOpts *v1.SELinuxOptions,
+	policy *v1.PodSELinuxChangePolicy,
+	privileged bool,
+	command []string) (*storagev1.StorageClass, *v1.PersistentVolumeClaim, *v1.Pod) {
+
 	ginkgo.By("Creating pod with SELinux context")
 	f := m.f
 	nodeSelection := m.config.ClientNodeSelection
@@ -493,7 +502,7 @@ func (m *mockDriverSetup) createPodWithSELinux(ctx context.Context, accessModes
 		ReclaimPolicy:        m.tp.reclaimPolicy,
 	}
 	class, claim := createClaim(ctx, f.ClientSet, scTest, nodeSelection, m.tp.scName, f.Namespace.Name, accessModes)
-	pod, err := startPausePodWithSELinuxOptions(f.ClientSet, claim, nodeSelection, f.Namespace.Name, seLinuxOpts, policy, privileged)
+	pod, err := startPausePodWithSELinuxOptions(f.ClientSet, claim, nodeSelection, f.Namespace.Name, seLinuxOpts, policy, privileged, command)
 	framework.ExpectNoError(err, "Failed to create pause pod with SELinux context %s: %v", seLinuxOpts, err)
 
 	if class != nil {
@@ -868,7 +877,19 @@ func startBusyBoxPodWithVolumeSource(cs clientset.Interface, volumeSource v1.Vol
 	return cs.CoreV1().Pods(ns).Create(context.TODO(), pod, metav1.CreateOptions{})
 }
 
-func startPausePodWithSELinuxOptions(cs clientset.Interface, pvc *v1.PersistentVolumeClaim, node e2epod.NodeSelection, ns string, seLinuxOpts *v1.SELinuxOptions, policy *v1.PodSELinuxChangePolicy, privileged bool) (*v1.Pod, error) {
+func startPausePodWithSELinuxOptions(
+	cs clientset.Interface,
+	pvc *v1.PersistentVolumeClaim,
+	node e2epod.NodeSelection,
+	ns string,
+	seLinuxOpts *v1.SELinuxOptions,
+	policy *v1.PodSELinuxChangePolicy,
+	privileged bool,
+	command []string) (*v1.Pod, error) {
+
+	if len(command) == 0 {
+		command = sleepCommand
+	}
 	pod := &v1.Pod{
 		ObjectMeta: metav1.ObjectMeta{
 			GenerateName: "pvc-volume-tester-",
@@ -880,8 +901,9 @@ func startPausePodWithSELinuxOptions(cs clientset.Interface, pvc *v1.PersistentV
 			},
 			Containers: []v1.Container{
 				{
-					Name:  "volume-tester",
-					Image: imageutils.GetE2EImage(imageutils.Pause),
+					Name:    "volume-tester",
+					Image:   e2epod.GetDefaultTestImage(),
+					Command: command,
 					SecurityContext: &v1.SecurityContext{
 						Privileged: &privileged,
 					},
diff --git a/test/e2e/storage/csimock/csi_selinux_mount.go b/test/e2e/storage/csimock/csi_selinux_mount.go
index 09470056c7c69..e6da5c7c427e3 100644
--- a/test/e2e/storage/csimock/csi_selinux_mount.go
+++ b/test/e2e/storage/csimock/csi_selinux_mount.go
@@ -298,7 +298,7 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount", func() {
 				// Act
 				ginkgo.By("Starting the initial pod")
 				accessModes := []v1.PersistentVolumeAccessMode{t.volumeMode}
-				_, claim, pod := m.createPodWithSELinux(ctx, accessModes, t.mountOptions, t.firstPodSELinuxOpts, t.firstPodChangePolicy, false /* privileged */)
+				_, claim, pod := m.createPodWithSELinux(ctx, accessModes, t.mountOptions, t.firstPodSELinuxOpts, t.firstPodChangePolicy, false /* privileged */, sleepCommand)
 				err := e2epod.WaitForPodNameRunningInNamespace(ctx, m.cs, pod.Name, pod.Namespace)
 				framework.ExpectNoError(err, "starting the initial pod")
 
@@ -331,7 +331,15 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount", func() {
 				pod, err = m.cs.CoreV1().Pods(pod.Namespace).Get(ctx, pod.Name, metav1.GetOptions{})
 				framework.ExpectNoError(err, "getting the initial pod")
 				nodeSelection := e2epod.NodeSelection{Name: pod.Spec.NodeName}
-				pod2, err := startPausePodWithSELinuxOptions(f.ClientSet, claim, nodeSelection, f.Namespace.Name, t.secondPodSELinuxOpts, t.secondPodChangePolicy, false /* privileged */)
+				pod2, err := startPausePodWithSELinuxOptions(
+					f.ClientSet,
+					claim,
+					nodeSelection,
+					f.Namespace.Name,
+					t.secondPodSELinuxOpts,
+					t.secondPodChangePolicy,
+					false, /* privileged */
+					sleepCommand)
 				framework.ExpectNoError(err, "creating second pod with SELinux context %s", t.secondPodSELinuxOpts)
 				m.pods = append(m.pods, pod2)
 
@@ -455,6 +463,7 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 			firstPodSELinuxOpts              *v1.SELinuxOptions
 			firstPodChangePolicy             *v1.PodSELinuxChangePolicy
 			firstPodPrivileged               bool
+			firstPodTargetPhase              v1.PodPhase // Phase the first pod should reach before the second pod is created. Empty value means Running
 			secondPodSELinuxOpts             *v1.SELinuxOptions
 			secondPodChangePolicy            *v1.PodSELinuxChangePolicy
 			secondPodPrivileged              bool
@@ -720,6 +729,74 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 				expectControllerConflictProperty: "SELinuxLabel",
 				testTags:                         []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
 			},
+			{
+				name:                    "error is not bumped on a finished Pod with a different context on RWO volume and SELinuxMount enabled",
+				csiDriverSELinuxEnabled: true,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				firstPodTargetPhase:     v1.PodSucceeded,
+				secondPodSELinuxOpts:    &seLinuxOpts2,
+				volumeMode:              v1.ReadWriteOnce,
+				waitForSecondPodStart:   true,
+				// The volume is unmounted between the first and the second Pod, so admitted_total increases,
+				expectNodeIncreases: sets.New[string]("volume_manager_selinux_volumes_admitted_total"),
+				testTags:            []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
+			{
+				name:                    "error is not bumped on a failed Pod with a different context on RWO volume and SELinuxMount enabled",
+				csiDriverSELinuxEnabled: true,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				firstPodTargetPhase:     v1.PodFailed,
+				secondPodSELinuxOpts:    &seLinuxOpts2,
+				volumeMode:              v1.ReadWriteOnce,
+				waitForSecondPodStart:   true,
+				// The volume is unmounted between the first and the second Pod, so admitted_total increases,
+				expectNodeIncreases: sets.New[string]("volume_manager_selinux_volumes_admitted_total"),
+				testTags:            []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
+			{
+				name:                    "warning is not bumped on RWO volume with CSIDriver.SELinuxMount disabled and mismatched labels",
+				csiDriverSELinuxEnabled: false,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				secondPodSELinuxOpts:    &seLinuxOpts2,
+				volumeMode:              v1.ReadWriteOnce,
+				waitForSecondPodStart:   true,
+				expectNodeIncreases:     sets.New[string]( /* no metric is increased, admitted_total was already increased when the first pod started */ ),
+				testTags:                []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
+			{
+				name:                    "warning is not bumped on RWX volume with CSIDriver.SELinuxMount disabled and mismatched labels",
+				csiDriverSELinuxEnabled: false,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				secondPodSELinuxOpts:    &seLinuxOpts2,
+				volumeMode:              v1.ReadWriteMany,
+				waitForSecondPodStart:   true,
+				expectNodeIncreases:     sets.New[string]( /* no metric is increased, admitted_total was already increased when the first pod started */ ),
+				testTags:                []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
+			{
+				name:                    "warning is not bumped on RWO volume with CSIDriver.SELinuxMount disabled and mismatched policies",
+				csiDriverSELinuxEnabled: false,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				firstPodChangePolicy:    &recursive,
+				secondPodSELinuxOpts:    &seLinuxOpts1,
+				secondPodChangePolicy:   &mount,
+				volumeMode:              v1.ReadWriteOnce,
+				waitForSecondPodStart:   true,
+				expectNodeIncreases:     sets.New[string]( /* no metric is increased, admitted_total was already increased when the first pod started */ ),
+				testTags:                []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
+			{
+				name:                    "warning is not bumped on RWX volume with CSIDriver.SELinuxMount disabled and mismatched policies",
+				csiDriverSELinuxEnabled: false,
+				firstPodSELinuxOpts:     &seLinuxOpts1,
+				firstPodChangePolicy:    &recursive,
+				secondPodSELinuxOpts:    &seLinuxOpts1,
+				secondPodChangePolicy:   &mount,
+				volumeMode:              v1.ReadWriteMany,
+				waitForSecondPodStart:   true,
+				expectNodeIncreases:     sets.New[string]( /* no metric is increased, admitted_total was already increased when the first pod started */ ),
+				testTags:                []interface{}{framework.WithFeatureGate(features.SELinuxMount)},
+			},
 		}
 		for _, t := range tests {
 			t := t
@@ -727,6 +804,9 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 				if processLabel == "" {
 					e2eskipper.Skipf("SELinux tests are supported only on %+v", getSupportedSELinuxDistros())
 				}
+				if t.firstPodTargetPhase == "" {
+					t.firstPodTargetPhase = v1.PodRunning
+				}
 
 				// Some metrics use CSI driver name as a label, which is "csi-mock-" + the namespace name.
 				volumePluginLabel := "volume_plugin=\"kubernetes.io/csi/csi-mock-" + f.Namespace.Name + "\""
@@ -745,9 +825,24 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 
 				ginkgo.By("Starting the first pod")
 				accessModes := []v1.PersistentVolumeAccessMode{t.volumeMode}
-				_, claim, pod := m.createPodWithSELinux(ctx, accessModes, []string{}, t.firstPodSELinuxOpts, t.firstPodChangePolicy, t.firstPodPrivileged)
-				err = e2epod.WaitForPodNameRunningInNamespace(ctx, m.cs, pod.Name, pod.Namespace)
-				framework.ExpectNoError(err, "starting the initial pod")
+				command := sleepCommand
+				switch t.firstPodTargetPhase {
+				case v1.PodSucceeded:
+					command = []string{"/bin/true"}
+				case v1.PodFailed:
+					command = []string{"/bin/false"}
+				}
+				_, claim, pod := m.createPodWithSELinux(ctx, accessModes, []string{}, t.firstPodSELinuxOpts, t.firstPodChangePolicy, t.firstPodPrivileged, command)
+
+				switch t.firstPodTargetPhase {
+				case v1.PodRunning:
+					err = e2epod.WaitForPodNameRunningInNamespace(ctx, m.cs, pod.Name, pod.Namespace)
+					framework.ExpectNoError(err, "starting the initial pod")
+				case v1.PodSucceeded, v1.PodFailed:
+					ginkgo.By("Waiting for the first pod to complete")
+					err = e2epod.WaitForPodNoLongerRunningInNamespace(ctx, m.cs, pod.Name, pod.Namespace)
+					framework.ExpectNoError(err, "starting and completing the initial pod")
+				}
 
 				ginkgo.By("Grabbing initial metrics")
 				pod, err = m.cs.CoreV1().Pods(pod.Namespace).Get(ctx, pod.Name, metav1.GetOptions{})
@@ -760,7 +855,15 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 				ginkgo.By("Starting the second pod")
 				// Skip scheduler, it would block scheduling the second pod with ReadWriteOncePod PV.
 				nodeSelection := e2epod.NodeSelection{Name: pod.Spec.NodeName}
-				pod2, err := startPausePodWithSELinuxOptions(f.ClientSet, claim, nodeSelection, f.Namespace.Name, t.secondPodSELinuxOpts, t.secondPodChangePolicy, t.secondPodPrivileged)
+				pod2, err := startPausePodWithSELinuxOptions(
+					f.ClientSet,
+					claim,
+					nodeSelection,
+					f.Namespace.Name,
+					t.secondPodSELinuxOpts,
+					t.secondPodChangePolicy,
+					t.secondPodPrivileged,
+					sleepCommand)
 				framework.ExpectNoError(err, "creating second pod with SELinux context %s", t.secondPodSELinuxOpts)
 				m.pods = append(m.pods, pod2)
 
@@ -796,6 +899,9 @@ var _ = utils.SIGDescribe("CSI Mock selinux on mount metrics and SELinuxWarningC
 					// Check the controler generated event on the second pod
 					err = waitForConflictEvent(ctx, m.cs, pod2, pod, t.expectControllerConflictProperty, f.Timeouts.PodStart)
 					framework.ExpectNoError(err, "while waiting for an event on the second pod")
+				} else {
+					err := checkForNoConflictEvents(ctx, m.cs, pod, pod2)
+					framework.ExpectNoError(err, "ensuring there are no SELinux conflict events")
 				}
 			}
 			// t.testTags is array and it'"'"'s not possible to use It("name", func(){xxx}, t.testTags...)
@@ -975,6 +1081,29 @@ func waitForConflictEvent(ctx context.Context, cs clientset.Interface, pod, othe
 	return e2eevents.WaitTimeoutForEvent(ctx, cs, pod.Namespace, eventSelector, msg, timeout)
 }
 
+func checkForNoConflictEvents(ctx context.Context, cs clientset.Interface, pod, otherPod *v1.Pod) error {
+	eventSelector := fields.Set{
+		"involvedObject.kind":      "Pod",
+		"involvedObject.name":      pod.Name,
+		"involvedObject.namespace": pod.Namespace,
+	}.AsSelector().String()
+	options := metav1.ListOptions{FieldSelector: eventSelector}
+
+	events, err := cs.CoreV1().Events(pod.Namespace).List(ctx, options)
+	if err != nil {
+		return fmt.Errorf("error getting events: %w", err)
+	}
+
+	msg := fmt.Sprintf("conflicts with pod %s that uses the same volume as this pod", otherPod.Name)
+	ginkgo.By(fmt.Sprintf("Checking for the SELinux controller events on pod %q: %q", pod.Name, msg))
+	for _, event := range events.Items {
+		if strings.Contains(event.Message, msg) {
+			return fmt.Errorf("conflict event found: %s", event.Message)
+		}
+	}
+	return nil
+}
+
 func dumpMetrics(metrics map[string]float64) {
 	// Print the metrics sorted by metric name for better readability
 	keys := make([]string, 0, len(metrics))
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestSELinuxWarningController_Sync"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
