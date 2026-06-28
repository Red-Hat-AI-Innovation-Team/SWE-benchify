#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/volume/csi/csi_block.go b/pkg/volume/csi/csi_block.go
index 4626751c393c1..5613b354c0cd3 100644
--- a/pkg/volume/csi/csi_block.go
+++ b/pkg/volume/csi/csi_block.go
@@ -68,7 +68,6 @@ package csi
 import (
 	"context"
 	"errors"
-	"fmt"
 	"os"
 	"path/filepath"
 
@@ -171,8 +170,8 @@ func (m *csiBlockMapper) stageVolumeForBlock(
 	if csiSource.NodeStageSecretRef != nil {
 		nodeStageSecrets, err = getCredentialsFromSecret(m.k8s, csiSource.NodeStageSecretRef)
 		if err != nil {
-			return "", fmt.Errorf("failed to get NodeStageSecretRef %s/%s: %v",
-				csiSource.NodeStageSecretRef.Namespace, csiSource.NodeStageSecretRef.Name, err)
+			return "", volumetypes.NewTransientOperationFailure(log("failed to get NodeStageSecretRef %s/%s: %v",
+				csiSource.NodeStageSecretRef.Namespace, csiSource.NodeStageSecretRef.Name, err))
 		}
 	}
 
@@ -223,11 +222,11 @@ func (m *csiBlockMapper) publishVolumeForBlock(
 	volAttribs := csiSource.VolumeAttributes
 	podInfoEnabled, err := m.plugin.podInfoEnabled(string(m.driverName))
 	if err != nil {
-		return "", errors.New(log("blockMapper.publishVolumeForBlock failed to assemble volume attributes: %v", err))
+		return "", volumetypes.NewTransientOperationFailure(log("blockMapper.publishVolumeForBlock failed to assemble volume attributes: %v", err))
 	}
 	volumeLifecycleMode, err := m.plugin.getVolumeLifecycleMode(m.spec)
 	if err != nil {
-		return "", errors.New(log("blockMapper.publishVolumeForBlock failed to get VolumeLifecycleMode: %v", err))
+		return "", volumetypes.NewTransientOperationFailure(log("blockMapper.publishVolumeForBlock failed to get VolumeLifecycleMode: %v", err))
 	}
 	if podInfoEnabled {
 		volAttribs = mergeMap(volAttribs, getPodInfoAttrs(m.pod, volumeLifecycleMode))
@@ -237,7 +236,7 @@ func (m *csiBlockMapper) publishVolumeForBlock(
 	if csiSource.NodePublishSecretRef != nil {
 		nodePublishSecrets, err = getCredentialsFromSecret(m.k8s, csiSource.NodePublishSecretRef)
 		if err != nil {
-			return "", errors.New(log("blockMapper.publishVolumeForBlock failed to get NodePublishSecretRef %s/%s: %v",
+			return "", volumetypes.NewTransientOperationFailure(log("blockMapper.publishVolumeForBlock failed to get NodePublishSecretRef %s/%s: %v",
 				csiSource.NodePublishSecretRef.Namespace, csiSource.NodePublishSecretRef.Name, err))
 		}
 	}
@@ -304,7 +303,7 @@ func (m *csiBlockMapper) SetUpDevice() (string, error) {
 		attachID := getAttachmentName(csiSource.VolumeHandle, csiSource.Driver, nodeName)
 		attachment, err = m.k8s.StorageV1().VolumeAttachments().Get(context.TODO(), attachID, meta.GetOptions{})
 		if err != nil {
-			return "", errors.New(log("blockMapper.SetupDevice failed to get volume attachment [id=%v]: %v", attachID, err))
+			return "", volumetypes.NewTransientOperationFailure(log("blockMapper.SetupDevice failed to get volume attachment [id=%v]: %v", attachID, err))
 		}
 	}
 
@@ -366,7 +365,7 @@ func (m *csiBlockMapper) MapPodDevice() (string, error) {
 		attachID := getAttachmentName(csiSource.VolumeHandle, csiSource.Driver, nodeName)
 		attachment, err = m.k8s.StorageV1().VolumeAttachments().Get(context.TODO(), attachID, meta.GetOptions{})
 		if err != nil {
-			return "", errors.New(log("blockMapper.MapPodDevice failed to get volume attachment [id=%v]: %v", attachID, err))
+			return "", volumetypes.NewTransientOperationFailure(log("blockMapper.MapPodDevice failed to get volume attachment [id=%v]: %v", attachID, err))
 		}
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
