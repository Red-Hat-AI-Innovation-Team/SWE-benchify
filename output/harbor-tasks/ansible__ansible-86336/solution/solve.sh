#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/85834-fix-copy-in-single-file-directory.yml b/changelogs/fragments/85834-fix-copy-in-single-file-directory.yml
new file mode 100644
index 00000000000000..e19a3f4c273602
--- /dev/null
+++ b/changelogs/fragments/85834-fix-copy-in-single-file-directory.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - "copy - when a single-file local directory was specified as the source, ``changed`` used to be ``false`` even when the source was actually copied. It now makes sure ``changed`` is ``true`` in this case. (https://github.com/ansible/ansible/issues/85833)"
diff --git a/lib/ansible/plugins/action/copy.py b/lib/ansible/plugins/action/copy.py
index 89a6a8f1f95aff..d3c1f0b2fc4a07 100644
--- a/lib/ansible/plugins/action/copy.py
+++ b/lib/ansible/plugins/action/copy.py
@@ -529,11 +529,9 @@ def run(self, tmp=None, task_vars=None):
                 result.update(module_return)
                 return self._ensure_invocation(result)
 
-            paths = os.path.split(source_rel)
-            dir_path = ''
-            for dir_component in paths:
-                os.path.join(dir_path, dir_component)
-                implicit_directories.add(dir_path)
+            while (source_rel := os.path.dirname(source_rel)) != '':
+                implicit_directories.add(source_rel)
+
             if 'diff' in result and not result['diff']:
                 del result['diff']
             module_executed = True
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
