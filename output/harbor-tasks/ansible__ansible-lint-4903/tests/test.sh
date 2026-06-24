#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_cli.py b/test/test_cli.py
index c78685f424..fa2e374fa7 100644
--- a/test/test_cli.py
+++ b/test/test_cli.py
@@ -3,12 +3,15 @@
 from __future__ import annotations
 
 import os
+import sys
 from pathlib import Path
 from typing import TYPE_CHECKING
+from unittest.mock import patch
 
 import pytest
 
 from ansiblelint import cli
+from ansiblelint.config import Options
 
 if TYPE_CHECKING:
     from _pytest.monkeypatch import MonkeyPatch
@@ -254,3 +257,29 @@ def test_config_dev_null(base_arguments: list[str], config_file: str) -> None:
     """Ensures specific config files produce error code 3."""
     cfg = cli.get_config([*base_arguments, "-c", config_file])
     assert cfg.config_file == "/dev/null"
+
+
+def test_offline_cli_overrides_config(base_arguments: list[str]) -> None:
+    """Ensure --no-offline overrides offline: true in config (#4845)."""
+    cli_config = Options()
+    cli_config.offline = False
+    file_config = {"offline": True}
+
+    command: list[str] = [*base_arguments, "--no-offline"]
+    with patch.object(sys, "argv", command):
+        result = cli.merge_config(file_config, cli_config)
+
+    assert result.offline is False
+
+
+def test_offline_config_used_when_no_cli(base_arguments: list[str]) -> None:
+    """Ensure config file is used when CLI flag is absent (#4845)."""
+    cli_config = Options()
+    cli_config.offline = False
+    file_config = {"offline": True}
+
+    command: list[str] = [*base_arguments]
+    with patch.object(sys, "argv", command):
+        result = cli.merge_config(file_config, cli_config)
+
+    assert result.offline is True
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_cli.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_cli.py::test_offline_cli_overrides_config"]
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
