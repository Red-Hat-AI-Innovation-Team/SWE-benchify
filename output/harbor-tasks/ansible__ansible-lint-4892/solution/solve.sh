#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/rules/__init__.py b/src/ansiblelint/rules/__init__.py
index 069439bb31..6ec7705b87 100644
--- a/src/ansiblelint/rules/__init__.py
+++ b/src/ansiblelint/rules/__init__.py
@@ -504,27 +504,48 @@ def run(
         for rule in self.rules:
             if rule.id == "syntax-check":
                 continue
+
+            is_targeted = any(t.startswith(f"{rule.id}[") for t in tags)
+            is_skipped = any(t.startswith(f"{rule.id}[") for t in skip_list)
+
+            # rule selection logic
             if (
                 not tags
                 or rule.has_dynamic_tags
                 or not set(rule.tags).union([rule.id]).isdisjoint(tags)
+                or is_targeted
             ):
-                if tags and set(rule.tags).union(list(rule.ids().keys())).isdisjoint(
-                    tags,
+                # specific tag targeting override
+                if (
+                    tags
+                    and not is_targeted
+                    and set(rule.tags).union(list(rule.ids().keys())).isdisjoint(tags)
                 ):
-                    _logger.debug("Skipping rule %s", rule.id)
-                else:
-                    _logger.debug("Running rule %s", rule.id)
-                    rule_definition = set(rule.tags)
-                    rule_definition.add(rule.id)
-                    if set(rule_definition).isdisjoint(skip_list):
-                        matches.extend(rule.getmatches(file))
-            else:
-                _logger.debug("Skipping rule %s", rule.id)
+                    continue
 
-        # some rules can produce matches with tags that are inside our
-        # skip_list, so we need to cleanse the matches
-        matches = [m for m in matches if m.tag not in skip_list]
+                # rule-level skip check
+                rule_definition = set(rule.tags) | {rule.id}
+                if rule_definition.isdisjoint(skip_list) and not is_skipped:
+                    matches.extend(rule.getmatches(file))
+
+        if tags or skip_list:
+            filtered_matches = []
+            for m in matches:
+                # inclusion logic (if tags are provided)
+                if tags:
+                    if (
+                        m.tag in tags
+                        or m.rule.id in tags
+                        or (
+                            not set(m.rule.tags).isdisjoint(tags)
+                            and not any(t.startswith(f"{m.rule.id}[") for t in tags)
+                        )
+                    ):
+                        filtered_matches.append(m)
+                else:
+                    # no tags requested, so keep everything that wasn't skipped
+                    filtered_matches.append(m)
+            matches = filtered_matches
 
         return matches
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
