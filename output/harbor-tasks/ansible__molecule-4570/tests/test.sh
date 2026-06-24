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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs tests/unit/command/conftest.py tests/unit/command/test_list.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["tests/unit/command/test_list.py::test_list_execute_native[_molecule_data_native]"]
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
