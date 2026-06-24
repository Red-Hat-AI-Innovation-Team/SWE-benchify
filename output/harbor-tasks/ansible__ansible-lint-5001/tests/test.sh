#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_app.py b/test/test_app.py
index 1a34458fef..a9a2ada805 100644
--- a/test/test_app.py
+++ b/test/test_app.py
@@ -75,3 +75,63 @@ def test_app_fixed_violations_coverage(tmp_path: Path) -> None:
     exit_code = app.report_outcome(result)
 
     assert exit_code == RC.FIXED_VIOLATIONS
+
+
+def test_ignore_file_with_skip_and_strict(tmp_path: Path) -> None:
+    """Test that .ansible-lint-ignore with skip qualifier returns exit code 0 with --strict.
+
+    When all violations are skipped using '"'"'skip'"'"' in .ansible-lint-ignore,
+    the exit code should be 0, even with --strict flag.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create ignore file with skip qualifier
+    ignore_file = tmp_path / ".ansible-lint-ignore"
+    ignore_file.write_text("test.yml yaml[indentation] skip")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 0 because all violations are skipped
+    assert result.returncode == RC.SUCCESS
+
+
+def test_ignore_file_without_skip_and_strict(tmp_path: Path) -> None:
+    """Test that .ansible-lint-ignore without skip qualifier returns exit code 2 with --strict.
+
+    When violations are ignored (but not skipped) in .ansible-lint-ignore,
+    they should be treated as warnings, and --strict should cause exit code 2.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create ignore file without skip qualifier
+    ignore_file = tmp_path / ".ansible-lint-ignore"
+    ignore_file.write_text("test.yml yaml[indentation]")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 2 because there'"'"'s a warning and we'"'"'re in strict mode
+    assert result.returncode == RC.VIOLATIONS_FOUND
+
+
+def test_skip_list_and_strict(tmp_path: Path) -> None:
+    """Test that skip_list returns exit code 0 with --strict.
+
+    When all rules generating violations are skipped using '"'"'skip_list'"'"',
+    the exit code should be 0, even with --strict flag.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create config file with skip_list
+    config_file = tmp_path / ".ansible-lint"
+    config_file.write_text("skip_list:\n  - yaml[indentation]\n")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 0 because rule is in skip_list
+    assert result.returncode == RC.SUCCESS
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/test_app.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/test_app.py::test_ignore_file_with_skip_and_strict"]

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
