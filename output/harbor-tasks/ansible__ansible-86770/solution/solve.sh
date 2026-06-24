#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/82792-sort-entries-in-FILES_json.yml b/changelogs/fragments/82792-sort-entries-in-FILES_json.yml
new file mode 100644
index 00000000000000..2b0b56337e8c71
--- /dev/null
+++ b/changelogs/fragments/82792-sort-entries-in-FILES_json.yml
@@ -0,0 +1,2 @@
+minor_changes:
+  - ansible-galaxy - sort the FILES.json for ansible galaxy build based on name. (https://github.com/ansible/ansible/issues/82792).
diff --git a/lib/ansible/galaxy/collection/__init__.py b/lib/ansible/galaxy/collection/__init__.py
index 3a4d1da506df0f..8fd20043bebea0 100644
--- a/lib/ansible/galaxy/collection/__init__.py
+++ b/lib/ansible/galaxy/collection/__init__.py
@@ -32,6 +32,7 @@
 from importlib.metadata import distribution
 from importlib.resources import files
 from itertools import chain
+from operator import itemgetter
 
 try:
     from packaging.requirements import Requirement as PkgReq
@@ -79,7 +80,10 @@
     ManifestValueType = t.Dict[CollectionInfoKeysType, t.Union[int, str, t.List[str], t.Dict[str, str], None]]
     CollectionManifestType = t.Dict[ManifestKeysType, ManifestValueType]
     FileManifestEntryType = t.Dict[FileMetaKeysType, t.Union[str, int, None]]
-    FilesManifestType = t.Dict[t.Literal['files', 'format'], t.Union[t.List[FileManifestEntryType], int]]
+
+    class FilesManifestType(t.TypedDict):
+        files: t.List[FileManifestEntryType]
+        format: int
 
 import ansible.constants as C
 from ansible.errors import AnsibleError
@@ -1070,15 +1074,19 @@ def _build_files_manifest(b_collection_path, namespace, name, ignore_patterns,
         raise AnsibleError('"build_ignore" and "manifest" are mutually exclusive')
 
     if manifest_control is not Sentinel:
-        return _build_files_manifest_distlib(
+        manifest = _build_files_manifest_distlib(
             b_collection_path,
             namespace,
             name,
             manifest_control,
             license_file,
         )
+    else:
+        manifest = _build_files_manifest_walk(b_collection_path, namespace, name, ignore_patterns)
 
-    return _build_files_manifest_walk(b_collection_path, namespace, name, ignore_patterns)
+    manifest['files'].sort(key=itemgetter('name'))
+
+    return manifest
 
 
 def _build_files_manifest_distlib(b_collection_path, namespace, name, manifest_control,
@@ -1180,7 +1188,6 @@ def _build_files_manifest_distlib(b_collection_path, namespace, name, manifest_c
             )
 
         manifest['files'].append(manifest_entry)
-
     return manifest
 
 
@@ -1297,7 +1304,7 @@ def _build_collection_tar(
         file_manifest,  # type: FilesManifestType
 ):  # type: (...) -> str
     """Build a tar.gz collection artifact from the manifest data."""
-    files_manifest_json = to_bytes(json.dumps(file_manifest, indent=True), errors='surrogate_or_strict')
+    files_manifest_json = to_bytes(json.dumps(file_manifest, indent=True, sort_keys=True), errors='surrogate_or_strict')
     collection_manifest['file_manifest_file']['chksum_sha256'] = secure_hash_s(files_manifest_json, hash_func=sha256)
     collection_manifest_json = to_bytes(json.dumps(collection_manifest, indent=True), errors='surrogate_or_strict')
 
@@ -1369,7 +1376,7 @@ def _build_collection_dir(b_collection_path, b_collection_output, collection_man
     """
     os.makedirs(b_collection_output, mode=S_IRWXU_RXG_RXO)
 
-    files_manifest_json = to_bytes(json.dumps(file_manifest, indent=True), errors='surrogate_or_strict')
+    files_manifest_json = to_bytes(json.dumps(file_manifest, indent=True, sort_keys=True), errors='surrogate_or_strict')
     collection_manifest['file_manifest_file']['chksum_sha256'] = secure_hash_s(files_manifest_json, hash_func=sha256)
     collection_manifest_json = to_bytes(json.dumps(collection_manifest, indent=True), errors='surrogate_or_strict')
 
@@ -1382,7 +1389,7 @@ def _build_collection_dir(b_collection_path, b_collection_output, collection_man
         os.chmod(b_path, S_IRWU_RG_RO)
 
     base_directories = []
-    for file_info in sorted(file_manifest['files'], key=lambda x: x['name']):
+    for file_info in file_manifest['files']:
         if file_info['name'] == '.':
             continue
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
