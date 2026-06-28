#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/86341-galaxy-list-warn.yml b/changelogs/fragments/86341-galaxy-list-warn.yml
new file mode 100644
index 00000000000000..ce837cab469093
--- /dev/null
+++ b/changelogs/fragments/86341-galaxy-list-warn.yml
@@ -0,0 +1,2 @@
+bugfixes:
+   - ansible-galaxy - warn instead of raising an error when no valid role or collections paths exist (https://github.com/ansible/ansible/pull/86341)
diff --git a/lib/ansible/cli/galaxy.py b/lib/ansible/cli/galaxy.py
index 5d85a57bbf1f14..fa418a32bd307a 100755
--- a/lib/ansible/cli/galaxy.py
+++ b/lib/ansible/cli/galaxy.py
@@ -1610,8 +1610,8 @@ def execute_list_role(self):
             display.warning(w)
 
         if not path_found:
-            raise AnsibleOptionsError(
-                "- None of the provided paths were usable. Please specify a valid path with --{0}s-path".format(context.CLIARGS['type'])
+            display.warning(
+                "None of the provided paths were usable. Please specify a valid path with --{0}s-path.".format(context.CLIARGS['type'])
             )
 
         return 0
@@ -1695,8 +1695,8 @@ def execute_list_collection(self, artifacts_manager=None):
             display.warning(w)
 
         if not collections and not path_found:
-            raise AnsibleOptionsError(
-                "- None of the provided paths were usable. Please specify a valid path with --{0}s-path".format(context.CLIARGS['type'])
+            display.warning(
+                "None of the provided paths were usable. Please specify a valid path with --{0}s-path.".format(context.CLIARGS['type'])
             )
 
         if output_format == 'json':
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
