#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/src/ansiblelint/cli.py b/src/ansiblelint/cli.py
index b22e2decb3..5e1fb73f67 100644
--- a/src/ansiblelint/cli.py
+++ b/src/ansiblelint/cli.py
@@ -26,6 +26,7 @@
     normpath,
 )
 from ansiblelint.loaders import IGNORE_FILE
+from ansiblelint.output import console_stderr
 from ansiblelint.schemas.main import validate_file_schema
 from ansiblelint.yaml_utils import clean_json
 
@@ -74,7 +75,14 @@ def load_config(
     if config_file:
         config_path = os.path.abspath(config_file)
         if not os.path.exists(config_path):
-            _logger.error("Config file not found '%s'", config_path)
+            msg = f"Config file not found '{config_path}'"
+            if any(
+                isinstance(h, logging.FileHandler)
+                and h.baseFilename != os.path.abspath(os.devnull)
+                for h in logging.root.handlers
+            ):
+                _logger.error(msg)
+            console_stderr.print(f"[error]{msg}[/]")
             sys.exit(RC.INVALID_CONFIG)
     config_path = config_path or get_config_path(None, project_path=project_path)
     if not config_path or not os.path.exists(config_path):
@@ -90,7 +98,14 @@ def load_config(
     )
 
     for error in validate_file_schema(config_lintable):
-        _logger.error("Invalid configuration file %s. %s", config_path, error)
+        msg = f"Invalid configuration file {config_path}. {error}"
+        if any(
+            isinstance(h, logging.FileHandler)
+            and h.baseFilename != os.path.abspath(os.devnull)
+            for h in logging.root.handlers
+        ):
+            _logger.error(msg)
+        console_stderr.print(f"[error]{msg}[/]")
         sys.exit(RC.INVALID_CONFIG)
 
     config = clean_json(config_lintable.data)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
