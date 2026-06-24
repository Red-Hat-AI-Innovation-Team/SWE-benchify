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

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/config/lookup_plugins/broken.py test/integration/targets/config/match_option_methods.yml test/integration/targets/config/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/integration/targets/config/match_option_methods.yml"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_junit_xml(text):
    # Minimal XML parser for JUnit format (no lxml dependency)
    results = {}
    for m in re.finditer(r'<testcase[^>]*name="([^"]*)"[^>]*classname="([^"]*)"[^>]*(/?>)', text):
        name, classname, close = m.groups()
        test_id = f"{classname}.{name}"
        # Check for failure/error child elements
        if close == "/>":
            results[test_id] = "passed"
        else:
            # Find the matching </testcase> and check contents
            start = m.end()
            end = text.find("</testcase>", start)
            block = text[start:end] if end != -1 else ""
            if "<failure" in block or "<error" in block:
                results[test_id] = "failed"
            elif "<skipped" in block:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results

def parse_cargo_test(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            test_id = m.group(1)
            status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_tap(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"(ok|not ok)\s+\d+\s*-?\s*(.*)", line)
        if m:
            status = "passed" if m.group(1) == "ok" else "failed"
            desc = m.group(2).strip()
            if "# SKIP" in desc:
                status = "skipped"
                desc = desc.split("# SKIP")[0].strip()
            results[desc] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
    "junit-xml": parse_junit_xml,
    "cargo-test": parse_cargo_test,
    "tap": parse_tap,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="pytest-verbose" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
