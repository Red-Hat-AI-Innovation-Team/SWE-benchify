#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/.pre-commit-config.yaml b/.pre-commit-config.yaml
index b25c49d3c2..05d6da2915 100644
--- a/.pre-commit-config.yaml
+++ b/.pre-commit-config.yaml
@@ -135,6 +135,7 @@ repos:
         exclude: >
           (?x)^(
             examples/playbooks/templates/.*|
+            examples/playbooks/transform-yaml-comments.yml|
             examples/yamllint/.*|
             examples/other/some.j2.yaml|
             examples/playbooks/collections/.*|
diff --git a/examples/playbooks/transform-yaml-comments.transformed.yml b/examples/playbooks/transform-yaml-comments.transformed.yml
new file mode 100644
index 0000000000..bcc57e29c7
--- /dev/null
+++ b/examples/playbooks/transform-yaml-comments.transformed.yml
@@ -0,0 +1,8 @@
+---
+# comment without space
+- name: Fixture
+  hosts: localhost
+  tasks:
+    - name: Task
+      ansible.builtin.debug:
+        msg: hello # inline without space
diff --git a/examples/playbooks/transform-yaml-comments.yml b/examples/playbooks/transform-yaml-comments.yml
new file mode 100644
index 0000000000..71a90dff99
--- /dev/null
+++ b/examples/playbooks/transform-yaml-comments.yml
@@ -0,0 +1,8 @@
+---
+#comment without space
+- name: Fixture
+  hosts: localhost
+  tasks:
+    - name: Task
+      ansible.builtin.debug:
+        msg: hello #inline without space
diff --git a/src/ansiblelint/rules/yaml_rule.py b/src/ansiblelint/rules/yaml_rule.py
index ef161391e4..5dac375f98 100644
--- a/src/ansiblelint/rules/yaml_rule.py
+++ b/src/ansiblelint/rules/yaml_rule.py
@@ -104,9 +104,8 @@ def transform(
         :param lintable: Lintable instance
         :param data: data to transform
         """
-        # This method does nothing because the YAML reformatting is implemented
-        # in data dumper. Still presence of this method helps us with
-        # documentation generation.
+        if match.tag == "yaml[comments]":
+            match.fixed = True
 
 
 # testing code to be loaded only with pytest or when executed the rule file
diff --git a/src/ansiblelint/yaml_utils.py b/src/ansiblelint/yaml_utils.py
index 71d746de9d..ab311fc441 100644
--- a/src/ansiblelint/yaml_utils.py
+++ b/src/ansiblelint/yaml_utils.py
@@ -824,6 +824,11 @@ def write_comment(
         else:
             # single blank lines in post comments
             value = self._re_repeat_blank_lines.sub("\n\n", value)
+
+        # make sure that comments have a space after #
+        if value.startswith("#") and not value.startswith("# ") and len(value) > 1:
+            value = "# " + value[1:]
+
         comment.value = value
 
         # make sure that the eol comment only has one space before it.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
