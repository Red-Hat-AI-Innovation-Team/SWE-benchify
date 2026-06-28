#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/template_lookup_skip_finalize.yml b/changelogs/fragments/template_lookup_skip_finalize.yml
new file mode 100644
index 00000000000000..7cbc1dfd9cf18d
--- /dev/null
+++ b/changelogs/fragments/template_lookup_skip_finalize.yml
@@ -0,0 +1,6 @@
+bugfixes:
+  - template lookup - Skip finalization on the internal templating operation to allow markers to be returned and handled by, e.g. the ``default`` filter.
+    Previously, finalization tripped markers, causing an exception to end processing of the current template pipeline.
+    (https://github.com/ansible/ansible/issues/85674)
+  - templating - Avoid tripping markers within Jinja generated code.
+    (https://github.com/ansible/ansible/issues/85674)
diff --git a/lib/ansible/_internal/_templating/_engine.py b/lib/ansible/_internal/_templating/_engine.py
index 4beb1806291f05..094d24dd86ad73 100644
--- a/lib/ansible/_internal/_templating/_engine.py
+++ b/lib/ansible/_internal/_templating/_engine.py
@@ -44,7 +44,7 @@
     _finalize_template_result,
     FinalizeMode,
 )
-from ._jinja_common import _TemplateConfig, MarkerError, ExceptionMarker
+from ._jinja_common import _TemplateConfig, MarkerError, ExceptionMarker, JinjaCallContext
 from ._lazy_containers import _AnsibleLazyTemplateMixin
 from ._marker_behaviors import MarkerBehavior, FAIL_ON_UNDEFINED
 from ._transform import _type_transform_mapping
@@ -260,6 +260,7 @@ def template(
             with (
                 TemplateContext(template_value=variable, templar=self, options=options, stop_on_template=stop_on_template) as ctx,
                 DeprecatedAccessAuditContext.when(ctx.is_top_level),
+                JinjaCallContext(accept_lazy_markers=True),  # let default Jinja marker behavior apply, since we're descending into a new template
             ):
                 try:
                     if not value_is_str:
diff --git a/lib/ansible/plugins/lookup/template.py b/lib/ansible/plugins/lookup/template.py
index 141d6684746e64..76cd8a9ceec25d 100644
--- a/lib/ansible/plugins/lookup/template.py
+++ b/lib/ansible/plugins/lookup/template.py
@@ -107,6 +107,7 @@
 from ansible.plugins.lookup import LookupBase
 from ansible.template import trust_as_template
 from ansible._internal._templating import _template_vars
+from ansible._internal._templating._engine import TemplateOptions, TemplateOverrides
 from ansible.utils.display import Display
 
 
@@ -174,7 +175,11 @@ def run(self, terms, variables=None, **kwargs):
                 )
 
                 data_templar = templar.copy_with_new_env(available_variables=vars, searchpath=searchpath)
-                res = data_templar.template(template_data, escape_backslashes=False, overrides=overrides)
+                # use the internal template API to avoid forced top-level finalization behavior imposed by the public API
+                res = data_templar._engine.template(template_data, options=TemplateOptions(
+                    escape_backslashes=False,
+                    overrides=TemplateOverrides.from_kwargs(overrides),
+                ))
 
                 ret.append(res)
             else:
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
