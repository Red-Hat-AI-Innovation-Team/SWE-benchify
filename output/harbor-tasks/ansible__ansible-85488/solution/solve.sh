#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/plugins_fix_origin.yml b/changelogs/fragments/plugins_fix_origin.yml
new file mode 100644
index 00000000000000..55d5b23228c2fd
--- /dev/null
+++ b/changelogs/fragments/plugins_fix_origin.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - plugins config, get_option_and_origin now correctly displays the value and origin of the option.
diff --git a/lib/ansible/config/manager.py b/lib/ansible/config/manager.py
index c4b0ffbc3624f9..33f398e199ba4d 100644
--- a/lib/ansible/config/manager.py
+++ b/lib/ansible/config/manager.py
@@ -450,13 +450,17 @@ def _find_yaml_config_files(self):
         pass
 
     def get_plugin_options(self, plugin_type, name, keys=None, variables=None, direct=None):
+        options, dummy = self.get_plugin_options_and_origins(plugin_type, name, keys=keys, variables=variables, direct=direct)
+        return options
 
+    def get_plugin_options_and_origins(self, plugin_type, name, keys=None, variables=None, direct=None):
         options = {}
+        origins = {}
         defs = self.get_configuration_definitions(plugin_type=plugin_type, name=name)
         for option in defs:
-            options[option] = self.get_config_value(option, plugin_type=plugin_type, plugin_name=name, keys=keys, variables=variables, direct=direct)
-
-        return options
+            options[option], origins[option] = self.get_config_value_and_origin(option, plugin_type=plugin_type, plugin_name=name, keys=keys,
+                                                                                variables=variables, direct=direct)
+        return options, origins
 
     def get_plugin_vars(self, plugin_type, name):
 
diff --git a/lib/ansible/plugins/__init__.py b/lib/ansible/plugins/__init__.py
index 833f18e34e68b0..e259960299e29b 100644
--- a/lib/ansible/plugins/__init__.py
+++ b/lib/ansible/plugins/__init__.py
@@ -79,6 +79,7 @@ class AnsiblePlugin(_AnsiblePluginInfoMixin, _ConfigurablePlugin, metaclass=abc.
 
     def __init__(self):
         self._options = {}
+        self._origins = {}
         self._defs = None
 
     @property
@@ -98,11 +99,16 @@ def matches_name(self, possible_names):
         return bool(possible_fqcns.intersection(set(self.ansible_aliases)))
 
     def get_option_and_origin(self, option, hostvars=None):
-        try:
-            option_value, origin = C.config.get_config_value_and_origin(option, plugin_type=self.plugin_type, plugin_name=self._load_name, variables=hostvars)
-        except AnsibleError as e:
-            raise KeyError(str(e))
-        return option_value, origin
+        if option not in self._options:
+            try:
+                # some plugins don't use set_option(s) and cannot use direct settings, so this populates the local copy for them
+                self._options[option], self._origins[option] = C.config.get_config_value_and_origin(option, plugin_type=self.plugin_type,
+                                                                                                    plugin_name=self._load_name, variables=hostvars)
+            except AnsibleError as e:
+                # callers expect key error on missing
+                raise KeyError() from e
+
+        return self._options[option], self._origins[option]
 
     @functools.cached_property
     def __plugin_info(self):
@@ -113,11 +119,10 @@ def __plugin_info(self):
         return _plugin_info.get_plugin_info(self)
 
     def get_option(self, option, hostvars=None):
-
         if option not in self._options:
-            option_value, dummy = self.get_option_and_origin(option, hostvars=hostvars)
-            self.set_option(option, option_value)
-        return self._options.get(option)
+            # let it populate _options
+            self.get_option_and_origin(option, hostvars=hostvars)
+        return self._options[option]
 
     def get_options(self, hostvars=None):
         options = {}
@@ -127,6 +132,7 @@ def get_options(self, hostvars=None):
 
     def set_option(self, option, value):
         self._options[option] = C.config.get_config_value(option, plugin_type=self.plugin_type, plugin_name=self._load_name, direct={option: value})
+        self._origins[option] = 'Direct'
         _display._report_config_warnings(self.__plugin_info)
 
     def set_options(self, task_keys=None, var_options=None, direct=None):
@@ -137,12 +143,14 @@ def set_options(self, task_keys=None, var_options=None, direct=None):
         :arg var_options: Dict with either 'connection variables'
         :arg direct: Dict with 'direct assignment'
         """
-        self._options = C.config.get_plugin_options(self.plugin_type, self._load_name, keys=task_keys, variables=var_options, direct=direct)
+        self._options, self._origins = C.config.get_plugin_options_and_origins(self.plugin_type, self._load_name, keys=task_keys,
+                                                                               variables=var_options, direct=direct)
 
         # allow extras/wildcards from vars that are not directly consumed in configuration
         # this is needed to support things like winrm that can have extended protocol options we don't directly handle
         if self.allow_extras and var_options and '_extras' in var_options:
             # these are largely unvalidated passthroughs, either plugin or underlying API will validate
+            # TODO: deprecate and remove, most plugins that needed this don't use this facility anymore
             self._options['_extras'] = var_options['_extras']
         _display._report_config_warnings(self.__plugin_info)
 
diff --git a/lib/ansible/plugins/callback/__init__.py b/lib/ansible/plugins/callback/__init__.py
index 2fc52c45c748c4..aa8beaea290154 100644
--- a/lib/ansible/plugins/callback/__init__.py
+++ b/lib/ansible/plugins/callback/__init__.py
@@ -228,10 +228,14 @@ def _init_callback_methods(self) -> None:
 
     def set_option(self, k, v):
         self._plugin_options[k] = C.config.get_config_value(k, plugin_type=self.plugin_type, plugin_name=self._load_name, direct={k: v})
+        self._origins[k] = 'direct'
 
     def get_option(self, k, hostvars=None):
         return self._plugin_options[k]
 
+    def get_option_and_origin(self, k, hostvars=None):
+        return self._plugin_options[k], self._origins[k]
+
     def has_option(self, option):
         return (option in self._plugin_options)
 
@@ -241,7 +245,8 @@ def set_options(self, task_keys=None, var_options=None, direct=None):
         """
 
         # load from config
-        self._plugin_options = C.config.get_plugin_options(self.plugin_type, self._load_name, keys=task_keys, variables=var_options, direct=direct)
+        self._plugin_options, self._origins = C.config.get_plugin_options_and_origins(self.plugin_type, self._load_name,
+                                                                                      keys=task_keys, variables=var_options, direct=direct)
 
     @staticmethod
     def host_label(result: CallbackTaskResult) -> str:
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
