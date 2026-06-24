#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/ansible-config/tasks/main.yml b/test/integration/targets/ansible-config/tasks/main.yml
index 3fbcb56342a7b1..c3b46fa4daf6bf 100644
--- a/test/integration/targets/ansible-config/tasks/main.yml
+++ b/test/integration/targets/ansible-config/tasks/main.yml
@@ -73,9 +73,6 @@
         password:
           value: my_pass
           origin: role_path ~ "/files/galaxy_server.ini"
-        api_version:
-          value: None
-          origin: default
       release_galaxy:
       test_galaxy:
       my_galaxy_ng:
@@ -120,7 +117,6 @@
           auth_url:
           username:
           password:
-          api_version:
           timeout:
       origin: '"'"'{{ role_path ~ "/files/galaxy_server.ini" }}'"'"'
       gs_keys: '"'"'{{ gs.keys()|list|sort }}'"'"'
diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/install.yml b/test/integration/targets/ansible-galaxy-collection/tasks/install.yml
index e7af6bab7334cf..2de0f11f4473c4 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/install.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/install.yml
@@ -337,27 +337,6 @@
   environment:
     ANSIBLE_GALAXY_SERVER_LIST: bogus
 
-# pulp_v2 doesn'"'"'t require auth
-- when: v2|default(false)
-  block:
-    - name: install a collection with an empty server list - {{ test_id }}
-      command: ansible-galaxy collection install namespace5.name -s '"'"'{{ test_server }}'"'"' --api-version 2 {{ galaxy_verbosity }}
-      register: install_empty_server_list
-      environment:
-        ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/ansible_collections'"'"'
-        ANSIBLE_GALAXY_SERVER_LIST: '"'"''"'"'
-
-    - name: get result of a collection with an empty server list - {{ test_id }}
-      slurp:
-        path: '"'"'{{ galaxy_dir }}/ansible_collections/namespace5/name/MANIFEST.json'"'"'
-      register: install_empty_server_list_actual
-
-    - name: assert install a collection with an empty server list - {{ test_id }}
-      assert:
-        that:
-        - '"'"'"Installing '"'"''"'"'namespace5.name:1.0.0'"'"''"'"' to" in install_empty_server_list.stdout'"'"'
-        - (install_empty_server_list_actual.content | b64decode | from_json).collection_info.version == '"'"'1.0.0'"'"'
-
 - name: create test requirements file with both roles and collections - {{ test_id }}
   copy:
     content: |
@@ -764,40 +743,38 @@
     - namespace8
     - namespace9
 
-- when: not v2|default(false)
-  block:
-    - name: install cache.cache at the current latest version
-      command: ansible-galaxy collection install cache.cache -s '"'"'{{ test_name }}'"'"' -vvv
-      environment:
-        ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/ansible_collections'"'"'
+- name: install cache.cache at the current latest version
+  command: ansible-galaxy collection install cache.cache -s '"'"'{{ test_name }}'"'"' -vvv
+  environment:
+    ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/ansible_collections'"'"'
 
-    - set_fact:
-        cache_version_build: '"'"'{{ (cache_version_build | int) + 1 }}'"'"'
+- set_fact:
+    cache_version_build: '"'"'{{ (cache_version_build | int) + 1 }}'"'"'
 
-    - name: publish update for cache.cache test
-      setup_collections:
-        server: galaxy_ng
-        collections:
-        - namespace: cache
-          name: cache
-          version: 1.0.{{ cache_version_build }}
+- name: publish update for cache.cache test
+  setup_collections:
+    server: galaxy_ng
+    collections:
+    - namespace: cache
+      name: cache
+      version: 1.0.{{ cache_version_build }}
 
-    - name: make sure the cache version list is ignored on a collection version change - {{ test_id }}
-      command: ansible-galaxy collection install cache.cache -s '"'"'{{ test_name }}'"'"' --force -vvv
-      register: install_cached_update
-      environment:
-        ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/ansible_collections'"'"'
+- name: make sure the cache version list is ignored on a collection version change - {{ test_id }}
+  command: ansible-galaxy collection install cache.cache -s '"'"'{{ test_name }}'"'"' --force -vvv
+  register: install_cached_update
+  environment:
+    ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/ansible_collections'"'"'
 
-    - name: get result of cache version list is ignored on a collection version change - {{ test_id }}
-      slurp:
-        path: '"'"'{{ galaxy_dir }}/ansible_collections/cache/cache/MANIFEST.json'"'"'
-      register: install_cached_update_actual
+- name: get result of cache version list is ignored on a collection version change - {{ test_id }}
+  slurp:
+    path: '"'"'{{ galaxy_dir }}/ansible_collections/cache/cache/MANIFEST.json'"'"'
+  register: install_cached_update_actual
 
-    - name: assert cache version list is ignored on a collection version change - {{ test_id }}
-      assert:
-        that:
-        - '"'"'"Installing '"'"''"'"'cache.cache:1.0." ~ cache_version_build ~ "'"'"''"'"' to" in install_cached_update.stdout'"'"'
-        - (install_cached_update_actual.content | b64decode | from_json).collection_info.version == '"'"'1.0.'"'"' ~ cache_version_build
+- name: assert cache version list is ignored on a collection version change - {{ test_id }}
+  assert:
+    that:
+    - '"'"'"Installing '"'"''"'"'cache.cache:1.0." ~ cache_version_build ~ "'"'"''"'"' to" in install_cached_update.stdout'"'"'
+    - (install_cached_update_actual.content | b64decode | from_json).collection_info.version == '"'"'1.0.'"'"' ~ cache_version_build
 
 - name: install collection with symlink - {{ test_id }}
   command: ansible-galaxy collection install symlink.symlink -s '"'"'{{ test_name }}'"'"' {{ galaxy_verbosity }}
diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/main.yml b/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
index e17d6aa1224d13..7bcc38286d88df 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
@@ -74,13 +74,8 @@
     test_server: '"'"'{{ item.server }}'"'"'
     test_api_server: '"'"'{{ item.api_server|default(item.server) }}'"'"'
   loop:
-  - name: pulp_v2
-    api_server: '"'"'{{ galaxy_ng_server }}'"'"'
-    server: '"'"'{{ pulp_server }}primary/api/'"'"'
-    v2: true
   - name: galaxy_ng
     server: '"'"'{{ galaxy_ng_server }}'"'"'
-    v3: true
 
 - include_tasks: setup_gpg.yml
 
@@ -109,7 +104,6 @@
     test_server: '"'"'{{ item.server }}'"'"'
     test_api_server: '"'"'{{ item.api_server|default(item.server) }}'"'"'
     requires_auth: '"'"'{{ item.requires_auth|default(false) }}'"'"'
-    v2: '"'"'{{ item.v2|default(false) }}'"'"'
   args:
     apply:
       environment:
@@ -117,12 +111,7 @@
   loop:
   - name: galaxy_ng
     server: '"'"'{{ galaxy_ng_server }}'"'"'
-    v3: true
     requires_auth: true
-  - name: pulp_v2
-    server: '"'"'{{ pulp_server }}primary/api/'"'"'
-    api_server: '"'"'{{ galaxy_ng_server }}'"'"'
-    v2: true
 
 - name: test installing and downloading collections with the range of supported resolvelib versions
   include_tasks: supported_resolvelib.yml
@@ -184,7 +173,7 @@
     - >-
       "'"'"'secondary.name:1.0.0'"'"' obtained from server secondary"
       in install_cross_dep.stdout
-    # pulp_v2 is highest in the list so it will find it there first
+    # galaxy_ng is highest in the list so it will find it there first
     - >-
       "'"'"'parent_dep.parent_collection:1.0.0'"'"' obtained from server galaxy_ng"
       in install_cross_dep.stdout
@@ -214,9 +203,9 @@
         ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}'"'"'
         ANSIBLE_CONFIG: '"'"'{{ galaxy_dir }}/ansible.cfg'"'"'
   vars:
-    test_api_fallback: '"'"'galaxy_ng'"'"'
+    test_api_fallback: '"'"'secondary'"'"'
     test_api_fallback_versions: '"'"'v3, pulp-v3, v1'"'"'
-    test_name: '"'"'pulp_v2'"'"'
+    test_name: '"'"'galaxy_ng'"'"'
 
 - name: run ansible-galaxy collection list tests
   include_tasks: list.yml
diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/verify.yml b/test/integration/targets/ansible-galaxy-collection/tasks/verify.yml
index 9c482037c2c843..96c2245696e988 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/verify.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/verify.yml
@@ -13,8 +13,8 @@
   args:
     chdir: '"'"'{{ galaxy_dir }}'"'"'
 
-- name: publish collection - {{ test_name }}
-  command: ansible-galaxy collection publish ansible_test-verify-1.0.0.tar.gz -s {{ test_name }} {{ galaxy_verbosity }}
+- name: publish to fallback server {{ test_api_fallback }}
+  command: ansible-galaxy collection publish ansible_test-verify-1.0.0.tar.gz -s {{ test_api_fallback }} {{ galaxy_verbosity }}
   args:
     chdir: '"'"'{{ galaxy_dir }}'"'"'
 
@@ -28,25 +28,23 @@
       - verify.rc != 0
       - verify.stderr is contains "'"'"'file'"'"' type is not supported. The format namespace.name is expected."
 
-- name: install the collection from the server
-  command: ansible-galaxy collection install ansible_test.verify:1.0.0 -s {{ test_api_fallback }} {{ galaxy_verbosity }}
+- name: install the collection from the secondary server
+  command: ansible-galaxy collection install ansible_test.verify:1.0.0 {{ galaxy_verbosity }}
 
 # This command is hardcoded with -vvvv purposefully to evaluate extra verbosity messages
 - name: verify the collection against the first valid server
   command: ansible-galaxy collection verify ansible_test.verify:1.0.0 -vvvv {{ galaxy_verbosity }}
   register: verify
-  vars:
-    # This sets a specific precedence that the tests are expecting
-    ANSIBLE_GALAXY_SERVER_LIST: offline,secondary,pulp_v2,galaxy_ng
 
 - assert:
     that:
       - verify is success
-      - >-
-        "Found API version '"'"'" + test_api_fallback_versions + "'"'"' with Galaxy server " + test_api_fallback in verify.stdout
+      - verify.stdout is search(msg)
+  vars:
+    msg: "Found API version '"'"'{{ test_api_fallback_versions }}'"'"' with Galaxy server {{ test_api_fallback }}"
 
 - name: verify the installed collection against the server
-  command: ansible-galaxy collection verify ansible_test.verify:1.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:1.0.0 {{ galaxy_verbosity }}
   register: verify
 
 - assert:
@@ -55,10 +53,10 @@
       - "'"'"'Collection ansible_test.verify contains modified content'"'"' not in verify.stdout"
 
 - name: verify the installed collection against the server, with unspecified version in CLI
-  command: ansible-galaxy collection verify ansible_test.verify -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify {{ galaxy_verbosity }}
 
 - name: verify a collection that doesn'"'"'t appear to be installed
-  command: ansible-galaxy collection verify ansible_test.verify:1.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:1.0.0 {{ galaxy_verbosity }}
   environment:
     ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}/nonexistent_dir'"'"'
   register: verify
@@ -90,13 +88,13 @@
   args:
     chdir: '"'"'{{ galaxy_dir }}'"'"'
 
