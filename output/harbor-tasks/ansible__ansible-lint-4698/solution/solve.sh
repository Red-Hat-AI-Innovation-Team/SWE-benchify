#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/utils.py b/src/ansiblelint/utils.py
index a3da59513d..daf8ad64b3 100644
--- a/src/ansiblelint/utils.py
+++ b/src/ansiblelint/utils.py
@@ -63,16 +63,15 @@
 )
 from ansible.template import Templar
 from ansible.utils.collection_loader import AnsibleCollectionConfig
+from jinja2 import Environment, nodes
+from jinja2.exceptions import TemplateError, TemplateSyntaxError
 from packaging.version import Version
 from yaml.composer import Composer
 from yaml.parser import ParserError
 from yaml.representer import RepresenterError
 from yaml.scanner import ScannerError
 
-from ansiblelint._internal.rules import (
-    AnsibleParserErrorRule,
-    RuntimeErrorRule,
-)
+from ansiblelint._internal.rules import AnsibleParserErrorRule, RuntimeErrorRule
 from ansiblelint.app import App, get_app
 from ansiblelint.config import Options, get_deps_versions, options
 from ansiblelint.constants import (
@@ -169,6 +168,32 @@ def mock_filter(left: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
     return left
 
 
+def has_lookup_function_calls(varname: str) -> bool:
+    """Check if a template string contains lookup, query, or q function calls using AST parsing.
+
+    This function parses Jinja2 templates and looks for function calls to
+    'lookup', 'query', or 'q' by examining the AST).
+
+    :param varname: The template string to analyze
+    :return: True if lookup functions are found, False otherwise
+    """
+    lookup_names = {"lookup", "query", "q"}
+
+    try:
+        env = Environment(autoescape=True)
+        ast_tree = env.parse(varname)
+
+        for node in ast_tree.find_all(nodes.Call):
+            if isinstance(node.node, nodes.Name) and node.node.name in lookup_names:
+                return True
+    except (TemplateSyntaxError, TemplateError, AttributeError):
+        # Fallback to regex for edge cases where Jinja2 parsing fails
+        fallback_pattern = re.compile(r"\(?(lookup|query|q)\)?\s*\(")
+        return bool(fallback_pattern.search(varname))
+    else:
+        return False
+
+
 def ansible_template(
     basedir: Path,
     varname: Any,
@@ -200,13 +225,13 @@ def ansible_template(
     re_filter_fqcn = re.compile(r"\w+\.\w+\.\w+")
     re_filter_in_err = re.compile(r"Could not load \"(\w+)\"")
     re_valid_filter = re.compile(r"^\w+(\.\w+\.\w+)?$")
-    re_lookup_functions = re.compile(r"\b(lookup|query|q)\s*\(")
     templar = ansible_templar(basedir=basedir, templatevars=templatevars)
+    ansible_core_2_19 = Version("2.19")
+    deps = get_deps_versions()
 
     # Skip lookups for ansible-core >= 2.19; use disable_lookups for older versions
-    if re_lookup_functions.search(str(varname)):
-        deps = get_deps_versions()
-        if deps["ansible-core"] and deps["ansible-core"] >= Version("2.19"):
+    if has_lookup_function_calls(str(varname)):
+        if deps["ansible-core"] and deps["ansible-core"] >= ansible_core_2_19:
             return varname
         kwargs["disable_lookups"] = True
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
