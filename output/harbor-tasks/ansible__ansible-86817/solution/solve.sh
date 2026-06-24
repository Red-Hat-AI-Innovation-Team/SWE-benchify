#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/start-at-task-fact-gathering.yml b/changelogs/fragments/start-at-task-fact-gathering.yml
new file mode 100644
index 00000000000000..685dc26decb947
--- /dev/null
+++ b/changelogs/fragments/start-at-task-fact-gathering.yml
@@ -0,0 +1,9 @@
+bugfixes:
+- >-
+  ``--start-at-task`` - fix starting at the requested task
+  instead of starting at the next block or play. Play level
+  tasks run first.
+  (https://github.com/ansible/ansible/issues/86268)
+- >-
+  Fix ``validate_argspec`` when tags are defined on the play.
+  The ``always`` tag is only added if the play has no tags.
diff --git a/lib/ansible/executor/play_iterator.py b/lib/ansible/executor/play_iterator.py
index 88c7641b32e8a1..78d95719eb0377 100644
--- a/lib/ansible/executor/play_iterator.py
+++ b/lib/ansible/executor/play_iterator.py
@@ -42,6 +42,7 @@ class IteratingStates(IntEnum):
     ALWAYS = 3
     HANDLERS = 4
     COMPLETE = 5
+    VALIDATE = 6
 
 
 class FailedStates(IntFlag):
@@ -51,6 +52,7 @@ class FailedStates(IntFlag):
     RESCUE = 4
     ALWAYS = 8
     HANDLERS = 16  # NOTE not in use anymore
+    VALIDATE = 32
 
 
 class HostState:
@@ -69,7 +71,6 @@ def __init__(self, blocks):
         self.fail_state = FailedStates.NONE
         self.pre_flushing_run_state = None
         self.update_handlers = True
-        self.pending_setup = False
         self.tasks_child_state = None
         self.rescue_child_state = None
         self.always_child_state = None
@@ -81,7 +82,7 @@ def __repr__(self):
 
     def __str__(self):
         return ("HOST STATE: block=%d, task=%d, rescue=%d, always=%d, handlers=%d, run_state=%s, fail_state=%s, "
-                "pre_flushing_run_state=%s, update_handlers=%s, pending_setup=%s, "
+                "pre_flushing_run_state=%s, update_handlers=%s, "
                 "tasks child state? (%s), rescue child state? (%s), always child state? (%s), "
                 "did rescue? %s, did start at task? %s" % (
                     self.cur_block,
@@ -93,7 +94,6 @@ def __str__(self):
                     self.fail_state,
                     self.pre_flushing_run_state,
                     self.update_handlers,
-                    self.pending_setup,
                     self.tasks_child_state,
                     self.rescue_child_state,
                     self.always_child_state,
@@ -107,7 +107,7 @@ def __eq__(self, other):
 
         for attr in ('_blocks',
                      'cur_block', 'cur_regular_task', 'cur_rescue_task', 'cur_always_task', 'cur_handlers_task',
-                     'run_state', 'fail_state', 'pre_flushing_run_state', 'update_handlers', 'pending_setup',
+                     'run_state', 'fail_state', 'pre_flushing_run_state', 'update_handlers',
                      'tasks_child_state', 'rescue_child_state', 'always_child_state'):
             if getattr(self, attr) != getattr(other, attr):
                 return False
@@ -130,7 +130,6 @@ def copy(self):
         new_state.fail_state = self.fail_state
         new_state.pre_flushing_run_state = self.pre_flushing_run_state
         new_state.update_handlers = self.update_handlers
-        new_state.pending_setup = self.pending_setup
         new_state.did_rescue = self.did_rescue
         new_state.did_start_at_task = self.did_start_at_task
         if self.tasks_child_state is not None:
@@ -187,7 +186,7 @@ def __init__(self, inventory, play, play_context, variable_manager, all_vars, st
                     'path': self._play._metadata_path,
                 },
             },
-            'tags': ['always'],
+            'tags': ['always'] if not self._play.tags else [],
         }, block=setup_block)
 
         validation_task.set_loader(self._play._loader)
@@ -292,51 +291,37 @@ def _get_next_task_from_state(self, state, host):
                 return (state, None)
 
             if state.run_state == IteratingStates.SETUP:
