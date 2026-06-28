#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/__main__.py b/src/ansiblelint/__main__.py
index f763d8b33f..a88dd5ce13 100755
--- a/src/ansiblelint/__main__.py
+++ b/src/ansiblelint/__main__.py
@@ -393,9 +393,6 @@ def main(argv: list[str] | None = None) -> int:
 
     mark_as_success = True
 
-    if options.strict and result.matches:
-        mark_as_success = False
-
     # Remove skip_list items from the result
     result.matches = [m for m in result.matches if m.tag not in app.options.skip_list]
     # load ignore file
@@ -404,6 +401,12 @@ def main(argv: list[str] | None = None) -> int:
     result.matches = [
         m for m in result.matches if not _rule_is_skipped(m.tag, ignore_map[m.filename])
     ]
+
+    # For strict option, decide of success or failure after we have pruned the skipped ones
+    # from both the skip_list and the ignore file.
+    if options.strict and result.matches:
+        mark_as_success = False
+
     # others entries are ignored
     for match in result.matches:
         if match.tag in [
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
