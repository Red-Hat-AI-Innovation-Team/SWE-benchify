#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/play_arg_spec/tasks/main.yml b/test/integration/targets/play_arg_spec/tasks/main.yml
index 2d49cf6af4e9f3..6afca13080c74d 100644
--- a/test/integration/targets/play_arg_spec/tasks/main.yml
+++ b/test/integration/targets/play_arg_spec/tasks/main.yml
@@ -186,12 +186,12 @@
   vars:
     playbook_name: tagged_play
 
-- name: Test validation always runs otherwise
-  command: ansible-playbook {{ playbook }} --tags task_level_tag -e '"'"'required_str="success"'"'"'
+- name: Test validation only runs when the play tag runs
+  command: ansible-playbook {{ playbook }} --tags mismatch
   vars:
     playbook_name: tagged_play
   register: result
 
 - assert:
     that:
-      - result.stdout is search("Validating arguments against arg spec Tagged Play")
+      - result.stdout is not search("Validating arguments against arg spec Tagged Play")
diff --git a/test/integration/targets/play_iterator/playbook.meta.yml b/test/integration/targets/play_iterator/playbook.meta.yml
new file mode 100644
index 00000000000000..4f0a847feee763
--- /dev/null
+++ b/test/integration/targets/play_iterator/playbook.meta.yml
@@ -0,0 +1,3 @@
+argument_specs:
+  test:
+    options: {}
diff --git a/test/integration/targets/play_iterator/playbook.yml b/test/integration/targets/play_iterator/playbook.yml
index 76100c6089c896..3a4449c4c7800b 100644
--- a/test/integration/targets/play_iterator/playbook.yml
+++ b/test/integration/targets/play_iterator/playbook.yml
@@ -1,10 +1,15 @@
 ---
 - hosts: localhost
-  gather_facts: false
+  gather_facts: "{{ setup | default(False) }}"
+  validate_argspec: "{{ spec | default(omit) }}"
   tasks:
-    - name:
-      debug:
-        msg: foo
+    - name: "task 1"
+      fail:
+
     - name: "task 2"
       debug:
         msg: bar
+
+    - assert:
+        that: ansible_facts.gather_subset == ["all"]
+      when: setup | default(False)
diff --git a/test/integration/targets/play_iterator/runme.sh b/test/integration/targets/play_iterator/runme.sh
index 9f30d9e7a2f5f0..318ffd5e571ea2 100755
--- a/test/integration/targets/play_iterator/runme.sh
+++ b/test/integration/targets/play_iterator/runme.sh
@@ -3,3 +3,10 @@
 set -eux
 
 ansible-playbook playbook.yml --start-at-task '"'"'task 2'"'"' "$@"
+
+ansible-playbook playbook.yml --start-at-task '"'"'task 2'"'"' \
+    --extra-vars '"'"'setup="{{ True }}" spec="test"'"'"' "$@" | tee out.txt
+
+grep "TASK \[Gathering Facts\]" out.txt
+grep "TASK \[Validating arguments against arg spec test\]" out.txt
+grep "TASK \[task 2\]" out.txt
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/play_arg_spec/tasks/main.yml test/integration/targets/play_iterator/playbook.meta.yml test/integration/targets/play_iterator/playbook.yml test/integration/targets/play_iterator/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/play_iterator/runme.sh::start_at_task_with_setup_and_argspec", "test/integration/targets/play_arg_spec::tagged_play_validation_skipped_on_tag_mismatch"]
passed = set()

with open("/tmp/test_output.txt") as f:
    for line in f:
        # pytest output: "PASSED" or "FAILED" after the test ID
        m = re.match(r"^(.+?)\s+PASSED", line)
        if m:
            passed.add(m.group(1).strip())

# Also check for the short form "test_name PASSED"
# and pytest's "X passed" summary
all_pass = True
for t in f2p:
    # Check exact match or suffix match
    if t not in passed:
        # Try matching just the test function part
        found = any(t.endswith(p.split("::")[-1]) or p.endswith(t.split("::")[-1]) for p in passed)
        if not found:
            all_pass = False

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    print(f"NOT RESOLVED: some FAIL_TO_PASS tests still failing")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
