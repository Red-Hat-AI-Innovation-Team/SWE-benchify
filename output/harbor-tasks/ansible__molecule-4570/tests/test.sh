#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/tests/unit/command/conftest.py b/tests/unit/command/conftest.py
index 2c4d76aea..b1b6c9f5f 100644
--- a/tests/unit/command/conftest.py
+++ b/tests/unit/command/conftest.py
@@ -19,9 +19,15 @@
 #  DEALINGS IN THE SOFTWARE.
 from __future__ import annotations
 
+from typing import TYPE_CHECKING
+
 import pytest
 
 
+if TYPE_CHECKING:
+    from molecule.types import ConfigData
+
+
 @pytest.fixture
 def command_patched_ansible_create(mocker):  # type: ignore[no-untyped-def]  # noqa: ANN201, D103
     return mocker.patch("molecule.provisioner.ansible.Ansible.create")
@@ -45,3 +51,20 @@ def command_driver_delegated_section_data():  # type: ignore[no-untyped-def]  #
 @pytest.fixture
 def command_driver_delegated_managed_section_data():  # type: ignore[no-untyped-def]  # noqa: ANN201, D103
     return {"driver": {"name": "default", "managed": True}}
+
+
+@pytest.fixture
+def _molecule_data_native() -> ConfigData:
+    """Provide a default molecule data dictionary.
+
+    This version removes options unused in ansible-native configs.
+
+    Returns:
+      A molecule config dictionary.
+    """
+    return {
+        "ansible": {"executor": {"backend": "ansible-playbook"}},
+        "driver": {},
+        "platforms": [],
+        "provisioner": {},
+    }
diff --git a/tests/unit/command/test_list.py b/tests/unit/command/test_list.py
index 237b31c48..12af62fc6 100644
--- a/tests/unit/command/test_list.py
+++ b/tests/unit/command/test_list.py
@@ -21,13 +21,13 @@
 
 from typing import TYPE_CHECKING
 
+import pytest
+
 from molecule.command import list  # noqa: A004
 from molecule.status import Status
 
 
 if TYPE_CHECKING:
-    import pytest
-
     from molecule import config
 
 
@@ -56,3 +56,27 @@ def test_list_execute(  # noqa: D103
     ]
 
     assert x == l.execute()
+
+
+@pytest.mark.parametrize(
+    "config_instance",
+    ["_molecule_data_native"],  # noqa: PT007
+    indirect=True,
+)
+def test_list_execute_native(  # noqa: D103
+    capsys: pytest.CaptureFixture[str],
+    config_instance: config.Config,
+) -> None:
+    l = list.List(config_instance)  # noqa: E741
+    x = [
+        Status(
+            instance_name="",
+            driver_name="default",
+            provisioner_name="ansible",
+            scenario_name="default",
+            created="false",
+            converged="false",
+        ),
+    ]
+
+    assert x == l.execute()
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs tests/unit/command/conftest.py tests/unit/command/test_list.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["tests/unit/command/test_list.py::test_list_execute_native[_molecule_data_native]"]

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
