#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/units/_internal/templating/test_jinja_bits.py b/test/units/_internal/templating/test_jinja_bits.py
index 35d24c536c7156..97fe7b21cae475 100644
--- a/test/units/_internal/templating/test_jinja_bits.py
+++ b/test/units/_internal/templating/test_jinja_bits.py
@@ -9,10 +9,11 @@
 import pytest
 import pytest_mock
 
+from ansible._internal._templating._access import NotifiableAccessContextBase
 from ansible.errors import AnsibleUndefinedVariable, AnsibleTemplateError
 from ansible._internal._templating._errors import AnsibleTemplatePluginRuntimeError
 from ansible.module_utils._internal._datatag import AnsibleTaggedObject
-from ansible._internal._templating._jinja_common import CapturedExceptionMarker, MarkerError, Marker, UndefinedMarker, JinjaCallContext
+from ansible._internal._templating._jinja_common import CapturedExceptionMarker, MarkerError, Marker, UndefinedMarker
 from ansible._internal._templating._utils import TemplateContext
 from ansible._internal._datatag._tags import TrustedAsTemplate
 from ansible._internal._templating._jinja_bits import (AnsibleEnvironment, TemplateOverrides, _TEMPLATE_OVERRIDE_FIELD_NAMES, defer_template_error,
@@ -445,6 +446,15 @@ def test_mutation_methods(template: str, result: object) -> None:
     assert TemplateEngine().template(TRUST.tag(template)) == result
 
 
+class ExampleMarkerAccessTracker(NotifiableAccessContextBase):
+    def __init__(self) -> None:
+        self._type_interest = frozenset(Marker._concrete_subclasses)
+        self._markers: list[Marker] = []
+
+    def _notify(self, o: Marker) -> None:
+        self._markers.append(o)
+
+
 @pytest.mark.parametrize("template", (
     '"'"'{{ adict["bogus"] | default("ok") }}'"'"',
     '"'"'{{ adict.bogus | default("ok") }}'"'"',
@@ -454,6 +464,7 @@ def test_marker_access_getattr_and_getitem(template: str) -> None:
     # the absence of a JinjaCallContext should cause the access done by getattr and getitem not to trip when a marker is encountered
     assert TemplateEngine(variables=dict(adict={})).template(TRUST.tag(template)) == "ok"
 
-    with pytest.raises(AnsibleUndefinedVariable):
-        with JinjaCallContext(accept_lazy_markers=False):  # the access done by getattr and getitem should immediately trip when a marker is encountered
-            TemplateEngine(variables=dict(adict={})).template(TRUST.tag(template))
+    with ExampleMarkerAccessTracker() as tracker:  # the access done by getattr and getitem should immediately trip when a marker is encountered
+        TemplateEngine(variables=dict(adict={})).template(TRUST.tag(template))
+
+    assert type(tracker._markers[0]) is UndefinedMarker  # pylint: disable=unidiomatic-typecheck
diff --git a/test/units/_internal/templating/test_templar.py b/test/units/_internal/templating/test_templar.py
index 8da9bfc0a7d861..8565a9dbf0505a 100644
--- a/test/units/_internal/templating/test_templar.py
+++ b/test/units/_internal/templating/test_templar.py
@@ -1111,3 +1111,15 @@ def test_filter_generator() -> None:
     te = TemplateEngine(variables=variables)
     te.template(TRUST.tag("{{ bar }}"))
     te.template(TRUST.tag("{{ lookup('"'"'vars'"'"', '"'"'bar'"'"') }}"))
+
+
+def test_call_context_reset() -> None:
+    """Ensure that new template invocations do not inherit trip behavior from running Jinja plugins."""
+    templar = TemplateEngine(variables=dict(
+        somevar=TRUST.tag("{{ somedict.somekey | default('"'"'ok'"'"') }}"),
+        somedict=dict(
+            somekey=TRUST.tag("{{ not_here }}"),
+        )
+    ))
+
+    assert templar.template(TRUST.tag("{{ lookup('"'"'vars'"'"', '"'"'somevar'"'"') }}")) == '"'"'ok'"'"'
diff --git a/test/units/plugins/lookup/test_template.py b/test/units/plugins/lookup/test_template.py
new file mode 100644
index 00000000000000..5f77b73847f7ae
--- /dev/null
+++ b/test/units/plugins/lookup/test_template.py
@@ -0,0 +1,31 @@
+from __future__ import annotations
+
+import pathlib
+
+from ansible._internal._templating._utils import Omit
+from ansible.parsing.dataloader import DataLoader
+from ansible.template import Templar, trust_as_template
+
+
+def test_no_finalize_marker_passthru(tmp_path: pathlib.Path) -> None:
+    """Return an Undefined marker from a template lookup to ensure that the internal templating operation does not finalize its result."""
+    template_path = tmp_path / '"'"'template.txt'"'"'
+    template_path.write_text("{{ bogusvar }}")
+
+    templar = Templar(loader=DataLoader(), variables=dict(template_path=str(template_path)))
+
+    assert templar.template(trust_as_template('"'"'{{ lookup("template", template_path) | default("pass") }}'"'"')) == "pass"
+
+
+def test_no_finalize_omit_passthru(tmp_path: pathlib.Path) -> None:
+    """Return an Omit scalar from a template lookup to ensure that the internal templating operation does not finalize its result."""
+    template_path = tmp_path / '"'"'template.txt'"'"'
+    template_path.write_text("{{ omitted }}")
+
+    data = dict(omitted=trust_as_template("{{ omit }}"), template_path=str(template_path))
+
+    # The result from the lookup should be an Omit value, since the result of the template lookup'"'"'s internal templating call should not be finalized.
+    # If it were, finalize would trip the Omit and raise an error about a top-level template result resolving to an Omit scalar.
+    res = Templar(loader=DataLoader(), variables=data).template(trust_as_template("{{ lookup('"'"'template'"'"', template_path) | type_debug }}"))
+
+    assert res == type(Omit).__name__
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/units/_internal/templating/test_jinja_bits.py test/units/_internal/templating/test_templar.py test/units/plugins/lookup/test_template.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/_internal/templating/test_templar.py::test_call_context_reset", "test/units/plugins/lookup/test_template.py::test_no_finalize_marker_passthru", "test/units/plugins/lookup/test_template.py::test_no_finalize_omit_passthru"]

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
