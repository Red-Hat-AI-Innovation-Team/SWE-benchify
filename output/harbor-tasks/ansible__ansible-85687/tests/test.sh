#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/handlers/rescue_flush_handlers.yml b/test/integration/targets/handlers/rescue_flush_handlers.yml
new file mode 100644
index 00000000000000..065743654a88cb
--- /dev/null
+++ b/test/integration/targets/handlers/rescue_flush_handlers.yml
@@ -0,0 +1,16 @@
+- hosts: localhost
+  gather_facts: false
+  tasks:
+    - block:
+        - debug:
+          changed_when: true
+          notify: h1
+
+        - meta: flush_handlers
+      rescue:
+        - assert:
+            that:
+              - ansible_failed_task is defined
+  handlers:
+    - name: h1
+      fail:
diff --git a/test/integration/targets/handlers/runme.sh b/test/integration/targets/handlers/runme.sh
index 0cc7b3c36ca371..648eb87bb91e76 100755
--- a/test/integration/targets/handlers/runme.sh
+++ b/test/integration/targets/handlers/runme.sh
@@ -230,3 +230,5 @@ ansible-playbook handler_notify_earlier_handler.yml "$@" 2>&1 | tee out.txt
 ANSIBLE_DEBUG=1 ansible-playbook tagged_play.yml --skip-tags the_whole_play "$@" 2>&1 | tee out.txt
 [ "$(grep out.txt -ce '"'"'META: triggered running handlers'"'"')" = "0" ]
 [ "$(grep out.txt -ce '"'"'handler_ran'"'"')" = "0" ]
+
+ansible-playbook rescue_flush_handlers.yml "$@"
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/handlers/rescue_flush_handlers.yml test/integration/targets/handlers/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/handlers/rescue_flush_handlers.yml"]
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