-                # First, we check to see if we completed both setup tasks injected
-                # during play compilation in __init__ above.
-                # If not, below we will determine if we do in fact want to gather
-                # facts or validate arguments for the specified host.
-                state.pending_setup = state.cur_regular_task < len(block.block)
-                if state.pending_setup:
-                    task = block.block[state.cur_regular_task]
-
-                    # Gather facts if the default is 'smart' and we have not yet
-                    # done it for this host; or if 'explicit' and the play sets
-                    # gather_facts to True; or if 'implicit' and the play does
-                    # NOT explicitly set gather_facts to False.
-                    gather_facts = bool(state.cur_regular_task == 0)
-                    gathering = C.DEFAULT_GATHERING
-                    implied = self._play.gather_facts is None or boolean(self._play.gather_facts, strict=False)
-
-                    if gather_facts and not (
-                        (gathering == 'implicit' and implied) or
-                        (gathering == 'explicit' and boolean(self._play.gather_facts, strict=False)) or
-                        (gathering == 'smart' and implied and not self._variable_manager._facts_gathered_for_host(host.name))
-                    ):
-                        task = None
-                    elif not gather_facts and not self._play.validate_argspec:
-                        task = None
+                # Gather facts if the default is 'smart' and we have not yet
+                # done it for this host; or if 'explicit' and the play sets
+                # gather_facts to True; or if 'implicit' and the play does
+                # NOT explicitly set gather_facts to False.
+                gather_facts = len(self._blocks[0].block) >= 1
+                gathering = C.DEFAULT_GATHERING
+                implied = self._play.gather_facts is None or boolean(self._play.gather_facts, strict=False)
+                if gather_facts and (
+                    (gathering == 'implicit' and implied) or
+                    (gathering == 'explicit' and boolean(self._play.gather_facts, strict=False)) or
+                    (gathering == 'smart' and implied and not self._variable_manager._facts_gathered_for_host(host.name))
+                ):
+                    task = self._blocks[0].block[0]
 
-                    state.cur_regular_task += 1
-                else:
-                    # This is the last trip through IteratingStates.SETUP, so we
-                    # move onto the next block in the list while setting the run
-                    # state to IteratingStates.TASKS
-                    state.run_state = IteratingStates.TASKS
-                    if not state.did_start_at_task:
-                        state.cur_block += 1
-                        state.cur_regular_task = 0
-                        state.cur_rescue_task = 0
-                        state.cur_always_task = 0
-                        state.tasks_child_state = None
-                        state.rescue_child_state = None
-                        state.always_child_state = None
+                state.run_state = IteratingStates.VALIDATE
 
-            elif state.run_state == IteratingStates.TASKS:
-                # clear the pending setup flag, since we're past that and it didn't fail
-                if state.pending_setup:
-                    state.pending_setup = False
+            elif state.run_state == IteratingStates.VALIDATE:
+                if len(self._blocks[0].block) >= 2 and self._play.validate_argspec:
+                    task = self._blocks[0].block[1]
+
+                state.run_state = IteratingStates.TASKS
+                if not state.did_start_at_task:
+                    state.cur_block += 1
+                    state.cur_regular_task = 0
+                    state.cur_rescue_task = 0
+                    state.cur_always_task = 0
+                    state.tasks_child_state = None
+                    state.rescue_child_state = None
+                    state.always_child_state = None
 
+            elif state.run_state == IteratingStates.TASKS:
                 # First, we check for a child task state that is not failed, and if we
                 # have one recurse into it for the next task. If we're done with the child
                 # state, we clear it and drop back to getting the next task from the list.
@@ -496,6 +481,9 @@ def _set_failed_state(self, state):
         if state.run_state == IteratingStates.SETUP:
             state.fail_state |= FailedStates.SETUP
             state.run_state = IteratingStates.COMPLETE
+        elif state.run_state == IteratingStates.VALIDATE:
+            state.fail_state |= FailedStates.VALIDATE
+            state.run_state = IteratingStates.COMPLETE
         elif state.run_state == IteratingStates.TASKS:
             if state.tasks_child_state is not None:
                 state.tasks_child_state = self._set_failed_state(state.tasks_child_state)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
