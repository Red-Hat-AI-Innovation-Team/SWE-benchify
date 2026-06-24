#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/config/lookup_plugins/broken.py b/test/integration/targets/config/lookup_plugins/broken.py
new file mode 100644
index 00000000000000..ee37b030d24bda
--- /dev/null
+++ b/test/integration/targets/config/lookup_plugins/broken.py
@@ -0,0 +1,57 @@
+# -*- coding: utf-8 -*-
+# Copyright (c) 2025, Felix Fontein <felix@fontein.de>, The Ansible Project
+# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
+# SPDX-License-Identifier: GPL-3.0-or-later
+from __future__ import annotations
+
+
+DOCUMENTATION = r"""
+name: broken
+short_description: Test input precedence
+author: Felix Fontein (@felixfontein)
+description:
+  - Test input precedence.
+options:
+  _terms:
+    description:
+      - Ignored.
+    type: list
+    elements: str
+    required: true
+  some_option:
+    description:
+      - The interesting part.
+    type: str
+    default: default value
+    env:
+      - name: PLAYGROUND_TEST_1
+      - name: PLAYGROUND_TEST_2
+    vars:
+      - name: playground_test_1
+      - name: playground_test_2
+    ini:
+      - key: playground_test_1
+        section: playground
+      - key: playground_test_2
+        section: playground
+"""
+
+EXAMPLES = r"""#"""
+
+RETURN = r"""
+_list:
+  description:
+    - The value of O(some_option).
+  type: list
+  elements: str
+"""
+
+from ansible.plugins.lookup import LookupBase
+
+
+class LookupModule(LookupBase):
+    def run(self, terms, variables=None, **kwargs):
+        """Generate list."""
+        self.set_options(var_options=variables, direct=kwargs)
+
+        return [self.get_option("some_option"), *self.get_option_and_origin("some_option")]
diff --git a/test/integration/targets/config/match_option_methods.yml b/test/integration/targets/config/match_option_methods.yml
new file mode 100644
index 00000000000000..c3f1412a78f7fa
--- /dev/null
+++ b/test/integration/targets/config/match_option_methods.yml
@@ -0,0 +1,37 @@
+- hosts: localhost
+  gather_facts: false
+  vars:
+      direct: "{{ query('"'"'broken'"'"', some_option='"'"'foo'"'"') }}"
+      default: "{{ query('"'"'broken'"'"') }}"
+  tasks:
+    - name: Set directly but also have  vars
+      set_fact:
+        direct_with_vars: "{{ query('"'"'broken'"'"', some_option='"'"'foo'"'"') }}"
+      vars:
+        playground_test_1: var 1
+        playground_test_2: var 2
+    - name:  Set via vars only
+      set_fact:
+        vars_only: "{{ query('"'"'broken'"'"') }}"
+      vars:
+        playground_test_1: var 1
+        playground_test_2: var 2
+
+    - debug: msg={{q('"'"'vars'"'"', item)}}
+      loop:
+        - direct
+        - default
+        - direct_with_vars
+        - vars_only
+
+    - name: now ensure it all worked as expected (simple value, origin value, origin)
+      assert:
+        that:
+          - direct[0] == direct[1]
+          - direct[2] == '"'"'Direct'"'"'
+          - default[0] == default[1]
+          - default[2] == '"'"'default'"'"'
+          - direct_with_vars[0] == direct_with_vars[1]
+          - direct_with_vars[2] == '"'"'Direct'"'"'
+          - vars_only[0] == vars_only[1]
+          - vars_only[2].startswith('"'"'var:'"'"')
diff --git a/test/integration/targets/config/runme.sh b/test/integration/targets/config/runme.sh
index 0ed659d1b7490e..4f8d4eb396c098 100755
--- a/test/integration/targets/config/runme.sh
+++ b/test/integration/targets/config/runme.sh
@@ -43,3 +43,6 @@ done
 
 # ensure we don'"'"'t show default templates, but templated defaults
 [ "$(ansible-config init |grep '"'"'={{'"'"' -c )" -eq 0 ]
+
+# test seldom used '"'"'_and_origin'"'"' api 
+ansible-playbook match_option_methods.yml "$@"
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/config/lookup_plugins/broken.py test/integration/targets/config/match_option_methods.yml test/integration/targets/config/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/config/match_option_methods.yml"]
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
