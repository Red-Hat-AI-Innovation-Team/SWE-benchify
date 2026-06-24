#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/85682-rescue-flush_handlers.yml b/changelogs/fragments/85682-rescue-flush_handlers.yml
new file mode 100644
index 00000000000000..115dd4b5faf011
--- /dev/null
+++ b/changelogs/fragments/85682-rescue-flush_handlers.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - The ``ansible_failed_task`` variable is now correctly exposed in a rescue section, even when a failing handler is triggered by the ``flush_handlers`` task in the corresponding ``block`` (https://github.com/ansible/ansible/issues/85682)
diff --git a/lib/ansible/executor/play_iterator.py b/lib/ansible/executor/play_iterator.py
index 69d0b00b0e719d..de0c5f78d1b634 100644
--- a/lib/ansible/executor/play_iterator.py
+++ b/lib/ansible/executor/play_iterator.py
@@ -574,7 +574,7 @@ def is_any_block_rescuing(self, state):
         Given the current HostState state, determines if the current block, or any child blocks,
         are in rescue mode.
         """
-        if state.run_state == IteratingStates.TASKS and state.get_current_block().rescue:
+        if state.run_state in (IteratingStates.TASKS, IteratingStates.HANDLERS) and state.get_current_block().rescue:
             return True
         if state.tasks_child_state is not None:
             return self.is_any_block_rescuing(state.tasks_child_state)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
