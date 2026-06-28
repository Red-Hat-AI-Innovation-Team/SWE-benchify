#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/remove-v2-galaxy-api.yml b/changelogs/fragments/remove-v2-galaxy-api.yml
new file mode 100644
index 00000000000000..d173aea74302e3
--- /dev/null
+++ b/changelogs/fragments/remove-v2-galaxy-api.yml
@@ -0,0 +1,2 @@
+removed_features:
+- ansible-galaxy - removed the v2 Galaxy server API. Galaxy servers hosting collections must support v3.
diff --git a/lib/ansible/cli/galaxy.py b/lib/ansible/cli/galaxy.py
index 6fc310ea6b1b4d..5d85a57bbf1f14 100755
--- a/lib/ansible/cli/galaxy.py
+++ b/lib/ansible/cli/galaxy.py
@@ -654,23 +654,10 @@ def run(self):
             client_secret = server_options.pop('client_secret')
             token_val = server_options['token'] or NoTokenSentinel
             username = server_options['username']
-            api_version = server_options.pop('api_version')
             if server_options['validate_certs'] is None:
                 server_options['validate_certs'] = context.CLIARGS['resolved_validate_certs']
             validate_certs = server_options['validate_certs']
 
-            # This allows a user to explicitly force use of an API version when
-            # multiple versions are supported. This was added for testing
-            # against pulp_ansible and I'm not sure it has a practical purpose
-            # outside of this use case. As such, this option is not documented
-            # as of now
-            if api_version:
-                display.warning(
-                    f'The specified "api_version" configuration for the galaxy server "{server_key}" is '
-                    'not a public configuration, and may be removed at any time without warning.'
-                )
-                server_options['available_api_versions'] = {'v%s' % api_version: '/v%s' % api_version}
-
             # default case if no auth info is provided.
             server_options['token'] = None
 
@@ -697,12 +684,6 @@ def run(self):
             ))
 
         cmd_server = context.CLIARGS['api_server']
-        if context.CLIARGS['api_version']:
-            api_version = context.CLIARGS['api_version']
-            display.warning(
-                'The --api-version is not a public argument, and may be removed at any time without warning.'
-            )
-            galaxy_options['available_api_versions'] = {'v%s' % api_version: '/v%s' % api_version}
 
         cmd_token = GalaxyToken(token=context.CLIARGS['api_key'])
 
diff --git a/lib/ansible/config/manager.py b/lib/ansible/config/manager.py
index 33f398e199ba4d..cf67f53a65ad95 100644
--- a/lib/ansible/config/manager.py
+++ b/lib/ansible/config/manager.py
@@ -36,7 +36,6 @@
     ('password', False, 'str'),
     ('token', False, 'str'),
     ('auth_url', False, 'str'),
-    ('api_version', False, 'int'),
     ('validate_certs', False, 'bool'),
     ('client_id', False, 'str'),
     ('client_secret', False, 'str'),
@@ -45,7 +44,6 @@
 
 # config definition fields
 GALAXY_SERVER_ADDITIONAL = {
-    'api_version': {'default': None, 'choices': [2, 3]},
     'validate_certs': {'cli': [{'name': 'validate_certs'}]},
     'timeout': {'cli': [{'name': 'timeout'}]},
     'token': {'default': None},
diff --git a/lib/ansible/galaxy/api.py b/lib/ansible/galaxy/api.py
index b34be950f8c527..23c1e307f83b75 100644
--- a/lib/ansible/galaxy/api.py
+++ b/lib/ansible/galaxy/api.py
@@ -113,13 +113,7 @@ def wrapped(self, *args, **kwargs):
                 # url + '/api/' appended.
                 self.api_server = n_url
 
-                # Default to only supporting v1, if only v1 is returned we also assume that v2 is available even though
-                # it isn't returned in the available_versions dict.
-                available_versions = data.get('available_versions', {u'v1': u'v1/'})
-                if list(available_versions.keys()) == [u'v1']:
-                    available_versions[u'v2'] = u'v2/'
-
-                self._available_api_versions = available_versions
+                self._available_api_versions = available_versions = data['available_versions']
                 display.vvvv("Found API version '%s' with Galaxy server %s (%s)"
                              % (', '.join(available_versions.keys()), self.name, self.api_server))
 
@@ -131,15 +125,6 @@ def wrapped(self, *args, **kwargs):
                                    % (method.__name__, ", ".join(versions), ", ".join(available_versions),
                                       self.name, self.api_server))
 
