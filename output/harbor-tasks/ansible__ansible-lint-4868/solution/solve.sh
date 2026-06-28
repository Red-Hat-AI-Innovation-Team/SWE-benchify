#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/examples/playbooks/transform-yaml-comments.transformed.yml b/examples/playbooks/transform-yaml-comments.transformed.yml
index bcc57e29c7..ab58106cd5 100644
--- a/examples/playbooks/transform-yaml-comments.transformed.yml
+++ b/examples/playbooks/transform-yaml-comments.transformed.yml
@@ -1,5 +1,7 @@
 ---
 # comment without space
+#
+# second comment after blank
 - name: Fixture
   hosts: localhost
   tasks:
diff --git a/examples/playbooks/transform-yaml-comments.yml b/examples/playbooks/transform-yaml-comments.yml
index 71a90dff99..a22ed323de 100644
--- a/examples/playbooks/transform-yaml-comments.yml
+++ b/examples/playbooks/transform-yaml-comments.yml
@@ -1,5 +1,7 @@
 ---
 #comment without space
+#
+#second comment after blank
 - name: Fixture
   hosts: localhost
   tasks:
diff --git a/src/ansiblelint/yaml_utils.py b/src/ansiblelint/yaml_utils.py
index ab311fc441..e321dbd6f5 100644
--- a/src/ansiblelint/yaml_utils.py
+++ b/src/ansiblelint/yaml_utils.py
@@ -826,7 +826,7 @@ def write_comment(
             value = self._re_repeat_blank_lines.sub("\n\n", value)
 
         # make sure that comments have a space after #
-        if value.startswith("#") and not value.startswith("# ") and len(value) > 1:
+        if value.startswith("#") and not value.startswith("# ") and value[1:].strip():
             value = "# " + value[1:]
 
         comment.value = value
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
