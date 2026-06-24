#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/units/module_utils/basic/test_run_command.py b/test/units/module_utils/basic/test_run_command.py
index c00ec27187b202..075c1a79c27eba 100644
--- a/test/units/module_utils/basic/test_run_command.py
+++ b/test/units/module_utils/basic/test_run_command.py
@@ -255,3 +255,81 @@ def test_run_command_fds(mocker, rc_am):
 
     assert subprocess_mock.Popen.call_args[1]['"'"'pass_fds'"'"'] == (101, 42)
     assert subprocess_mock.Popen.call_args[1]['"'"'close_fds'"'"'] is True
+
+
+class TestRunCommandNoneRead:
+    """
+    Test handling of read() returning None from non-blocking pipes.
+
+    This tests the fix for issue #86920 where read() can return None
+    in certain edge cases with non-blocking I/O, which would cause
+    TypeError when trying to concatenate None to bytes.
+    """
+
+    class NoneReturningBytesIO(SpecialBytesIO):
+        """
+        BytesIO that returns None on first read, then actual data.
+
+        This simulates edge cases where non-blocking read() returns None
+        to indicate "no data available right now" rather than empty bytes.
+        """
+
+        def __init__(self, *args, **kwargs):
+            # Pop '"'"'data'"'"' before calling super().__init__() since BytesIO doesn'"'"'t accept it
+            self.data = kwargs.pop('"'"'data'"'"', b'"'"'test output'"'"')
+            self.read_count = 0
+            super(TestRunCommandNoneRead.NoneReturningBytesIO, self).__init__(*args, **kwargs)
+
+        def read(self, size=-1):
+            self.read_count += 1
+            if self.read_count == 1:
+                # First read returns None (no data available)
+                return None
+            elif self.read_count == 2:
+                # Second read returns actual data
+                return self.data
+            else:
+                # Subsequent reads return empty bytes (EOF)
+                return b'"'"''"'"'
+
+    @pytest.mark.parametrize('"'"'stdin'"'"', [{}], indirect=['"'"'stdin'"'"'])
+    def test_none_from_stdout_read(self, mocker, rc_am):
+        """Test that None returned from stdout.read() doesn'"'"'t cause TypeError."""
+        rc_am._subprocess._output = {
+            mocker.sentinel.stdout:
+                self.NoneReturningBytesIO(fh=mocker.sentinel.stdout, data=b'"'"'command output'"'"'),
+            mocker.sentinel.stderr:
+                SpecialBytesIO(b'"'"''"'"', fh=mocker.sentinel.stderr)
+        }
+        (rc, stdout, stderr) = rc_am.run_command('"'"'/bin/test'"'"')
+        assert rc == 0
+        assert stdout == '"'"'command output'"'"'
+        assert stderr == '"'"''"'"'
+
+    @pytest.mark.parametrize('"'"'stdin'"'"', [{}], indirect=['"'"'stdin'"'"'])
+    def test_none_from_stderr_read(self, mocker, rc_am):
+        """Test that None returned from stderr.read() doesn'"'"'t cause TypeError."""
+        rc_am._subprocess._output = {
+            mocker.sentinel.stdout:
+                SpecialBytesIO(b'"'"''"'"', fh=mocker.sentinel.stdout),
+            mocker.sentinel.stderr:
+                self.NoneReturningBytesIO(fh=mocker.sentinel.stderr, data=b'"'"'error output'"'"')
+        }
+        (rc, stdout, stderr) = rc_am.run_command('"'"'/bin/test'"'"')
+        assert rc == 0
+        assert stdout == '"'"''"'"'
+        assert stderr == '"'"'error output'"'"'
+
+    @pytest.mark.parametrize('"'"'stdin'"'"', [{}], indirect=['"'"'stdin'"'"'])
+    def test_none_from_both_pipes(self, mocker, rc_am):
+        """Test that None returned from both pipes doesn'"'"'t cause TypeError."""
+        rc_am._subprocess._output = {
+            mocker.sentinel.stdout:
+                self.NoneReturningBytesIO(fh=mocker.sentinel.stdout, data=b'"'"'stdout data'"'"'),
+            mocker.sentinel.stderr:
+                self.NoneReturningBytesIO(fh=mocker.sentinel.stderr, data=b'"'"'stderr data'"'"')
+        }
+        (rc, stdout, stderr) = rc_am.run_command('"'"'/bin/test'"'"')
+        assert rc == 0
+        assert stdout == '"'"'stdout data'"'"'
+        assert stderr == '"'"'stderr data'"'"'
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/units/module_utils/basic/test_run_command.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_stdout_read[stdin0]", "test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_stderr_read[stdin0]", "test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_both_pipes[stdin0]"]

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
