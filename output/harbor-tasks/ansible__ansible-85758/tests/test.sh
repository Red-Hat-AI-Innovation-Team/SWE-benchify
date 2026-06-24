#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/callback_default/callback_default.out.hide_included.stderr b/test/integration/targets/callback_default/callback_default.out.hide_included.stderr
new file mode 100644
index 00000000000000..d3e07d472db6de
--- /dev/null
+++ b/test/integration/targets/callback_default/callback_default.out.hide_included.stderr
@@ -0,0 +1,2 @@
++ ansible-playbook -i inventory test.yml
+++ set +x
diff --git a/test/integration/targets/callback_default/callback_default.out.hide_included.stdout b/test/integration/targets/callback_default/callback_default.out.hide_included.stdout
new file mode 100644
index 00000000000000..cee8802c227bff
--- /dev/null
+++ b/test/integration/targets/callback_default/callback_default.out.hide_included.stdout
@@ -0,0 +1,135 @@
+
+PLAY [testhost] ****************************************************************
+
+TASK [Changed task] ************************************************************
+changed: [testhost]
+
+TASK [Ok task] *****************************************************************
+ok: [testhost]
+
+TASK [Failed task] *************************************************************
+[ERROR]: Task failed: Action failed: no reason
+Origin: TEST_PATH/test.yml:16:7
+
+14       changed_when: false
+15
+16     - name: Failed task
+         ^ column 7
+
+fatal: [testhost]: FAILED! => {"changed": false, "msg": "no reason"}
+...ignoring
+
+TASK [Skipped task] ************************************************************
+skipping: [testhost]
+
+TASK [Task with var in name (foo bar)] *****************************************
+changed: [testhost]
+
+TASK [Loop task] ***************************************************************
+changed: [testhost] => (item=foo-1)
+changed: [testhost] => (item=foo-2)
+changed: [testhost] => (item=foo-3)
+
+TASK [debug loop] **************************************************************
+changed: [testhost] => (item=debug-1) => {
+    "msg": "debug-1"
+}
+[ERROR]: Task failed: Action failed: debug-2
+Origin: TEST_PATH/test.yml:38:7
+
+36
+37     # detect "changed" debug tasks being hidden with display_ok_tasks=false
+38     - name: debug loop
+         ^ column 7
+
+failed: [testhost] (item=debug-2) => {
+    "msg": "debug-2"
+}
+ok: [testhost] => (item=debug-3) => {
+    "msg": "debug-3"
+}
+skipping: [testhost] => (item=debug-4) 
+fatal: [testhost]: FAILED! => {"msg": "One or more items failed"}
+...ignoring
+
+TASK [EXPECTED FAILURE Failed task to be rescued] ******************************
+[ERROR]: Task failed: Action failed: Failed as requested from task
+Origin: TEST_PATH/test.yml:54:11
+
+52
+53     - block:
+54         - name: EXPECTED FAILURE Failed task to be rescued
+             ^ column 11
+
+fatal: [testhost]: FAILED! => {"changed": false, "msg": "Failed as requested from task"}
+
+TASK [Rescue task] *************************************************************
+changed: [testhost]
+
+TASK [include_tasks] ***********************************************************
+
+TASK [debug] *******************************************************************
+ok: [testhost] => {
+    "item": 1
+}
+
+TASK [copy] ********************************************************************
+changed: [testhost]
+
+TASK [replace] *****************************************************************
+--- before: .../test_diff.txt
++++ after: .../test_diff.txt
+@@ -1 +1 @@
+-foo
+\ No newline at end of file
++bar
+\ No newline at end of file
+
+changed: [testhost]
+
+TASK [replace] *****************************************************************
+ok: [testhost]
+
+TASK [debug] *******************************************************************
+skipping: [testhost]
+
+TASK [debug] *******************************************************************
+skipping: [testhost]
+
+TASK [debug] *******************************************************************
+skipping: [testhost] => (item=1) 
+skipping: [testhost] => (item=2) 
+skipping: [testhost]
+
+TASK [debug] *******************************************************************
+ok: [testhost] => (item=a) => {
+    "msg": "a"
+}
+
+RUNNING HANDLER [Test handler 1] ***********************************************
+changed: [testhost]
+
+RUNNING HANDLER [Test handler 2] ***********************************************
+ok: [testhost]
+
+RUNNING HANDLER [Test handler 3] ***********************************************
+changed: [testhost]
+
+PLAY [testhost] ****************************************************************
+
+TASK [First free task] *********************************************************
+changed: [testhost]
+
+TASK [Second free task] ********************************************************
+changed: [testhost]
+
+TASK [Include some tasks] ******************************************************
+
+TASK [debug] *******************************************************************
+ok: [testhost] => {
+    "item": 1
+}
+
+PLAY RECAP *********************************************************************
+testhost                   : ok=20   changed=11   unreachable=0    failed=0    skipped=4    rescued=1    ignored=2   
+
diff --git a/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stderr b/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stderr
new file mode 100644
index 00000000000000..d3e07d472db6de
--- /dev/null
+++ b/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stderr
@@ -0,0 +1,2 @@
++ ansible-playbook -i inventory test.yml
+++ set +x
diff --git a/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stdout b/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stdout
new file mode 100644
index 00000000000000..06427be4271b5c
--- /dev/null
+++ b/test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stdout
@@ -0,0 +1,93 @@
+
+PLAY [testhost] ****************************************************************
+
+TASK [Changed task] ************************************************************
+changed: [testhost]
+
+TASK [Failed task] *************************************************************
+[ERROR]: Task failed: Action failed: no reason
+Origin: TEST_PATH/test.yml:16:7
+
+14       changed_when: false
+15
+16     - name: Failed task
+         ^ column 7
+
+fatal: [testhost]: FAILED! => {"changed": false, "msg": "no reason"}
+...ignoring
+
+TASK [Task with var in name (foo bar)] *****************************************
+changed: [testhost]
+
+TASK [Loop task] ***************************************************************
+changed: [testhost] => (item=foo-1)
+changed: [testhost] => (item=foo-2)
+changed: [testhost] => (item=foo-3)
+
+TASK [debug loop] **************************************************************
+changed: [testhost] => (item=debug-1) => {
+    "msg": "debug-1"
+}
+[ERROR]: Task failed: Action failed: debug-2
+Origin: TEST_PATH/test.yml:38:7
+
+36
+37     # detect "changed" debug tasks being hidden with display_ok_tasks=false
+38     - name: debug loop
+         ^ column 7
+
+failed: [testhost] (item=debug-2) => {
+    "msg": "debug-2"
+}
+fatal: [testhost]: FAILED! => {"msg": "One or more items failed"}
+...ignoring
+
+TASK [EXPECTED FAILURE Failed task to be rescued] ******************************
+[ERROR]: Task failed: Action failed: Failed as requested from task
+Origin: TEST_PATH/test.yml:54:11
+
+52
+53     - block:
+54         - name: EXPECTED FAILURE Failed task to be rescued
+             ^ column 11
+
+fatal: [testhost]: FAILED! => {"changed": false, "msg": "Failed as requested from task"}
+
+TASK [Rescue task] *************************************************************
+changed: [testhost]
+
+TASK [include_tasks] ***********************************************************
+
+TASK [copy] ********************************************************************
+changed: [testhost]
+
+TASK [replace] *****************************************************************
+--- before: .../test_diff.txt
++++ after: .../test_diff.txt
+@@ -1 +1 @@
+-foo
+\ No newline at end of file
++bar
+\ No newline at end of file
+
+changed: [testhost]
+
+RUNNING HANDLER [Test handler 1] ***********************************************
+changed: [testhost]
+
+RUNNING HANDLER [Test handler 3] ***********************************************
+changed: [testhost]
+
+PLAY [testhost] ****************************************************************
+
+TASK [First free task] *********************************************************
+changed: [testhost]
+
+TASK [Second free task] ********************************************************
+changed: [testhost]
+
+TASK [Include some tasks] ******************************************************
+
+PLAY RECAP *********************************************************************
+testhost                   : ok=20   changed=11   unreachable=0    failed=0    skipped=4    rescued=1    ignored=2   
+
diff --git a/test/integration/targets/callback_default/runme.sh b/test/integration/targets/callback_default/runme.sh
index b73d3f24dfdf0f..5306ec1bfe6661 100755
--- a/test/integration/targets/callback_default/runme.sh
+++ b/test/integration/targets/callback_default/runme.sh
@@ -170,6 +170,27 @@ export ANSIBLE_DISPLAY_OK_HOSTS=0
 
 run_test hide_ok test.yml
 
