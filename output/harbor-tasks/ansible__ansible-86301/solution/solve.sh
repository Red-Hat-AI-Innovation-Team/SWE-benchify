#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/ansible_local_nodepr.yml b/changelogs/fragments/ansible_local_nodepr.yml
new file mode 100644
index 00000000000000..0462c85deed742
--- /dev/null
+++ b/changelogs/fragments/ansible_local_nodepr.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - ansible_local will no longer trigger variable injection default value deprecation.
diff --git a/lib/ansible/vars/manager.py b/lib/ansible/vars/manager.py
index fb4970cd7494c5..1ee0ea6fa6ac57 100644
--- a/lib/ansible/vars/manager.py
+++ b/lib/ansible/vars/manager.py
@@ -299,7 +299,7 @@ def plugins_by_groups():
                 # push facts to main namespace
                 if inject:
                     if origin == 'default':
-                        clean_top = {k: _deprecate_top_level_fact(v) for k, v in clean_facts(facts).items()}
+                        clean_top = {k: (_deprecate_top_level_fact(v) if k != 'ansible_local' else v) for k, v in clean_facts(facts).items()}
                     else:
                         clean_top = clean_facts(facts)
                     all_vars = _combine_and_track(all_vars, clean_top, "facts")
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
