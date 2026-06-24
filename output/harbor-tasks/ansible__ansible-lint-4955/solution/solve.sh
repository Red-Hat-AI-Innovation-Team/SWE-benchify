#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/.pre-commit-config.yaml b/.pre-commit-config.yaml
index a47f693bc9..c6a2649dde 100644
--- a/.pre-commit-config.yaml
+++ b/.pre-commit-config.yaml
@@ -116,7 +116,7 @@ repos:
       - id: trailing-whitespace
         exclude: >
           (?x)^(
-            examples/playbooks/(with-skip-tag-id|unicode).yml|
+            examples/playbooks/(with-skip-tag-id|unicode|with-multiple-yaml-violations).yml|
             examples/playbooks/example.yml|
             examples/yamllint/.*|
             test/eco/.*.result|
diff --git a/examples/playbooks/with-multiple-yaml-violations.yml b/examples/playbooks/with-multiple-yaml-violations.yml
new file mode 100644
index 0000000000..7f34dc3253
--- /dev/null
+++ b/examples/playbooks/with-multiple-yaml-violations.yml
@@ -0,0 +1,6 @@
+---
+- hosts: all
+  tasks:
+    - name: Trailing whitespace on this line      
+      ansible.builtin.debug:
+        msg :  "Too many spaces around colon"
diff --git a/src/ansiblelint/rules/__init__.py b/src/ansiblelint/rules/__init__.py
index 6ec7705b87..6584333fe2 100644
--- a/src/ansiblelint/rules/__init__.py
+++ b/src/ansiblelint/rules/__init__.py
@@ -506,7 +506,6 @@ def run(
                 continue
 
             is_targeted = any(t.startswith(f"{rule.id}[") for t in tags)
-            is_skipped = any(t.startswith(f"{rule.id}[") for t in skip_list)
 
             # rule selection logic
             if (
@@ -525,7 +524,7 @@ def run(
 
                 # rule-level skip check
                 rule_definition = set(rule.tags) | {rule.id}
-                if rule_definition.isdisjoint(skip_list) and not is_skipped:
+                if rule_definition.isdisjoint(skip_list):
                     matches.extend(rule.getmatches(file))
 
         if tags or skip_list:
@@ -544,7 +543,8 @@ def run(
                         filtered_matches.append(m)
                 else:
                     # no tags requested, so keep everything that wasn't skipped
-                    filtered_matches.append(m)
+                    if m.tag not in skip_list:
+                        filtered_matches.append(m)
             matches = filtered_matches
 
         return matches
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