-            # Warn only when we know we are talking to a collections API
-            if common_versions == {'v2'}:
-                display.deprecated(
-                    'The v2 Ansible Galaxy API is deprecated and no longer supported. '
-                    'Ensure that you have configured the ansible-galaxy CLI to utilize an '
-                    'updated and supported version of Ansible Galaxy.',
-                    version='2.20',
-                )
-
             return method(self, *args, **kwargs)
         return wrapped
     return decorator
@@ -213,11 +198,7 @@ def __init__(self, http_error, message):
             err_info = {}
 
         url_split = self.url.split('/')
-        if 'v2' in url_split:
-            galaxy_msg = err_info.get('message', http_error.reason)
-            code = err_info.get('code', 'Unknown')
-            full_error_msg = u"%s (HTTP Code: %d, Message: %s Code: %s)" % (message, self.http_code, galaxy_msg, code)
-        elif 'v3' in url_split:
+        if 'v3' in url_split:
             errors = err_info.get('errors', [])
             if not errors:
                 errors = [{}]  # Defaults are set below, we just need to make sure 1 error is present.
@@ -339,7 +320,7 @@ def __lt__(self, other_galaxy_api):
         return self._priority > other_galaxy_api._priority
 
     @property  # type: ignore[misc]  # https://github.com/python/mypy/issues/1362
-    @g_connect(['v1', 'v2', 'v3'])
+    @g_connect(['v1', 'v3'])
     def available_api_versions(self):
         # Calling g_connect will populate self._available_api_versions
         return self._available_api_versions
@@ -644,7 +625,7 @@ def delete_role(self, github_user, github_repo):
 
     # Collection APIs #
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def publish_collection(self, collection_path):
         """
         Publishes a collection to a Galaxy server and returns the import task URI.
@@ -679,18 +660,14 @@ def publish_collection(self, collection_path):
             'Content-length': len(b_form_data),
         }
 
-        if 'v3' in self.available_api_versions:
-            n_url = _urljoin(self.api_server, self.available_api_versions['v3'], 'artifacts', 'collections') + '/'
-        else:
-            n_url = _urljoin(self.api_server, self.available_api_versions['v2'], 'collections') + '/'
-
+        n_url = _urljoin(self.api_server, self.available_api_versions['v3'], 'artifacts', 'collections') + '/'
         resp = self._call_galaxy(n_url, args=b_form_data, headers=headers, method='POST', auth_required=True,
                                  error_context_msg='Error when publishing collection to %s (%s)'
                                                    % (self.name, self.api_server))
 
         return urljoin(self.api_server, resp['task'])
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def wait_import_task(self, task_url, timeout=0):
         """
         Waits until the import process on the Galaxy server has completed or the timeout is reached.
@@ -748,7 +725,7 @@ def wait_import_task(self, task_url, timeout=0):
                 data['error'].get('description', "Unknown error, see %s for more details" % task_url))
             raise AnsibleError("Galaxy import process failed: %s (Code: %s)" % (description, code))
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def get_collection_metadata(self, namespace, name):
         """
         Gets the collection information from the Galaxy server about a specific Collection.
@@ -757,18 +734,11 @@ def get_collection_metadata(self, namespace, name):
         :param name: The collection name.
         return: CollectionMetadata about the collection.
         """
-        if 'v3' in self.available_api_versions:
-            api_path = self.available_api_versions['v3']
-            field_map = [
-                ('created_str', 'created_at'),
-                ('modified_str', 'updated_at'),
-            ]
-        else:
-            api_path = self.available_api_versions['v2']
-            field_map = [
-                ('created_str', 'created'),
-                ('modified_str', 'modified'),
-            ]
+        api_path = self.available_api_versions['v3']
+        field_map = [
+            ('created_str', 'created_at'),
+            ('modified_str', 'updated_at'),
+        ]
 
         info_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, '/')
         error_context_msg = 'Error when getting the collection info for %s.%s from %s (%s)' \
