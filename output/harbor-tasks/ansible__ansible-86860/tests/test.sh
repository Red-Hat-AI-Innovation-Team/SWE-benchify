#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/git/tasks/localmods.yml b/test/integration/targets/git/tasks/localmods.yml
index 57e3071007f8de..a3e8ea625453ab 100644
--- a/test/integration/targets/git/tasks/localmods.yml
+++ b/test/integration/targets/git/tasks/localmods.yml
@@ -132,3 +132,160 @@
 
 - name: LOCALMODS | clear checkout_dir
   file: state=absent path={{ checkout_dir }}
+
+# Regression test for https://github.com/ansible/ansible/issues/83367
+- name: Check that commits aren'"'"'t overwritten
+  vars:
+    branch: "testbranch"
+  block:
+  - name: LOCALMODS | create branch on remote
+    shell: |
+      git checkout -b {{ branch }}
+      echo "remote" > c
+      git add c
+      git commit -m "remote branch"
+    args:
+      chdir: "{{ repo_dir }}/localmods"
+
+  - name: LOCALMODS | checkout repo with branch
+    git:
+      repo: '"'"'{{ repo_dir }}/localmods'"'"'
+      dest: '"'"'{{ checkout_dir }}'"'"'
+      version: '"'"'{{ branch }}'"'"'
+
+  - name: LOCALMODS | make local commit
+    shell: |
+      echo "local" > b
+      git add b
+      git commit -m "local"
+      git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: local_commit
+
+  - name: LOCALMODS | rerun git module without force (should fail)
+    git:
+      repo: '"'"'{{ repo_dir }}/localmods'"'"'
+      dest: '"'"'{{ checkout_dir }}'"'"'
+      version: '"'"'{{ branch }}'"'"'
+    register: rerun_no_force
+    ignore_errors: yes
+
+  - name: LOCALMODS | assert task failed with local commits ahead
+    assert:
+      that:
+        - rerun_no_force is failed
+
+  - name: LOCALMODS | verify local commit still exists after failed run
+    shell: git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: commit_after_fail
+
+  - name: LOCALMODS | assert local commit preserved after failure
+    assert:
+      that:
+        - local_commit.stdout_lines[-1] == commit_after_fail.stdout
+
+  - name: LOCALMODS | rerun git module with force (should succeed and reset)
+    git:
+      repo: '"'"'{{ repo_dir }}/localmods'"'"'
+      dest: '"'"'{{ checkout_dir }}'"'"'
+      version: '"'"'{{ branch }}'"'"'
+      force: yes
+    register: rerun_with_force
+
+  - name: LOCALMODS | get remote commit hash
+    shell: git rev-parse origin/{{ branch }}
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: remote_commit
+
+  - name: LOCALMODS | verify local commit was reset
+    shell: git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: commit_after_force
+
+  - name: LOCALMODS | assert force reset to remote
+    assert:
+      that:
+        - local_commit.stdout_lines[-1] != commit_after_force.stdout
+        - commit_after_force.stdout == remote_commit.stdout
+        - rerun_with_force is changed
+
+  - name: LOCALMODS | make remote commit to create diverged state
+    shell: |
+      echo "remote2" > d
+      git add d
+      git commit -m "remote commit 2"
+    args:
+      chdir: "{{ repo_dir }}/localmods"
+
+  - name: LOCALMODS | make local commit to complete diverged state
+    shell: |
+      echo "local2" > e
+      git add e
+      git commit -m "local commit 2"
+      git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: diverged_local_commit
+
+  - name: LOCALMODS | rerun git module with diverged branches without force (should fail)
+    git:
+      repo: '"'"'{{ repo_dir }}/localmods'"'"'
+      dest: '"'"'{{ checkout_dir }}'"'"'
+      version: '"'"'{{ branch }}'"'"'
+    register: diverged_no_force
+    ignore_errors: yes
+
+  - name: LOCALMODS | assert task failed with diverged branches
+    assert:
+      that:
+        - diverged_no_force is failed
+        - "'"'"'local commits will be lost'"'"' in diverged_no_force.msg"
+
+  - name: LOCALMODS | verify local commit still exists after diverged failure
+    shell: git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: commit_after_diverged_fail
+
+  - name: LOCALMODS | assert local commit preserved after diverged failure
+    assert:
+      that:
+        - diverged_local_commit.stdout_lines[-1] == commit_after_diverged_fail.stdout
+
+  - name: LOCALMODS | rerun git module with diverged branches with force (should succeed)
+    git:
+      repo: '"'"'{{ repo_dir }}/localmods'"'"'
+      dest: '"'"'{{ checkout_dir }}'"'"'
+      version: '"'"'{{ branch }}'"'"'
+      force: yes
+    register: diverged_with_force
+
+  - name: LOCALMODS | get remote commit after diverged force
+    shell: git rev-parse origin/{{ branch }}
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: remote_after_diverged
+
+  - name: LOCALMODS | verify diverged branch was reset with force
+    shell: git rev-parse HEAD
+    args:
+      chdir: "{{ checkout_dir }}"
+    register: commit_after_diverged_force
+
+  - name: LOCALMODS | assert force reset diverged branch to remote
+    assert:
+      that:
+        - diverged_local_commit.stdout_lines[-1] != commit_after_diverged_force.stdout
+        - commit_after_diverged_force.stdout == remote_after_diverged.stdout
+        - diverged_with_force is changed
+
+  always:
+  - name: LOCALMODS | cleanup checkout_dir
+    file: 
+       state: absent
+       path: "{{ checkout_dir }}"
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/git/tasks/localmods.yml 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/modules/test_git.py::TestSwitchVersionLocalCommitsAhead::test_local_branch_ahead_without_force_should_fail", "test/units/modules/test_git.py::TestSwitchVersionLocalCommitsAhead::test_local_branch_ahead_with_force_should_reset", "test/units/modules/test_git.py::TestSwitchVersionLocalCommitsAhead::test_local_branch_diverged_without_force_should_fail", "test/units/modules/test_git.py::TestSwitchVersionLocalCommitsAhead::test_local_branch_up_to_date_without_force_should_succeed", "test/units/modules/test_git.py::TestSwitchVersionLocalCommitsAhead::test_switch_version_force_parameter_exists"]
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
