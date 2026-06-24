#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/86920-fix-run-command-none-read.yml b/changelogs/fragments/86920-fix-run-command-none-read.yml
new file mode 100644
index 00000000000000..b8bf56f5a88a8f
--- /dev/null
+++ b/changelogs/fragments/86920-fix-run-command-none-read.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - module_utils/basic.py - Fix ``AnsibleModule.run_command()`` to handle ``None`` return from non-blocking pipe reads (https://github.com/ansible/ansible/issues/86920).
diff --git a/lib/ansible/module_utils/basic.py b/lib/ansible/module_utils/basic.py
index 9b5d634f0cc7e0..f852fb5c7399f1 100644
--- a/lib/ansible/module_utils/basic.py
+++ b/lib/ansible/module_utils/basic.py
@@ -2092,7 +2092,13 @@ def preexec():
                 stdout_changed = False
                 for key, event in events:
                     b_chunk = key.fileobj.read(32768)
-                    if not b_chunk and b_chunk is not None:
+                    if b_chunk is None:
+                        # Non-blocking read returned None (no data currently available).
+                        # This can happen with certain file-like objects or in edge cases.
+                        # Skip this chunk and try again on next select iteration.
+                        continue
+                    if not b_chunk:
+                        # Empty bytes received, EOF reached
                         selector.unregister(key.fileobj)
                     elif key.fileobj == cmd.stdout:
                         stdout += b_chunk
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
