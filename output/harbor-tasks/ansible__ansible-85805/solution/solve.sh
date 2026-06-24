#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/85475-fix-flush_handlers-play-tags.yml b/changelogs/fragments/85475-fix-flush_handlers-play-tags.yml
new file mode 100644
index 00000000000000..b4994345a4a4d9
--- /dev/null
+++ b/changelogs/fragments/85475-fix-flush_handlers-play-tags.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - Fix issue where play tags prevented executing notified handlers (https://github.com/ansible/ansible/issues/85475)
diff --git a/lib/ansible/playbook/block.py b/lib/ansible/playbook/block.py
index a47bdc31e451c7..37d4fa7ebe848a 100644
--- a/lib/ansible/playbook/block.py
+++ b/lib/ansible/playbook/block.py
@@ -17,7 +17,6 @@
 
 from __future__ import annotations
 
-import ansible.constants as C
 from ansible.errors import AnsibleParserError
 from ansible.module_utils.common.sentinel import Sentinel
 from ansible.playbook.attribute import NonInheritableFieldAttribute
@@ -376,8 +375,7 @@ def evaluate_and_append_task(target):
                     filtered_block = evaluate_block(task)
                     if filtered_block.has_tasks():
                         tmp_list.append(filtered_block)
-                elif ((task.action in C._ACTION_META and task.implicit) or
-                        task.evaluate_tags(self._play.only_tags, self._play.skip_tags, all_vars=all_vars)):
+                elif task.evaluate_tags(self._play.only_tags, self._play.skip_tags, all_vars=all_vars):
                     tmp_list.append(task)
             return tmp_list
 
diff --git a/lib/ansible/playbook/play.py b/lib/ansible/playbook/play.py
index 032716e90b4459..a4a9d7adb15374 100644
--- a/lib/ansible/playbook/play.py
+++ b/lib/ansible/playbook/play.py
@@ -306,19 +306,9 @@ def compile(self):
         t.args['_raw_params'] = 'flush_handlers'
         t.implicit = True
         t.set_loader(self._loader)
+        t.tags = ['always']
 
-        if self.tags:
-            # Avoid calling flush_handlers in case the whole play is skipped on tags,
-            # this could be performance improvement since calling flush_handlers on
-            # large inventories could be expensive even if no hosts are notified
-            # since we call flush_handlers per host.
-            # Block.filter_tagged_tasks ignores evaluating tags on implicit meta
-            # tasks so we need to explicitly call Task.evaluate_tags here.
-            t.tags = self.tags
-            if t.evaluate_tags(self.only_tags, self.skip_tags, all_vars=self.vars):
-                flush_block.block = [t]
-        else:
-            flush_block.block = [t]
+        flush_block.block = [t]
 
         # NOTE keep flush_handlers tasks even if a section has no regular tasks,
         #      there may be notified handlers from the previous section
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
