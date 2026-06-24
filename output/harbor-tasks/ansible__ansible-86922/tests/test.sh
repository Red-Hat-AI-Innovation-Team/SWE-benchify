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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/units/module_utils/basic/test_run_command.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_stdout_read[stdin0]", "test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_stderr_read[stdin0]", "test/units/module_utils/basic/test_run_command.py::TestRunCommandNoneRead::test_none_from_both_pipes[stdin0]"]
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
