#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/display_included_hosts.yml b/changelogs/fragments/display_included_hosts.yml
new file mode 100644
index 00000000000000..b1dad766145c7b
--- /dev/null
+++ b/changelogs/fragments/display_included_hosts.yml
@@ -0,0 +1,2 @@
+minor_changes:
+  - default callback - add ``display_included_hosts`` option to control the ``included:`` banner lines for ``include_tasks``/``include_role`` (https://github.com/ansible/ansible/issues/84499).
diff --git a/lib/ansible/plugins/callback/default.py b/lib/ansible/plugins/callback/default.py
index 5032d917c429be..71d8b99c4884c0 100644
--- a/lib/ansible/plugins/callback/default.py
+++ b/lib/ansible/plugins/callback/default.py
@@ -293,6 +293,9 @@ def v2_runner_item_on_skipped(self, result: CallbackTaskResult) -> None:
             self._display.display(msg, color=C.COLOR_SKIP)
 
     def v2_playbook_on_include(self, included_file):
+        if not self.get_option("display_included_hosts"):
+            return
+
         msg = 'included: %s for %s' % (included_file._filename, ", ".join([h.name for h in included_file._hosts]))
         label = self._get_item_label(included_file._vars)
         if label:
diff --git a/lib/ansible/plugins/doc_fragments/default_callback.py b/lib/ansible/plugins/doc_fragments/default_callback.py
index 228fa168a1e27b..2b3615147a0492 100644
--- a/lib/ansible/plugins/doc_fragments/default_callback.py
+++ b/lib/ansible/plugins/doc_fragments/default_callback.py
@@ -44,6 +44,17 @@ class ModuleDocFragment(object):
           - key: display_failed_stderr
             section: defaults
         version_added: '2.7'
+      display_included_hosts:
+        name: Show included hosts
+        description: "Toggle to control displaying included task/host results in a task."
+        type: bool
+        default: yes
+        env:
+          - name: ANSIBLE_DISPLAY_INCLUDED_HOSTS
+        ini:
+          - key: display_included_hosts
+            section: defaults
+        version_added: '2.21'
       show_custom_stats:
         name: Show custom stats
         description: 'This adds the custom stats set via the set_stats plugin to the play recap.'
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