-- name: publish the new version
+- name: publish to primary server {{ test_name }}
   command: ansible-galaxy collection publish ansible_test-verify-2.0.0.tar.gz -s {{ test_name }} {{ galaxy_verbosity }}
   args:
     chdir: '"'"'{{ galaxy_dir }}'"'"'
 
 - name: verify a version of a collection that isn'"'"'t installed
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
   failed_when: verify.rc == 0
 
@@ -106,10 +104,10 @@
       - '"'"'"ansible_test.verify has the version '"'"''"'"'1.0.0'"'"''"'"' but is being compared to '"'"''"'"'2.0.0'"'"''"'"'" in verify.stdout'"'"'
 
 - name: install the new version from the server
-  command: ansible-galaxy collection install ansible_test.verify:2.0.0 --force -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection install ansible_test.verify:2.0.0 --force {{ galaxy_verbosity }}
 
 - name: verify the installed collection against the server
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
 
 - assert:
@@ -153,7 +151,7 @@
       - "updated_file.stat.checksum != file.stat.checksum"
 
 - name: test verifying checksums of the modified collection
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
   failed_when: verify.rc == 0
 
@@ -171,7 +169,7 @@
   diff: true
 
 - name: ensure a modified FILES.json is validated
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
   failed_when: verify.rc == 0
 
@@ -193,7 +191,7 @@
     line: '"'"' "chksum_sha256": "{{ manifest_info.stat.checksum }}",'"'"'
 
 - name: ensure the MANIFEST.json is validated against the uncorrupted file from the server
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
   failed_when: verify.rc == 0
 
@@ -221,7 +219,7 @@
     dest: '"'"'{{ galaxy_dir }}/ansible_collections/ansible_test/verify/galaxy.yml'"'"'
 
 - name: test we only verify collections containing a MANIFEST.json with the version on the server
-  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 -s {{ test_name }} {{ galaxy_verbosity }}
+  command: ansible-galaxy collection verify ansible_test.verify:2.0.0 {{ galaxy_verbosity }}
   register: verify
   failed_when: verify.rc == 0
 
diff --git a/test/integration/targets/ansible-galaxy-collection/templates/ansible.cfg.j2 b/test/integration/targets/ansible-galaxy-collection/templates/ansible.cfg.j2
index a242979d227add..97dbbb34781837 100644
--- a/test/integration/targets/ansible-galaxy-collection/templates/ansible.cfg.j2
+++ b/test/integration/targets/ansible-galaxy-collection/templates/ansible.cfg.j2
@@ -1,17 +1,11 @@
 [galaxy]
 # Ensures subsequent unstable reruns don'"'"'t use the cached information causing another failure
 cache_dir={{ remote_tmp_dir }}/galaxy_cache
-server_list=offline,galaxy_ng,secondary,pulp_v2
+server_list=offline,galaxy_ng,secondary
 
 [galaxy_server.offline]
 url={{ offline_server }}
 
-[galaxy_server.pulp_v2]
-url={{ pulp_server }}primary/api/
-username={{ pulp_user }}
-password={{ pulp_password }}
-api_version=2
-
 [galaxy_server.galaxy_ng]
 url={{ galaxy_ng_server }}content/primary/
 token={{ galaxy_ng_token.json.token }}
diff --git a/test/sanity/ignore.txt b/test/sanity/ignore.txt
index 37902613d09422..2cff1a050b48e5 100644
--- a/test/sanity/ignore.txt
+++ b/test/sanity/ignore.txt
@@ -229,4 +229,3 @@ test/integration/targets/ansible-test-sanity-pylint/deprecated_thing.py pylint:a
 test/integration/targets/ansible-test-sanity-pylint/deprecated_thing.py pylint:ansible-deprecated-date-not-permitted  # required to verify plugin against core
 test/integration/targets/ansible-test-sanity-pylint/deprecated_thing.py pylint:ansible-deprecated-unnecessary-collection-name  # required to verify plugin against core
 test/integration/targets/ansible-test-sanity-pylint/deprecated_thing.py pylint:ansible-deprecated-collection-name-not-permitted  # required to verify plugin against core
-lib/ansible/galaxy/api.py pylint:ansible-deprecated-version  # TODO: 2.20
diff --git a/test/units/galaxy/test_api.py b/test/units/galaxy/test_api.py
index 58985f1bb0eb3d..58bda34f713cd2 100644
--- a/test/units/galaxy/test_api.py
+++ b/test/units/galaxy/test_api.py
@@ -126,37 +126,32 @@ def get_v3_collection_versions(namespace='"'"'namespace'"'"', name='"'"'collection'"'"'):
 
 
 def get_collection_versions(namespace='"'"'namespace'"'"', name='"'"'collection'"'"'):
