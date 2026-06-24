#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/hardware_facts/tasks/Linux.yml b/test/integration/targets/hardware_facts/tasks/Linux.yml
index 885aa0ec9308ba..c15cce30036cce 100644
--- a/test/integration/targets/hardware_facts/tasks/Linux.yml
+++ b/test/integration/targets/hardware_facts/tasks/Linux.yml
@@ -52,7 +52,25 @@
           - ansible_lvm.lvs.two.vg == '"'"'first'"'"'
           - ansible_lvm.lvs.uno.vg == '"'"'second'"'"'
           - ansible_lvm.vgs.first.num_lvs == "2"
+          - ansible_facts['"'"'lvm'"'"']['"'"'vgs'"'"']['"'"'first'"'"']['"'"'lvs'"'"'] | sort == ['"'"'one'"'"', '"'"'two'"'"']
           - ansible_lvm.vgs.second.num_lvs == "1"
+          - ansible_facts['"'"'lvm'"'"']['"'"'vgs'"'"']['"'"'second'"'"']['"'"'lvs'"'"'] | sort == ['"'"'uno'"'"']
+
+    - name: Create another lv using duplicate name
+      command: lvcreate -L 4M second --name two
+
+    - name: Gather facts
+      setup:
+
+    - assert:
+        that:
+          - ansible_facts['"'"'lvm'"'"']['"'"'vgs'"'"']['"'"'first'"'"']['"'"'lvs'"'"'] | sort == ['"'"'one'"'"', '"'"'two'"'"']
+          - ansible_facts['"'"'lvm'"'"']['"'"'vgs'"'"']['"'"'second'"'"']['"'"'lvs'"'"'] | sort == ['"'"'two'"'"', '"'"'uno'"'"']
+          # only one lv named '"'"'two'"'"' is represented in the top level lvs fact
+          - ansible_facts['"'"'lvm'"'"']['"'"'lvs'"'"']['"'"'two'"'"']['"'"'vg'"'"'] == '"'"'second'"'"'
+          - (vgs_lvs | unique | sort) == (ansible_facts['"'"'lvm'"'"']['"'"'lvs'"'"'] | sort)
+      vars:
+        vgs_lvs: "{{ ansible_facts['"'"'lvm'"'"']['"'"'vgs'"'"'].values() | map(attribute='"'"'lvs'"'"') | map('"'"'list'"'"') | flatten }}"
 
   always:
     - name: remove lvs
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/hardware_facts/tasks/Linux.yml 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/module_utils/facts/hardware/test_linux.py::TestFactsLinuxHardwareGetMountFacts::test_get_lvm_facts_vgs_contain_lvs"]
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
