#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/85743-lazy-ternary.yml b/changelogs/fragments/85743-lazy-ternary.yml
new file mode 100644
index 00000000000000..e6e4872e6686dc
--- /dev/null
+++ b/changelogs/fragments/85743-lazy-ternary.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - "``ternary`` filter - evaluate values lazily (https://github.com/ansible/ansible/issues/85743)"
diff --git a/lib/ansible/plugins/filter/core.py b/lib/ansible/plugins/filter/core.py
index eed6511bce2430..96329d5b5b266b 100644
--- a/lib/ansible/plugins/filter/core.py
+++ b/lib/ansible/plugins/filter/core.py
@@ -220,6 +220,7 @@ def regex_search(value, regex, *args, **kwargs):
             return items
 
 
+@accept_args_markers
 def ternary(value, true_val, false_val, none_val=None):
     """  value ? true_val : false_val """
     if value is None and none_val is not None:
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
