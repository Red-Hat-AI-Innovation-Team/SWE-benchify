#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/yaml_utils.py b/src/ansiblelint/yaml_utils.py
index e321dbd6f5..70a7b2d163 100644
--- a/src/ansiblelint/yaml_utils.py
+++ b/src/ansiblelint/yaml_utils.py
@@ -704,7 +704,10 @@ def increase_indent(
         super().increase_indent(flow, sequence, indentless)
         # If our previous node was a sequence and we are still trying to indent, don't
         if self.indents.last_seq():
-            self.indent = self.column + 1
+            if self.event and getattr(self.event, "anchor", None):
+                self.indent = self.best_sequence_indent - self.sequence_dash_offset
+            else:
+                self.indent = self.column + 1
 
     def write_indicator(
         self,
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