@@ -781,7 +751,7 @@ def get_collection_metadata(self, namespace, name):
 
         return CollectionMetadata(namespace, name, **metadata)
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def get_collection_version_metadata(self, namespace, name, version):
         """
         Gets the collection information from the Galaxy server about a specific Collection version.
@@ -791,7 +761,7 @@ def get_collection_version_metadata(self, namespace, name, version):
         :param version: Version of the collection to get the information for.
         :return: CollectionVersionMetadata about the collection at the version requested.
         """
-        api_path = self.available_api_versions.get('v3', self.available_api_versions.get('v2'))
+        api_path = self.available_api_versions['v3']
         url_paths = [self.api_server, api_path, 'collections', namespace, name, 'versions', version, '/']
 
         n_collection_url = _urljoin(*url_paths)
@@ -815,7 +785,7 @@ def get_collection_version_metadata(self, namespace, name, version):
                                          download_url, data['artifact']['sha256'],
                                          data['metadata']['dependencies'], data['href'], signatures)
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def get_collection_versions(self, namespace, name):
         """
         Gets a list of available versions for a collection on a Galaxy server.
@@ -824,17 +794,10 @@ def get_collection_versions(self, namespace, name):
         :param name: The collection name.
         :return: A list of versions that are available.
         """
-        relative_link = False
-        if 'v3' in self.available_api_versions:
-            api_path = self.available_api_versions['v3']
-            pagination_path = ['links', 'next']
-            relative_link = True  # AH pagination results are relative an not an absolute URI.
-        else:
-            api_path = self.available_api_versions['v2']
-            pagination_path = ['next']
+        api_path = self.available_api_versions['v3']
+        pagination_path = ['links', 'next']
 
-        page_size_name = 'limit' if 'v3' in self.available_api_versions else 'page_size'
-        versions_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, 'versions', '/?%s=%d' % (page_size_name, COLLECTION_PAGE_SIZE))
+        versions_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, 'versions', '/?limit=%d' % COLLECTION_PAGE_SIZE)
         versions_url_info = urlparse(versions_url)
         cache_key = versions_url_info.path
 
@@ -889,11 +852,10 @@ def get_collection_versions(self, namespace, name):
 
             if not next_link:
                 break
-            elif relative_link:
-                next_link_info = urlparse(next_link)
-                if not next_link_info.scheme and not next_link_info.path.startswith('/'):
-                    raise AnsibleError(f'Invalid non absolute pagination link: {next_link}')
-                next_link = urljoin(self.api_server, next_link)
+            next_link_info = urlparse(next_link)
+            if not next_link_info.scheme and not next_link_info.path.startswith('/'):
+                raise AnsibleError(f'Invalid non absolute pagination link: {next_link}')
+            next_link = urljoin(self.api_server, next_link)
 
             data = self._call_galaxy(to_native(next_link, errors='surrogate_or_strict'),
                                      error_context_msg=error_context_msg, cache=True, cache_key=cache_key)
@@ -901,7 +863,7 @@ def get_collection_versions(self, namespace, name):
 
         return versions
 
-    @g_connect(['v2', 'v3'])
+    @g_connect(['v3'])
     def get_collection_signatures(self, namespace, name, version):
         """
         Gets the collection signatures from the Galaxy server about a specific Collection version.
@@ -911,7 +873,7 @@ def get_collection_signatures(self, namespace, name, version):
         :param version: Version of the collection to get the information for.
         :return: A list of signature strings.
         """
-        api_path = self.available_api_versions.get('v3', self.available_api_versions.get('v2'))
+        api_path = self.available_api_versions['v3']
         url_paths = [self.api_server, api_path, 'collections', namespace, name, 'versions', version, '/']
 
         n_collection_url = _urljoin(*url_paths)
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
