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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/units/_internal/templating/test_jinja_bits.py test/units/_internal/templating/test_templar.py test/units/plugins/lookup/test_template.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/_internal/templating/test_templar.py::test_call_context_reset", "test/units/plugins/lookup/test_template.py::test_no_finalize_marker_passthru", "test/units/plugins/lookup/test_template.py::test_no_finalize_omit_passthru"]
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