-    base_url = '"'"'https://galaxy.server.com/api/v2/collections/{0}/{1}/'"'"'.format(namespace, name)
-    versions_url = base_url + '"'"'versions/'"'"'
+    base_url = f'"'"'/api/v3/plugin/ansible/content/published/collections/index/{namespace}/{name}/'"'"'
+    versions_url = f'"'"'{base_url}versions/'"'"'
 
     # Response for collection info
     responses = [
         {
-            "id": 1000,
             "href": base_url,
             "name": name,
-            "namespace": {
-                "id": 30000,
-                "href": "https://galaxy.ansible.com/api/v1/namespaces/30000/",
-                "name": namespace,
-            },
-            "versions_url": versions_url,
-            "latest_version": {
+            "namespace": namespace,
+            "highest_version": {
+                "href": f"{versions_url}1.0.5",
                 "version": "1.0.5",
-                "href": versions_url + "1.0.5/"
             },
+            "versions_url": versions_url,
             "deprecated": False,
-            "created": "2021-02-09T16:55:42.749915-05:00",
-            "modified": "2021-02-09T16:55:42.749915-05:00",
+            "created_at": "2021-02-09T16:55:42.749915-05:00",
+            "updated_at": "2021-02-09T16:55:42.749915-05:00",
         }
     ]
 
     # Paginated responses for versions
     page_versions = (('"'"'1.0.0'"'"', '"'"'1.0.1'"'"',), ('"'"'1.0.2'"'"', '"'"'1.0.3'"'"',), ('"'"'1.0.4'"'"', '"'"'1.0.5'"'"'),)
-    last_page = None
+    prev_page = None
     for page in range(1, len(page_versions) + 1):
         if page < len(page_versions):
-            next_page = versions_url + '"'"'?page={0}'"'"'.format(page + 1)
+            next_page = f'"'"'{versions_url}?limit=2&offset={page + 1}'"'"'
         else:
             next_page = None
 
@@ -168,13 +163,19 @@ def get_collection_versions(namespace='"'"'namespace'"'"', name='"'"'collection'"'"'):
 
         responses.append(
             {
-                '"'"'count'"'"': 6,
-                '"'"'next'"'"': next_page,
-                '"'"'previous'"'"': last_page,
-                '"'"'results'"'"': version_results,
+                '"'"'meta'"'"': {
+                    '"'"'count'"'"': 6,
+                },
+                '"'"'links'"'"': {
+                    '"'"'first'"'"': f'"'"'{versions_url}?limit=2&offset=0'"'"',
+                    '"'"'next'"'"': next_page,
+                    '"'"'previous'"'"': prev_page,
+                    '"'"'last'"'"': f'"'"'{versions_url}?limit=2&offset={len(page_versions)}'"'"',
+                },
+                '"'"'data'"'"': version_results,
             }
         )
-        last_page = page
+        prev_page = page
 
     return responses
 
@@ -265,9 +266,8 @@ def test_initialise_galaxy(monkeypatch):
     api = GalaxyAPI(None, "test", "https://galaxy.ansible.com/api/")
     actual = api.authenticate("github_token")
 
-    assert len(api.available_api_versions) == 2
+    assert len(api.available_api_versions) == 1
     assert api.available_api_versions['"'"'v1'"'"'] == u'"'"'v1/'"'"'
-    assert api.available_api_versions['"'"'v2'"'"'] == u'"'"'v2/'"'"'
     assert actual == {u'"'"'token'"'"': u'"'"'my token'"'"'}
     assert mock_open.call_count == 2
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.ansible.com/api/'"'"'
@@ -288,9 +288,8 @@ def test_initialise_galaxy_with_auth(monkeypatch):
     api = GalaxyAPI(None, "test", "https://galaxy.ansible.com/api/", token=GalaxyToken(token='"'"'my_token'"'"'))
     actual = api.authenticate("github_token")
 
-    assert len(api.available_api_versions) == 2
+    assert len(api.available_api_versions) == 1
     assert api.available_api_versions['"'"'v1'"'"'] == u'"'"'v1/'"'"'
-    assert api.available_api_versions['"'"'v2'"'"'] == u'"'"'v2/'"'"'
     assert actual == {u'"'"'token'"'"': u'"'"'my token'"'"'}
     assert mock_open.call_count == 2
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.ansible.com/api/'"'"'
@@ -303,7 +302,7 @@ def test_initialise_galaxy_with_auth(monkeypatch):
 def test_initialise_automation_hub(monkeypatch):
     mock_open = MagicMock()
     mock_open.side_effect = [
-        StringIO(u'"'"'{"available_versions":{"v2": "v2/", "v3":"v3/"}}'"'"'),
+        StringIO(u'"'"'{"available_versions":{"v3":"v3/"}}'"'"'),
     ]
     monkeypatch.setattr(galaxy_api, '"'"'open_url'"'"', mock_open)
     token = KeycloakToken(auth_url='"'"'https://api.test/'"'"')
@@ -313,8 +312,7 @@ def test_initialise_automation_hub(monkeypatch):
 
     api = GalaxyAPI(None, "test", "https://galaxy.ansible.com/api/", token=token)
 
-    assert len(api.available_api_versions) == 2
-    assert api.available_api_versions['"'"'v2'"'"'] == u'"'"'v2/'"'"'
+    assert len(api.available_api_versions) == 1
     assert api.available_api_versions['"'"'v3'"'"'] == u'"'"'v3/'"'"'
 
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.ansible.com/api/'"'"'
@@ -341,7 +339,7 @@ def test_initialise_unknown(monkeypatch):
 def test_get_available_api_versions(monkeypatch):
     mock_open = MagicMock()
     mock_open.side_effect = [
-        StringIO(u'"'"'{"available_versions":{"v1":"v1/","v2":"v2/"}}'"'"'),
+        StringIO(u'"'"'{"available_versions":{"v1":"v1/","v3":"v3/"}}'"'"'),
     ]
     monkeypatch.setattr(galaxy_api, '"'"'open_url'"'"', mock_open)
 
@@ -349,7 +347,7 @@ def test_get_available_api_versions(monkeypatch):
     actual = api.available_api_versions
     assert len(actual) == 2
     assert actual['"'"'v1'"'"'] == u'"'"'v1/'"'"'
-    assert actual['"'"'v2'"'"'] == u'"'"'v2/'"'"'
+    assert actual['"'"'v3'"'"'] == u'"'"'v3/'"'"'
 
     assert mock_open.call_count == 1
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.ansible.com/api/'"'"'
@@ -360,7 +358,7 @@ def test_publish_collection_missing_file():
     fake_path = u'"'"'/fake/ÅÑŚÌβŁÈ/path'"'"'
     expected = to_native("The collection path specified '"'"'%s'"'"' does not exist." % fake_path)
 
-    api = get_test_galaxy_api("https://galaxy.ansible.com/api/", "v2")
+    api = get_test_galaxy_api("https://galaxy.ansible.com/api/", "v3")
     with pytest.raises(AnsibleError, match=expected):
         api.publish_collection(fake_path)
 
@@ -369,7 +367,7 @@ def test_publish_collection_not_a_tarball():
     expected = "The collection path specified '"'"'{0}'"'"' is not a tarball, use '"'"'ansible-galaxy collection build'"'"' to " \
                "create a proper release artifact."
 
-    api = get_test_galaxy_api("https://galaxy.ansible.com/api/", "v2")
+    api = get_test_galaxy_api("https://galaxy.ansible.com/api/", "v3")
     with tempfile.NamedTemporaryFile(prefix=u'"'"'ÅÑŚÌβŁÈ'"'"') as temp_file:
         temp_file.write(b"\x00")
         temp_file.flush()
@@ -378,7 +376,7 @@ def test_publish_collection_not_a_tarball():
 
 
 def test_publish_collection_unsupported_version():
-    expected = "Galaxy action publish_collection requires API versions '"'"'v2, v3'"'"' but only '"'"'v1'"'"' are available on test " \
+    expected = "Galaxy action publish_collection requires API versions '"'"'v3'"'"' but only '"'"'v1'"'"' are available on test " \
                "https://galaxy.ansible.com/api/"
 
     api = get_test_galaxy_api("https://galaxy.ansible.com/api/", "v1")
@@ -387,7 +385,6 @@ def test_publish_collection_unsupported_version():
 
 
 @pytest.mark.parametrize('"'"'api_version, collection_url'"'"', [
-    ('"'"'v2'"'"', '"'"'collections'"'"'),
     ('"'"'v3'"'"', '"'"'artifacts/collections'"'"'),
 ])
 def test_publish_collection(api_version, collection_url, collection_artifact, monkeypatch):
@@ -410,12 +407,6 @@ def test_publish_collection(api_version, collection_url, collection_artifact, mo
 
 
 @pytest.mark.parametrize('"'"'api_version, collection_url, response, expected'"'"', [
-    ('"'"'v2'"'"', '"'"'collections'"'"', {},
-     '"'"'Error when publishing collection to test (%s) (HTTP Code: 500, Message: msg Code: Unknown)'"'"'),
-    ('"'"'v2'"'"', '"'"'collections'"'"', {
-        '"'"'message'"'"': u'"'"'Galaxy error messäge'"'"',
-        '"'"'code'"'"': '"'"'GWE002'"'"',
-    }, u'"'"'Error when publishing collection to test (%s) (HTTP Code: 500, Message: Galaxy error messäge Code: GWE002)'"'"'),
     ('"'"'v3'"'"', '"'"'artifact/collections'"'"', {},
      '"'"'Error when publishing collection to test (%s) (HTTP Code: 500, Message: msg Code: Unknown)'"'"'),
     ('"'"'v3'"'"', '"'"'artifact/collections'"'"', {
@@ -452,8 +443,6 @@ def test_publish_failure(api_version, collection_url, response, expected, collec
 
 
 @pytest.mark.parametrize('"'"'server_url, api_version, token_type, token_ins, full_import_uri'"'"', [
-    ('"'"'https://galaxy.server.com/api'"'"', '"'"'v2'"'"', '"'"'Token'"'"', GalaxyToken('"'"'my token'"'"'),
-     '"'"'https://galaxy.server.com/api/v2/collection-imports/1234/'"'"'),
     ('"'"'https://galaxy.server.com/api/automation-hub/'"'"', '"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'),
      '"'"'https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/'"'"'),
 ])
@@ -482,8 +471,6 @@ def test_wait_import_task(server_url, api_version, token_type, token_ins, full_i
 
 
 @pytest.mark.parametrize('"'"'server_url, api_version, token_type, token_ins, full_import_uri'"'"', [
-    ('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', '"'"'Token'"'"', GalaxyToken('"'"'my token'"'"'),
-     '"'"'https://galaxy.server.com/api/v2/collection-imports/1234/'"'"'),
     ('"'"'https://galaxy.server.com/api/automation-hub'"'"', '"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'),
      '"'"'https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/'"'"'),
 ])
@@ -526,8 +513,6 @@ def test_wait_import_task_multiple_requests(server_url, api_version, token_type,
 
 
 @pytest.mark.parametrize('"'"'server_url, api_version, token_type, token_ins, full_import_uri,'"'"', [
-    ('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', '"'"'Token'"'"', GalaxyToken('"'"'my token'"'"'),
-     '"'"'https://galaxy.server.com/api/v2/collection-imports/1234/'"'"'),
     ('"'"'https://galaxy.server.com/api/automation-hub/'"'"', '"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'),
      '"'"'https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/'"'"'),
 ])
@@ -600,8 +585,6 @@ def test_wait_import_task_with_failure(server_url, api_version, token_type, toke
 
 
 @pytest.mark.parametrize('"'"'server_url, api_version, token_type, token_ins, full_import_uri'"'"', [
-    ('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', '"'"'Token'"'"', GalaxyToken('"'"'my_token'"'"'),
-     '"'"'https://galaxy.server.com/api/v2/collection-imports/1234/'"'"'),
     ('"'"'https://galaxy.server.com/api/automation-hub/'"'"', '"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'),
      '"'"'https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/'"'"'),
 ])
@@ -670,8 +653,6 @@ def test_wait_import_task_with_failure_no_error(server_url, api_version, token_t
 
 
 @pytest.mark.parametrize('"'"'server_url, api_version, token_type, token_ins, full_import_uri'"'"', [
-    ('"'"'https://galaxy.server.com/api'"'"', '"'"'v2'"'"', '"'"'Token'"'"', GalaxyToken('"'"'my token'"'"'),
-     '"'"'https://galaxy.server.com/api/v2/collection-imports/1234/'"'"'),
     ('"'"'https://galaxy.server.com/api/automation-hub'"'"', '"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'),
      '"'"'https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/'"'"'),
 ])
@@ -725,7 +706,6 @@ def return_response(*args, **kwargs):
 
 
 @pytest.mark.parametrize('"'"'api_version, token_type, version, token_ins'"'"', [
-    ('"'"'v2'"'"', None, '"'"'v2.1.13'"'"', None),
     ('"'"'v3'"'"', '"'"'Bearer'"'"', '"'"'v1.0.0'"'"', KeycloakToken(auth_url='"'"'https://api.test/api/automation-hub/'"'"')),
 ])
 def test_get_collection_version_metadata_no_version(api_version, token_type, version, token_ins, monkeypatch):
@@ -777,11 +757,11 @@ def test_get_collection_version_metadata_no_version(api_version, token_type, ver
         assert mock_open.mock_calls[0][2]['"'"'headers'"'"']['"'"'Authorization'"'"'] == '"'"'%s my token'"'"' % token_type
 
 
-@pytest.mark.parametrize('"'"'api_version, token_type, token_ins, version'"'"', [
-    ('"'"'v2'"'"', None, None, '"'"'2.1.13'"'"'),
-    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/api/automation-hub/'"'"'), '"'"'1.0.0'"'"'),
+@pytest.mark.parametrize('"'"'api_version, token_type, token_ins'"'"', [
+    ('"'"'v3'"'"', None, None),
+    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/api/automation-hub/'"'"')),
 ])
-def test_get_collection_signatures_backwards_compat(api_version, token_type, token_ins, version, monkeypatch):
+def test_get_collection_signatures_backwards_compat(api_version, token_type, token_ins, monkeypatch):
     api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', api_version, token_ins=token_ins)
 
     if token_ins:
@@ -795,23 +775,23 @@ def test_get_collection_signatures_backwards_compat(api_version, token_type, tok
     ]
     monkeypatch.setattr(galaxy_api, '"'"'open_url'"'"', mock_open)
 
-    actual = api.get_collection_signatures('"'"'namespace'"'"', '"'"'collection'"'"', version)
+    actual = api.get_collection_signatures('"'"'namespace'"'"', '"'"'collection'"'"', '"'"'1.0.0'"'"')
     assert actual == []
 
     assert mock_open.call_count == 1
-    assert mock_open.mock_calls[0][1][0] == '"'"'%s%s/collections/namespace/collection/versions/%s/'"'"' \
-        % (api.api_server, api_version, version)
+    assert mock_open.mock_calls[0][1][0] == '"'"'%s%s/collections/namespace/collection/versions/1.0.0/'"'"' \
+        % (api.api_server, api_version)
 
-    # v2 calls dont need auth, so no authz header or token_type
+    # v3 calls dont need auth, so no authz header or token_type
     if token_type:
         assert mock_open.mock_calls[0][2]['"'"'headers'"'"']['"'"'Authorization'"'"'] == '"'"'%s my token'"'"' % token_type
 
 
-@pytest.mark.parametrize('"'"'api_version, token_type, token_ins, version'"'"', [
-    ('"'"'v2'"'"', None, None, '"'"'2.1.13'"'"'),
-    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/api/automation-hub/'"'"'), '"'"'1.0.0'"'"'),
+@pytest.mark.parametrize('"'"'api_version, token_type, token_ins'"'"', [
+    ('"'"'v3'"'"', None, None),
+    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/api/automation-hub/'"'"')),
 ])
-def test_get_collection_signatures(api_version, token_type, token_ins, version, monkeypatch):
+def test_get_collection_signatures(api_version, token_type, token_ins, monkeypatch):
     api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', api_version, token_ins=token_ins)
 
     if token_ins:
@@ -840,7 +820,7 @@ def test_get_collection_signatures(api_version, token_type, token_ins, version,
     ]
     monkeypatch.setattr(galaxy_api, '"'"'open_url'"'"', mock_open)
 
-    actual = api.get_collection_signatures('"'"'namespace'"'"', '"'"'collection'"'"', version)
+    actual = api.get_collection_signatures('"'"'namespace'"'"', '"'"'collection'"'"', '"'"'1.0.0'"'"')
 
     assert actual == [
         "-----BEGIN PGP SIGNATURE-----\nSIGNATURE1\n-----END PGP SIGNATURE-----\n",
@@ -848,48 +828,41 @@ def test_get_collection_signatures(api_version, token_type, token_ins, version,
     ]
 
     assert mock_open.call_count == 1
-    assert mock_open.mock_calls[0][1][0] == '"'"'%s%s/collections/namespace/collection/versions/%s/'"'"' \
-        % (api.api_server, api_version, version)
+    assert mock_open.mock_calls[0][1][0] == '"'"'%s%s/collections/namespace/collection/versions/1.0.0/'"'"' \
+        % (api.api_server, api_version)
 
-    # v2 calls dont need auth, so no authz header or token_type
+    # v3 calls dont need auth, so no authz header or token_type
     if token_type:
         assert mock_open.mock_calls[0][2]['"'"'headers'"'"']['"'"'Authorization'"'"'] == '"'"'%s my token'"'"' % token_type
 
 
-@pytest.mark.parametrize('"'"'api_version, token_type, token_ins, response'"'"', [
-    ('"'"'v2'"'"', None, None, {
-        '"'"'count'"'"': 2,
-        '"'"'next'"'"': None,
-        '"'"'previous'"'"': None,
-        '"'"'results'"'"': [
-            {
-                '"'"'version'"'"': '"'"'1.0.0'"'"',
-                '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.0'"'"',
-            },
-            {
-                '"'"'version'"'"': '"'"'1.0.1'"'"',
-                '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.1'"'"',
-            },
-        ],
-    }),
-    # TODO: Verify this once Automation Hub is actually out
-    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'), {
-        '"'"'count'"'"': 2,
-        '"'"'next'"'"': None,
-        '"'"'previous'"'"': None,
+@pytest.mark.parametrize('"'"'api_version, token_type, token_ins'"'"', [
+    ('"'"'v3'"'"', None, None),
+    ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://ah.test/'"'"'))
+])
+def test_get_collection_versions(api_version, token_type, token_ins, monkeypatch):
+    response = {
+        '"'"'meta'"'"': {
+            '"'"'count'"'"': 2
+        },
+        '"'"'links'"'"': {
+            '"'"'first'"'"': '"'"'/api/v3/plugin/ansible/content/published/collections/index/ns/col/versions/?limit=100&offset=0'"'"',
+            '"'"'previous'"'"': None,
+            '"'"'next'"'"': None,
+            '"'"'last'"'"': '"'"'/api/v3/plugin/ansible/content/published/collections/index/ns/col/versions/?limit=100&offset=0'"'"'
+        },
         '"'"'data'"'"': [
             {
                 '"'"'version'"'"': '"'"'1.0.0'"'"',
-                '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.0'"'"',
+                '"'"'href'"'"': '"'"'/api/v3/plugin/ansible/content/published/collections/index/ns/col/versions/1.0.0/'"'"',
             },
             {
                 '"'"'version'"'"': '"'"'1.0.1'"'"',
-                '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.1'"'"',
+                '"'"'href'"'"': '"'"'/api/v3/plugin/ansible/content/pubished/collections/index/ns/col/versions/1.0.1/'"'"',
             },
         ],
-    }),
-])
-def test_get_collection_versions(api_version, token_type, token_ins, response, monkeypatch):
+    }
+
     api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', api_version, token_ins=token_ins)
 
     if token_ins:
@@ -906,7 +879,7 @@ def test_get_collection_versions(api_version, token_type, token_ins, response, m
     actual = api.get_collection_versions('"'"'namespace'"'"', '"'"'collection'"'"')
     assert actual == [u'"'"'1.0.0'"'"', u'"'"'1.0.1'"'"']
 
-    page_query = '"'"'?limit=100'"'"' if api_version == '"'"'v3'"'"' else '"'"'?page_size=100'"'"'
+    page_query = '"'"'?limit=100'"'"'
     assert mock_open.call_count == 1
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.server.com/api/%s/collections/namespace/collection/'"'"' \
                                             '"'"'versions/%s'"'"' % (api_version, page_query)
@@ -915,53 +888,6 @@ def test_get_collection_versions(api_version, token_type, token_ins, response, m
 
 
 @pytest.mark.parametrize('"'"'api_version, token_type, token_ins, responses'"'"', [
-    ('"'"'v2'"'"', None, None, [
-        {
-            '"'"'count'"'"': 6,
-            '"'"'next'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/?page=2&page_size=100'"'"',
-            '"'"'previous'"'"': None,
-            '"'"'results'"'"': [  # Pay no mind, using more manageable results than page_size would indicate
-                {
-                    '"'"'version'"'"': '"'"'1.0.0'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.0'"'"',
-                },
-                {
-                    '"'"'version'"'"': '"'"'1.0.1'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.1'"'"',
-                },
-            ],
-        },
-        {
-            '"'"'count'"'"': 6,
-            '"'"'next'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/?page=3&page_size=100'"'"',
-            '"'"'previous'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions'"'"',
-            '"'"'results'"'"': [
-                {
-                    '"'"'version'"'"': '"'"'1.0.2'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.2'"'"',
-                },
-                {
-                    '"'"'version'"'"': '"'"'1.0.3'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.3'"'"',
-                },
-            ],
-        },
-        {
-            '"'"'count'"'"': 6,
-            '"'"'next'"'"': None,
-            '"'"'previous'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/?page=2&page_size=100'"'"',
-            '"'"'results'"'"': [
-                {
-                    '"'"'version'"'"': '"'"'1.0.4'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.4'"'"',
-                },
-                {
-                    '"'"'version'"'"': '"'"'1.0.5'"'"',
-                    '"'"'href'"'"': '"'"'https://galaxy.server.com/api/v2/collections/namespace/collection/versions/1.0.5'"'"',
-                },
-            ],
-        },
-    ]),
     ('"'"'v3'"'"', '"'"'Bearer'"'"', KeycloakToken(auth_url='"'"'https://api.test/'"'"'), [
         {
             '"'"'count'"'"': 6,
@@ -1034,14 +960,9 @@ def test_get_collection_versions_pagination(api_version, token_type, token_ins,
 
     assert mock_open.call_count == 3
 
-    if api_version == '"'"'v3'"'"':
-        query_1 = '"'"'limit=100'"'"'
-        query_2 = '"'"'limit=100&offset=100'"'"'
-        query_3 = '"'"'limit=100&offset=200'"'"'
-    else:
-        query_1 = '"'"'page_size=100'"'"'
-        query_2 = '"'"'page=2&page_size=100'"'"'
-        query_3 = '"'"'page=3&page_size=100'"'"'
+    query_1 = '"'"'limit=100'"'"'
+    query_2 = '"'"'limit=100&offset=100'"'"'
+    query_3 = '"'"'limit=100&offset=200'"'"'
 
     assert mock_open.mock_calls[0][1][0] == '"'"'https://galaxy.server.com/api/%s/collections/namespace/collection/'"'"' \
                                             '"'"'versions/?%s'"'"' % (api_version, query_1)
@@ -1160,7 +1081,7 @@ def test_cache_complete_pagination(cache_dir, monkeypatch):
     responses = get_collection_versions()
     cache_file = os.path.join(cache_dir, '"'"'api.json'"'"')
 
-    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', no_cache=False)
+    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v3'"'"', no_cache=False)
 
     mock_open = MagicMock(
         side_effect=[
@@ -1177,7 +1098,7 @@ def test_cache_complete_pagination(cache_dir, monkeypatch):
         final_cache = json.loads(fd.read())
 
     cached_server = final_cache['"'"'galaxy.server.com:'"'"']
-    cached_collection = cached_server['"'"'/api/v2/collections/namespace/collection/versions/'"'"']
+    cached_collection = cached_server['"'"'/api/v3/collections/namespace/collection/versions/'"'"']
     cached_versions = [r['"'"'version'"'"'] for r in cached_collection['"'"'results'"'"']]
 
     assert final_cache == api._cache
@@ -1218,14 +1139,14 @@ def test_cache_flaky_pagination(cache_dir, monkeypatch):
     responses = get_collection_versions()
     cache_file = os.path.join(cache_dir, '"'"'api.json'"'"')
 
-    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', no_cache=False)
+    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v3'"'"', no_cache=False)
 
     # First attempt, fail midway through
     mock_open = MagicMock(
         side_effect=[
             StringIO(to_text(json.dumps(responses[0]))),
             StringIO(to_text(json.dumps(responses[1]))),
-            urllib.error.HTTPError(responses[1]['"'"'next'"'"'], 500, '"'"'Error'"'"', {}, StringIO()),
+            urllib.error.HTTPError(responses[1]['"'"'links'"'"']['"'"'next'"'"'], 500, '"'"'Error'"'"', {}, StringIO()),
             StringIO(to_text(json.dumps(responses[3]))),
         ]
     )
@@ -1246,13 +1167,13 @@ def test_cache_flaky_pagination(cache_dir, monkeypatch):
         '"'"'version'"'"': 1,
         '"'"'galaxy.server.com:'"'"': {
             '"'"'modified'"'"': {
-                '"'"'namespace.collection'"'"': responses[0]['"'"'modified'"'"']
+                '"'"'namespace.collection'"'"': responses[0]['"'"'updated_at'"'"']
             }
         }
     }
 
     # Reset API
-    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v2'"'"', no_cache=False)
+    api = get_test_galaxy_api('"'"'https://galaxy.server.com/api/'"'"', '"'"'v3'"'"', no_cache=False)
 
     # Second attempt is successful so cache should be populated
     mock_open = MagicMock(
@@ -1270,7 +1191,7 @@ def test_cache_flaky_pagination(cache_dir, monkeypatch):
         final_cache = json.loads(fd.read())
 
     cached_server = final_cache['"'"'galaxy.server.com:'"'"']
-    cached_collection = cached_server['"'"'/api/v2/collections/namespace/collection/versions/'"'"']
+    cached_collection = cached_server['"'"'/api/v3/collections/namespace/collection/versions/'"'"']
     cached_versions = [r['"'"'version'"'"'] for r in cached_collection['"'"'results'"'"']]
 
     assert cached_versions == actual_versions
diff --git a/test/units/galaxy/test_collection.py b/test/units/galaxy/test_collection.py
index 7115a1da44f488..8da860da28485f 100644
--- a/test/units/galaxy/test_collection.py
+++ b/test/units/galaxy/test_collection.py
@@ -846,7 +846,7 @@ def test_publish_no_wait(galaxy_server, collection_artifact, monkeypatch):
     monkeypatch.setattr(Display, '"'"'display'"'"', mock_display)
 
     artifact_path, mock_open = collection_artifact
-    fake_import_uri = '"'"'https://galaxy.server.com/api/v2/import/1234'"'"'
+    fake_import_uri = '"'"'https://galaxy.server.com/api/v3/import/1234'"'"'
 
     mock_publish = MagicMock()
     mock_publish.return_value = fake_import_uri
@@ -869,7 +869,7 @@ def test_publish_with_wait(galaxy_server, collection_artifact, monkeypatch):
     monkeypatch.setattr(Display, '"'"'display'"'"', mock_display)
 
     artifact_path, mock_open = collection_artifact
-    fake_import_uri = '"'"'https://galaxy.server.com/api/v2/import/1234'"'"'
+    fake_import_uri = '"'"'https://galaxy.server.com/api/v3/import/1234'"'"'
 
     mock_publish = MagicMock()
     mock_publish.return_value = fake_import_uri
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/ansible-config/tasks/main.yml test/integration/targets/ansible-galaxy-collection/tasks/install.yml test/integration/targets/ansible-galaxy-collection/tasks/main.yml test/integration/targets/ansible-galaxy-collection/tasks/verify.yml test/integration/targets/ansible-galaxy-collection/templates/ansible.cfg.j2 test/sanity/ignore.txt test/units/galaxy/test_api.py test/units/galaxy/test_collection.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/galaxy/test_api.py::test_initialise_galaxy", "test/units/galaxy/test_api.py::test_initialise_galaxy_with_auth", "test/units/galaxy/test_api.py::test_publish_collection_unsupported_version", "test/units/galaxy/test_api.py::test_wait_import_task[https://galaxy.server.com/api/automation-hub/-v3-Bearer-token_ins0-https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/]", "test/units/galaxy/test_api.py::test_wait_import_task_multiple_requests[https://galaxy.server.com/api/automation-hub-v3-Bearer-token_ins0-https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/]", "test/units/galaxy/test_api.py::test_wait_import_task_with_failure[https://galaxy.server.com/api/automation-hub/-v3-Bearer-token_ins0-https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/]", "test/units/galaxy/test_api.py::test_wait_import_task_with_failure_no_error[https://galaxy.server.com/api/automation-hub/-v3-Bearer-token_ins0-https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/]", "test/units/galaxy/test_api.py::test_wait_import_task_timeout[https://galaxy.server.com/api/automation-hub-v3-Bearer-token_ins0-https://galaxy.server.com/api/automation-hub/v3/imports/collections/1234/]", "test/units/galaxy/test_collection.py::test_publish_with_wait"]

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
