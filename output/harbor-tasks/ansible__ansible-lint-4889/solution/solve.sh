#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/file_utils.py b/src/ansiblelint/file_utils.py
index 90d866986e..5e52e61951 100644
--- a/src/ansiblelint/file_utils.py
+++ b/src/ansiblelint/file_utils.py
@@ -134,9 +134,17 @@ def kind_from_path(path: Path, *, base: bool = False) -> FileType:
     When called with base=True, it will return the base file type instead
     of the explicit one. That is expected to return 'yaml' for any yaml files.
     """
-    # pathlib.Path.match patterns are very limited, they do not support *a*.yml
-    # glob.glob supports **/foo.yml but not multiple extensions
-    pathex = wcmatch.pathlib.PurePath(str(path.absolute().resolve()))
+    # We attempt to use a relative path to the project root for glob matching.
+    # This prevents parent directory names (like 'tasks') from triggering
+    # false positives in kind discovery. See #4763.
+    try:
+        project_root, _ = find_project_root([str(path)])
+        # .resolve() ensures we handle symlinks and double-dots correctly
+        rel_path = path.resolve().relative_to(project_root.resolve())
+        pathex = wcmatch.pathlib.PurePath(str(rel_path))
+    except (ValueError, RuntimeError):
+        # Fallback to absolute if the file is outside the project root or can't be found
+        pathex = wcmatch.pathlib.PurePath(str(path.absolute().resolve()))
     kinds = options.kinds if not base else BASE_KINDS
     for entry in kinds:
         for k, v in entry.items():
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
