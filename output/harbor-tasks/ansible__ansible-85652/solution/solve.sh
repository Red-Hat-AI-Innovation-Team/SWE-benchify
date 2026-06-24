#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/concat_coerce_none_to_empty.yml b/changelogs/fragments/concat_coerce_none_to_empty.yml
new file mode 100644
index 00000000000000..9fea388973ae7a
--- /dev/null
+++ b/changelogs/fragments/concat_coerce_none_to_empty.yml
@@ -0,0 +1,3 @@
+bugfixes:
+  - templating - Multi-node template results coerce embedded ``None`` nodes to empty string (instead of rendering literal ``None`` to the output).
+  - argspec validation - The ``str`` argspec type treats ``None`` values as empty string for better consistency with pre-2.19 templating conversions.
diff --git a/lib/ansible/_internal/_templating/_jinja_bits.py b/lib/ansible/_internal/_templating/_jinja_bits.py
index 1190bbef60f687..54b1eef682ddaa 100644
--- a/lib/ansible/_internal/_templating/_jinja_bits.py
+++ b/lib/ansible/_internal/_templating/_jinja_bits.py
@@ -753,7 +753,7 @@ def concat(nodes: t.Iterable[t.Any]) -> t.Any:  # type: ignore[override]
         except MarkerError as ex:
             return ex.source  # return the first Marker encountered
 
-        return ''.join([to_text(v) for v in node_list])
+        return ''.join([to_text(v) for v in node_list if v is not None])  # skip concat on `None`-valued nodes to avoid literal "None" in template results
 
     @staticmethod
     def _access_const(const_template: t.LiteralString) -> t.Any:
diff --git a/lib/ansible/module_utils/common/validation.py b/lib/ansible/module_utils/common/validation.py
index 498248c0ff32b2..81100cd5bce1fe 100644
--- a/lib/ansible/module_utils/common/validation.py
+++ b/lib/ansible/module_utils/common/validation.py
@@ -374,7 +374,10 @@ def check_type_str(value, allow_conversion=True, param=None, prefix=''):
     if isinstance(value, str):
         return value
 
-    if allow_conversion and value is not None:
+    if value is None:
+        return ''  # approximate pre-2.19 templating None->empty str equivalency here for backward compatibility
+
+    if allow_conversion:
         return to_native(value, errors='surrogate_or_strict')
 
     msg = "'{0!r}' is not a string and conversion is not allowed".format(value)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
