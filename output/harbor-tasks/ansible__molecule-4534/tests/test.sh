#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/tests/unit/command/init/test_scenario.py b/tests/unit/command/init/test_scenario.py
index 809d96435..644586345 100644
--- a/tests/unit/command/init/test_scenario.py
+++ b/tests/unit/command/init/test_scenario.py
@@ -27,7 +27,6 @@
 
 from molecule.command.init.scenario import Scenario
 from molecule.config import Config
-from molecule.exceptions import MoleculeError
 from molecule.utils import util
 
 
@@ -114,7 +113,7 @@ def test_execute_scenario_exists(
     monkeypatch.chdir(test_cache_path)
     instance.execute()
 
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         instance.execute()
 
     assert e.value.code == 1
@@ -249,7 +248,7 @@ def test_execute_scenario_exists_collection_mode(
     # Clear cache to ensure fresh detection
     util.get_collection_metadata.cache_clear()
 
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         instance.execute()
 
     assert e.value.code == 1
diff --git a/tests/unit/command/test_base.py b/tests/unit/command/test_base.py
index 2d979c3db..946d85da7 100644
--- a/tests/unit/command/test_base.py
+++ b/tests/unit/command/test_base.py
@@ -261,7 +261,7 @@ def test_execute_cmdline_scenarios_missing(
     args: MoleculeArgs = {}
     command_args: CommandArgs = {"destroy": "always", "subcommand": "test"}
 
-    with pytest.raises(ImmediateExit):
+    with pytest.raises(SystemExit):
         base.execute_cmdline_scenarios(scenario_name, args, command_args)
 
     error_msg = "'"'"'molecule/nonexistent/molecule.yml'"'"' glob failed.  Exiting."
@@ -318,23 +318,21 @@ def test_execute_cmdline_scenarios_no_prune(
     ),
 )
 @pytest.mark.usefixtures("config_instance")
-def test_execute_cmdline_scenarios_exit_destroy(  # noqa: PLR0913
+def test_execute_cmdline_scenarios_exit_destroy(
     patched_execute_scenario: MagicMock,
     patched_prune: MagicMock,
     patched_execute_subcommand: MagicMock,
-    patched_sysexit: MagicMock,
     destroy: Literal["always", "never"],
     subcommands: tuple[str, ...],
 ) -> None:
     """Ensure execute_cmdline_scenarios handles errors correctly when '"'"'destroy'"'"' is set.
 
-    - When ScenarioFailureError occurs, ImmediateExit should be raised immediately
+    - When ScenarioFailureError occurs, SystemExit should be raised immediately
 
     Args:
         patched_execute_scenario: Mocked execute_scenario function.
         patched_prune: Mocked prune function.
         patched_execute_subcommand: Mocked execute_subcommand function.
-        patched_sysexit: Mocked util.sysexit function.
         destroy: Value to set '"'"'destroy'"'"' arg to.
         subcommands: Expected subcommands to run after execute_scenario fails.
     """
@@ -343,8 +341,8 @@ def test_execute_cmdline_scenarios_exit_destroy(  # noqa: PLR0913
     command_args: CommandArgs = {"destroy": destroy, "subcommand": "test"}
     patched_execute_scenario.side_effect = ScenarioFailureError()
 
-    # Should raise ImmediateExit when ScenarioFailureError occurs
-    with pytest.raises(ImmediateExit):
+    # Should raise SystemExit when ScenarioFailureError occurs
+    with pytest.raises(SystemExit):
         base.execute_cmdline_scenarios(scenario_name, args, command_args)
 
     assert patched_execute_scenario.called
@@ -659,7 +657,7 @@ def mock_apply_cli_overrides(self: config.Config) -> None:
         main.main(standalone_mode=False)
 
     # 6. Assert results
-    assert exc_info.value.code == 0  # Our ImmediateExit code was handled properly
+    assert exc_info.value.code == 0
     assert len(captured_configs) >= 1  # At least one config was created
     assert captured_configs[0].shared_state is expected  # CLI override logic worked correctly
 
@@ -771,7 +769,7 @@ def mock_apply_cli_overrides(self: config.Config) -> None:
         main.main(standalone_mode=False)
 
     # 5. Assert results
-    assert exc_info.value.code == 0  # Our ImmediateExit code was handled properly
+    assert exc_info.value.code == 0
     assert len(captured_configs) >= 1  # At least one config was created
 
     config_obj = captured_configs[0]
diff --git a/tests/unit/command/test_login.py b/tests/unit/command/test_login.py
index 0e856830c..41eb93f0b 100644
--- a/tests/unit/command/test_login.py
+++ b/tests/unit/command/test_login.py
@@ -24,7 +24,6 @@
 import pytest
 
 from molecule.command import login
-from molecule.exceptions import MoleculeError
 
 
 if TYPE_CHECKING:
@@ -81,7 +80,7 @@ def test_get_hostname_does_not_match(  # noqa: D103
 ) -> None:
     _instance._config.command_args = {"host": "invalid"}
     hosts = ["instance-1"]
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         _instance._get_hostname(hosts)
 
     assert e.value.code == 1
@@ -132,7 +131,7 @@ def test_get_hostname_partial_match_with_multiple_hosts_raises(  # noqa: D103
 ) -> None:
     _instance._config.command_args = {"host": "inst"}
     hosts = ["instance-1", "instance-2"]
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         _instance._get_hostname(hosts)
 
     assert e.value.code == 1
@@ -163,7 +162,7 @@ def test_get_hostname_no_host_flag_specified_on_cli_with_multiple_hosts_raises(
 ) -> None:
     _instance._config.command_args = {}
     hosts = ["instance-1", "instance-2"]
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         _instance._get_hostname(hosts)
 
     assert e.value.code == 1
diff --git a/tests/unit/test_config.py b/tests/unit/test_config.py
index 47209ed95..1e31f6571 100644
--- a/tests/unit/test_config.py
+++ b/tests/unit/test_config.py
@@ -29,7 +29,6 @@
 
 from molecule import config, platforms, scenario, state
 from molecule.dependency import ansible_galaxy, shell
-from molecule.exceptions import MoleculeError
 from molecule.provisioner import ansible
 from molecule.utils import util
 from molecule.verifier.ansible import Ansible as AnsibleVerifier
@@ -278,7 +277,7 @@ def test_get_driver_name_from_state_file(  # noqa: D103
 ) -> None:
     config_instance.state.change_state("driver", "state-driver")
 
-    with pytest.raises(MoleculeError):
+    with pytest.raises(SystemExit):
         config_instance._get_driver_name()
 
     mocker.patch("molecule.api.drivers", return_value=["state-driver"])
@@ -301,7 +300,7 @@ def test_get_driver_name_raises_when_different_driver_used(  # noqa: D103
 ) -> None:
     config_instance.state.change_state("driver", "foo")
     config_instance.command_args = {"driver_name": "bar"}
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         config_instance._get_driver_name()
 
     assert e.value.code == 1
@@ -394,7 +393,7 @@ def test_interpolate_raises_on_failed_interpolation(  # noqa: D103
 ) -> None:
     string = "$6$8I5Cfmpr$kGZB"
 
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         config_instance._interpolate(string, os.environ, "")
 
     assert e.value.code == 1
@@ -465,7 +464,7 @@ def test_validate_exists_when_validation_fails(  # noqa: D103
     m = mocker.patch("molecule.model.schema_v3.validate")
     m.return_value = "validation errors"
 
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         config_instance._validate()
 
     assert e.value.code == 1
diff --git a/tests/unit/test_scenarios.py b/tests/unit/test_scenarios.py
index 35f17f2d9..00cc8f2f4 100644
--- a/tests/unit/test_scenarios.py
+++ b/tests/unit/test_scenarios.py
@@ -25,7 +25,6 @@
 
 from molecule import config, scenario, scenarios
 from molecule.console import console
-from molecule.exceptions import MoleculeError
 from molecule.text import chomp, strip_ansi_escape
 
 
@@ -137,7 +136,7 @@ def test_verify_raises_when_scenario_not_found(  # noqa: D103
     caplog: pytest.LogCaptureFixture,
 ) -> None:
     _instance._scenario_names = ["invalid"]
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         _instance._verify()
 
     assert e.value.code == 1
@@ -151,7 +150,7 @@ def test_verify_raises_when_multiple_scenarios_not_found(  # noqa: D103
     caplog: pytest.LogCaptureFixture,
 ) -> None:
     _instance._scenario_names = ["invalid", "also invalid"]
-    with pytest.raises(MoleculeError) as e:
+    with pytest.raises(SystemExit) as e:
         _instance._verify()
 
     assert e.value.code == 1
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs tests/unit/command/init/test_scenario.py tests/unit/command/test_base.py tests/unit/command/test_login.py tests/unit/test_config.py tests/unit/test_scenarios.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["tests/unit/command/init/test_scenario.py::test_execute_scenario_exists", "tests/unit/command/init/test_scenario.py::test_execute_scenario_exists_collection_mode", "tests/unit/command/test_base.py::test_execute_cmdline_scenarios_missing", "tests/unit/command/test_base.py::test_execute_cmdline_scenarios_exit_destroy[always-subcommands0]", "tests/unit/command/test_base.py::test_execute_cmdline_scenarios_exit_destroy[never-subcommands1]", "tests/unit/command/test_login.py::test_get_hostname_does_not_match", "tests/unit/command/test_login.py::test_get_hostname_partial_match_with_multiple_hosts_raises", "tests/unit/command/test_login.py::test_get_hostname_no_host_flag_specified_on_cli_with_multiple_hosts_raises", "tests/unit/test_config.py::test_get_driver_name_from_state_file", "tests/unit/test_config.py::test_get_driver_name_raises_when_different_driver_used", "tests/unit/test_config.py::test_interpolate_raises_on_failed_interpolation", "tests/unit/test_config.py::test_validate_exists_when_validation_fails", "tests/unit/test_scenarios.py::test_verify_raises_when_scenario_not_found", "tests/unit/test_scenarios.py::test_verify_raises_when_multiple_scenarios_not_found"]

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
