#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/cm/cpumanager/state/checkpoint.go b/pkg/kubelet/cm/cpumanager/state/checkpoint.go
index 625dca93d0b96..6903ef3e9d922 100644
--- a/pkg/kubelet/cm/cpumanager/state/checkpoint.go
+++ b/pkg/kubelet/cm/cpumanager/state/checkpoint.go
@@ -100,7 +100,17 @@ func (cp *CPUManagerCheckpointV1) MarshalCheckpoint() ([]byte, error) {
 func (cp *CPUManagerCheckpointV2) MarshalCheckpoint() ([]byte, error) {
 	// make sure checksum wasn't set before so it doesn't affect output checksum
 	cp.Checksum = 0
-	cp.Checksum = checksum.New(cp)
+
+	// In order to preserve rollback compatibility when the feature gate is disabled,
+	// we must generate a checksum using the legacy struct name "CPUManagerCheckpoint"
+	// instead of "CPUManagerCheckpointV2". Older Kubelets do not have the string
+	// replacement logic and expect the original struct name.
+	object := dump.ForHash(cp)
+	object = strings.Replace(object, "CPUManagerCheckpointV2", "CPUManagerCheckpoint", 1)
+	hash := fnv.New32a()
+	_, _ = fmt.Fprintf(hash, "%v", object)
+	cp.Checksum = checksum.Checksum(hash.Sum32())
+
 	return json.Marshal(*cp)
 }
 
diff --git a/pkg/kubelet/cm/memorymanager/state/checkpoint.go b/pkg/kubelet/cm/memorymanager/state/checkpoint.go
index be8a359cb55e7..445d0cf57b777 100644
--- a/pkg/kubelet/cm/memorymanager/state/checkpoint.go
+++ b/pkg/kubelet/cm/memorymanager/state/checkpoint.go
@@ -79,7 +79,17 @@ func newMemoryManagerCheckpointV2() *MemoryManagerCheckpointV2 {
 func (mp *MemoryManagerCheckpointV1) MarshalCheckpoint() ([]byte, error) {
 	// make sure checksum wasn't set before so it doesn't affect output checksum
 	mp.Checksum = 0
-	mp.Checksum = checksum.New(mp)
+
+	// In order to preserve rollback compatibility when the feature gate is disabled,
+	// we must generate a checksum using the legacy struct name "MemoryManagerCheckpoint"
+	// instead of "MemoryManagerCheckpointV1". Older Kubelets do not have the string
+	// replacement logic and expect the original struct name.
+	object := dump.ForHash(mp)
+	object = strings.Replace(object, "MemoryManagerCheckpointV1", "MemoryManagerCheckpoint", 1)
+	hash := fnv.New32a()
+	_, _ = fmt.Fprintf(hash, "%v", object)
+	mp.Checksum = checksum.Checksum(hash.Sum32())
+
 	return json.Marshal(*mp)
 }
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
