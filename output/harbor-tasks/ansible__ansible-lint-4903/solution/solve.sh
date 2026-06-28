#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/cli.py b/src/ansiblelint/cli.py
index c2f4914783..b22e2decb3 100644
--- a/src/ansiblelint/cli.py
+++ b/src/ansiblelint/cli.py
@@ -538,7 +538,13 @@ def merge_config(file_config: dict[Any, Any], cli_config: Options) -> Options:
 
     for entry in bools:
         file_value = file_config.pop(entry, False)
-        v = getattr(cli_config, entry) or file_value
+        v = getattr(cli_config, entry)
+        if (
+            not v
+            and entry not in sys.argv
+            and f"--no-{entry.replace('_', '-')}" not in sys.argv
+        ):
+            v = file_value
         setattr(cli_config, entry, v)
 
     for entry, default_scalar in scalar_map.items():
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