+# Hide include
+export ANSIBLE_DISPLAY_SKIPPED_HOSTS=1
+export ANSIBLE_DISPLAY_OK_HOSTS=1
+export ANSIBLE_DISPLAY_INCLUDED_HOSTS=0
+
+run_test hide_included test.yml
+
+# Hide skipped/ok/included
+export ANSIBLE_DISPLAY_SKIPPED_HOSTS=0
+export ANSIBLE_DISPLAY_OK_HOSTS=0
+export ANSIBLE_DISPLAY_INCLUDED_HOSTS=0
+
+run_test hide_skipped_ok_included test.yml
+
+# Hide ok
+export ANSIBLE_DISPLAY_SKIPPED_HOSTS=1
+export ANSIBLE_DISPLAY_OK_HOSTS=0
+export ANSIBLE_DISPLAY_INCLUDED_HOSTS=1
+
+run_test hide_ok test.yml
+
 # Failed to stderr
 export ANSIBLE_DISPLAY_SKIPPED_HOSTS=1
 export ANSIBLE_DISPLAY_OK_HOSTS=1
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/callback_default/callback_default.out.hide_included.stderr test/integration/targets/callback_default/callback_default.out.hide_included.stdout test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stderr test/integration/targets/callback_default/callback_default.out.hide_skipped_ok_included.stdout test/integration/targets/callback_default/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/plugins/callback/test_default_callback.py::TestDefaultCallbackDisplayIncludedHosts::test_v2_playbook_on_include_hidden_when_disabled"]
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
