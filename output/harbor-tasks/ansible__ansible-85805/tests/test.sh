#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/handlers/runme.sh b/test/integration/targets/handlers/runme.sh
index 648eb87bb91e76..51097192aeb428 100755
--- a/test/integration/targets/handlers/runme.sh
+++ b/test/integration/targets/handlers/runme.sh
@@ -229,6 +229,13 @@ ansible-playbook handler_notify_earlier_handler.yml "$@" 2>&1 | tee out.txt
 
 ANSIBLE_DEBUG=1 ansible-playbook tagged_play.yml --skip-tags the_whole_play "$@" 2>&1 | tee out.txt
 [ "$(grep out.txt -ce '"'"'META: triggered running handlers'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'No handler notifications for'"'"')" = "0" ]
 [ "$(grep out.txt -ce '"'"'handler_ran'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'handler1_ran'"'"')" = "0" ]
 
 ansible-playbook rescue_flush_handlers.yml "$@"
+
+ANSIBLE_DEBUG=1 ansible-playbook tagged_play.yml --tags task_tag "$@" 2>&1 | tee out.txt
+[ "$(grep out.txt -ce '"'"'META: triggered running handlers'"'"')" = "1" ]
+[ "$(grep out.txt -ce '"'"'handler_ran'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'handler1_ran'"'"')" = "1" ]
diff --git a/test/integration/targets/handlers/tagged_play.yml b/test/integration/targets/handlers/tagged_play.yml
index e96348dcd12794..8c209faaef1e53 100644
--- a/test/integration/targets/handlers/tagged_play.yml
+++ b/test/integration/targets/handlers/tagged_play.yml
@@ -2,9 +2,19 @@
   gather_facts: false
   tags: the_whole_play
   tasks:
-    - command: echo
+    - debug:
+      changed_when: true
       notify: h
+
+    - debug:
+      changed_when: true
+      notify: h1
+      tags: task_tag
   handlers:
     - name: h
       debug:
         msg: handler_ran
+
+    - name: h1
+      debug:
+        msg: handler1_ran
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/handlers/runme.sh test/integration/targets/handlers/tagged_play.yml 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/handlers/runme.sh::tagged_play.yml --tags task_tag::META_triggered_running_handlers_eq_1", "test/integration/targets/handlers/runme.sh::tagged_play.yml --tags task_tag::handler1_ran_eq_1"]
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
