#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/copy/files/subdir_with_deep_single_file/dir/file.txt b/test/integration/targets/copy/files/subdir_with_deep_single_file/dir/file.txt
new file mode 100644
index 00000000000000..e69de29bb2d1d6
diff --git a/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml b/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml
new file mode 100644
index 00000000000000..e5ce4c6b20eb22
--- /dev/null
+++ b/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml
@@ -0,0 +1,29 @@
+# Test copying to a source directory that contains only a single file in a deeper structure
+
+- name: Ensure that dest top directory doesn'"'"'t exist
+  file:
+    path: '"'"'{{ remote_dir }}/subdir_with_deep_single_file'"'"'
+    state: absent
+
+- name: Copy subdir_with_deep_single_file directory which contains a single file
+  copy:
+    src: subdir_with_deep_single_file
+    dest: '"'"'{{ remote_dir }}'"'"'
+  register: copy_result
+
+- name: Debug copy result
+  debug:
+    var: copy_result
+    verbosity: 1
+
+- name: Check the transferred file
+  stat:
+    path: '"'"'{{ remote_dir }}/subdir_with_deep_single_file/dir/file.txt'"'"'
+  register: stat_file
+
+- name: Assert that transferred file exists and copy_result is as expected for deeper structure
+  assert:
+    that:
+      - '"'"'stat_file.stat.exists'"'"'
+      - '"'"'copy_result.changed'"'"'
+      - '"'"'copy_result.dest == remote_dir + "/subdir_with_deep_single_file/dir/file.txt"'"'"'
diff --git a/test/integration/targets/copy/tasks/tests.yml b/test/integration/targets/copy/tasks/tests.yml
index 44067ae319ffc7..318db1ea2c36b3 100644
--- a/test/integration/targets/copy/tasks/tests.yml
+++ b/test/integration/targets/copy/tasks/tests.yml
@@ -2531,3 +2531,5 @@
         state: absent
       loop:
         - '"'"'{{ remote_file }}'"'"'
+
+- include_tasks: src_directory_contaning_one_single_file.yml
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml test/integration/targets/copy/tasks/tests.yml 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml::Assert that transferred file exists and copy_result is as expected for deeper structure"]
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
