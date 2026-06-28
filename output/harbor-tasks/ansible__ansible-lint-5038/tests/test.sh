#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_issue_4898.py b/test/test_issue_4898.py
new file mode 100644
index 0000000000..7661c23fd4
--- /dev/null
+++ b/test/test_issue_4898.py
@@ -0,0 +1,152 @@
+"""Tests for issue #4898: Silent configuration errors when log_path is set."""
+
+import logging
+import os
+from pathlib import Path
+from unittest.mock import patch
+
+import pytest
+
+from ansiblelint import cli
+
+
+def test_config_error_with_log_path(tmp_path: Path) -> None:
+    """Verify that configuration errors are printed to stderr and logged to log_path."""
+    # 1. Setup temporary paths
+    ansible_cfg = tmp_path / "ansible.cfg"
+    lint_cfg = tmp_path / ".ansible-lint"
+    log_file = tmp_path / "ansible-lint.log"
+
+    # 2. Create ansible.cfg with log_path
+    ansible_cfg.write_text(f"[defaults]\nlog_path={log_file}\n")
+
+    # 3. Create invalid .ansible-lint
+    lint_cfg.write_text("invalid_option: true\n")
+
+    # 4. Run cli.get_config and verify console_stderr.print and _logger.error were called
+    os.environ["ANSIBLE_CONFIG"] = str(ansible_cfg)
+    original_handlers = list(logging.root.handlers)
+
+    # Simulate Ansible'"'"'s FileHandler setup when log_path is configured in a fresh process
+    handler = logging.FileHandler(str(log_file))
+    logging.root.addHandler(handler)
+
+    try:
+        with (
+            patch("ansiblelint.cli.console_stderr.print") as mock_print,
+            patch("ansiblelint.cli._logger.error") as mock_error,
+            pytest.raises(SystemExit) as exc,
+        ):
+            cli.get_config(["-c", str(lint_cfg)])
+
+        assert exc.value.code == 3
+
+        # 5. Verify console_stderr.print was called with error message
+        mock_print.assert_called()
+        args, _ = mock_print.call_args
+        assert "Invalid configuration file" in args[0]
+        assert "invalid_option" in args[0]
+
+        # 6. Verify _logger.error was also called because handlers are configured
+        mock_error.assert_called_once()
+        args, _ = mock_error.call_args
+        assert "Invalid configuration file" in args[0]
+    finally:
+        os.environ.pop("ANSIBLE_CONFIG", None)
+        handler.close()
+        logging.root.handlers = original_handlers
+
+
+def test_config_error_without_log_path(tmp_path: Path) -> None:
+    """Verify that configuration errors are printed to stderr but NOT logged via _logger to avoid duplicates."""
+    # 1. Setup temporary paths
+    lint_cfg = tmp_path / ".ansible-lint"
+
+    # 2. Create invalid .ansible-lint
+    lint_cfg.write_text("invalid_option: true\n")
+
+    original_handlers = list(logging.root.handlers)
+
+    # 3. Run cli.get_config and verify only console_stderr.print is called
+    try:
+        with (
+            patch("ansiblelint.cli.console_stderr.print") as mock_print,
+            patch("ansiblelint.cli._logger.error") as mock_error,
+            pytest.raises(SystemExit) as exc,
+        ):
+            cli.get_config(["-c", str(lint_cfg)])
+
+        assert exc.value.code == 3
+
+        # 4. Verify console_stderr.print was called
+        mock_print.assert_called()
+        args, _ = mock_print.call_args
+        assert "Invalid configuration file" in args[0]
+        assert "invalid_option" in args[0]
+
+        # 5. Verify _logger.error was NOT called to avoid duplicate output to stderr
+        mock_error.assert_not_called()
+    finally:
+        logging.root.handlers = original_handlers
+
+
+def test_missing_config_error_with_log_path(tmp_path: Path) -> None:
+    """Verify that missing configuration file errors are printed to stderr and logged even with log_path."""
+    ansible_cfg = tmp_path / "ansible.cfg"
+    log_file = tmp_path / "ansible-lint.log"
+    missing_cfg = tmp_path / "non-existent.yml"
+
+    ansible_cfg.write_text(f"[defaults]\nlog_path={log_file}\n")
+    os.environ["ANSIBLE_CONFIG"] = str(ansible_cfg)
+    original_handlers = list(logging.root.handlers)
+
+    # Simulate Ansible'"'"'s FileHandler setup when log_path is configured in a fresh process
+    handler = logging.FileHandler(str(log_file))
+    logging.root.addHandler(handler)
+
+    try:
+        with (
+            patch("ansiblelint.cli.console_stderr.print") as mock_print,
+            patch("ansiblelint.cli._logger.error") as mock_error,
+            pytest.raises(SystemExit) as exc,
+        ):
+            cli.get_config(["-c", str(missing_cfg)])
+
+        assert exc.value.code == 3
+
+        mock_print.assert_called()
+        args, _ = mock_print.call_args
+        assert "Config file not found" in args[0]
+
+        mock_error.assert_called_once()
+        args, _ = mock_error.call_args
+        assert "Config file not found" in args[0]
+    finally:
+        os.environ.pop("ANSIBLE_CONFIG", None)
+        handler.close()
+        logging.root.handlers = original_handlers
+
+
+def test_missing_config_error_without_log_path(tmp_path: Path) -> None:
+    """Verify that missing configuration file errors are printed but not logged via _logger when log_path is not set."""
+    missing_cfg = tmp_path / "non-existent.yml"
+    original_handlers = list(logging.root.handlers)
+
+    try:
+        with (
+            patch("ansiblelint.cli.console_stderr.print") as mock_print,
+            patch("ansiblelint.cli._logger.error") as mock_error,
+            pytest.raises(SystemExit) as exc,
+        ):
+            cli.get_config(["-c", str(missing_cfg)])
+
+        assert exc.value.code == 3
+
+        mock_print.assert_called()
+        args, _ = mock_print.call_args
+        assert "Config file not found" in args[0]
+
+        # Should not log via _logger to prevent duplicate output to stderr
+        mock_error.assert_not_called()
+    finally:
+        logging.root.handlers = original_handlers
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/test_issue_4898.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/test_issue_4898.py::test_config_error_with_log_path", "test/test_issue_4898.py::test_config_error_without_log_path", "test/test_issue_4898.py::test_missing_config_error_with_log_path", "test/test_issue_4898.py::test_missing_config_error_without_log_path"]

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

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
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
