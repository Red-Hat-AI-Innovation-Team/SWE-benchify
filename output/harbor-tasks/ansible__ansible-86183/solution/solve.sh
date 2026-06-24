#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/install-ansible-core-compatible-collections.yml b/changelogs/fragments/install-ansible-core-compatible-collections.yml
new file mode 100644
index 00000000000000..4e24005d415f53
--- /dev/null
+++ b/changelogs/fragments/install-ansible-core-compatible-collections.yml
@@ -0,0 +1,6 @@
+bugfixes:
+- >-
+  ``ansible-galaxy install`` and ``ansible-galaxy collection install|download`` - now consider
+  the ``COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH`` configuration.
+  Collections which will cause a warning/error at load time are no longer installed/downloaded.
+  (https://github.com/ansible/ansible/issues/78539)
diff --git a/lib/ansible/galaxy/api.py b/lib/ansible/galaxy/api.py
index e145687b70f3b9..3a08dbcedd9b08 100644
--- a/lib/ansible/galaxy/api.py
+++ b/lib/ansible/galaxy/api.py
@@ -288,6 +288,8 @@ def __init__(
         if not no_cache:
             self._cache = _load_cache(self._b_cache_path)
 
+        self.requires_ansible = collections.defaultdict(dict)
+
         display.debug('Validate TLS certificates for %s: %s' % (self.api_server, self.validate_certs))
 
     def __str__(self):
@@ -780,6 +782,11 @@ def get_collection_version_metadata(self, namespace, name, version):
 
         signatures = data.get('signatures') or []
 
+        # NOTE: Galaxy and Hub already populated the cache when listing versions.
+        # NOTE: Allow 3rd party servers to provide version-specific metadata lazily.
+        if (requires_ansible := data.get('requires_ansible')):
+            self.requires_ansible[f"{namespace}.{name}"][version] = requires_ansible
+
         download_url_info = urlparse(data['download_url'])
         if not download_url_info.scheme and not download_url_info.path.startswith('/'):
             # galaxy does a lot of redirects, with much more complex pathing than we use
@@ -852,7 +859,10 @@ def get_collection_versions(self, namespace, name):
 
         versions = []
         while True:
-            versions += [v['version'] for v in data[results_key]]
+            for v in data[results_key]:
+                versions.append(v["version"])
+                # requires_ansible is new in galaxy_ng 4.3.0
+                self.requires_ansible[f"{namespace}.{name}"][v["version"]] = v.get("requires_ansible")
 
             next_link = data
             for path in pagination_path:
diff --git a/lib/ansible/galaxy/collection/__init__.py b/lib/ansible/galaxy/collection/__init__.py
index 5656227e7e18cc..f1628fcd8935e7 100644
--- a/lib/ansible/galaxy/collection/__init__.py
+++ b/lib/ansible/galaxy/collection/__init__.py
@@ -550,6 +550,8 @@ def download_collections(
             format(path=output_path),
     ):
         for fqcn, concrete_coll_pin in dep_map.copy().items():  # FIXME: move into the provider
+            if concrete_coll_pin.type == "requires_ansible":
+                continue
             if concrete_coll_pin.is_virtual:
                 display.display(
                     '{coll!s} is not downloadable'.
@@ -734,6 +736,8 @@ def install_collections(
     keyring_exists = artifacts_manager.keyring is not None
     with _display_progress("Starting collection install process"):
         for fqcn, concrete_coll_pin in dependency_map.items():
+            if concrete_coll_pin.type == "requires_ansible":
+                continue
             if concrete_coll_pin.is_virtual:
                 display.vvvv(
                     "Encountered {coll!s}, skipping.".
@@ -1827,6 +1831,10 @@ def _resolve_depenency_map(
         'installed by default unless a specific version is requested. '
         'To enable pre-releases globally, use --pre.'
     )
+    requires_ansible_hint = '' if C.COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH == 'ignore' else (
+        'Hint: To disregard whether the collection supports the current version of '
+        'ansible-core, configure COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH as "ignore".'
+    )
 
     collection_dep_resolver = build_collection_dependency_resolver(
         galaxy_apis=galaxy_apis,
@@ -1847,16 +1855,27 @@ def _resolve_depenency_map(
             ).mapping,
         )
     except CollectionDependencyResolutionImpossible as dep_exc:
-        conflict_causes = (
-            '* {req.fqcn!s}:{req.ver!s} ({dep_origin!s})'.format(
-                req=req_inf.requirement,
-                dep_origin='direct request'
-                if req_inf.parent is None
-                else 'dependency of {parent!s}'.
-                format(parent=req_inf.parent),
-            )
-            for req_inf in dep_exc.causes
-        )
+        conflict_causes = []
+        for req_inf in dep_exc.causes:
+            if req_inf.requirement.type == "requires_ansible":
+                if req_inf.requirement.has_candidate:
+                    continue
+                collection = str(req_inf.parent)
+                parents = [str(r._parent) for r in req_inf.parent._requirements if r._parent is not None]
+                if not parents:
+                    dep_origin = 'direct request'
+                else:
+                    dep_origin = f'dependency of {", ".join(parents)}'
+            else:
+                collection = str(req_inf.requirement)
+                dep_origin = 'direct request' if req_inf.parent is None else f'dependency of {req_inf.parent!s}'
+
+            cause = f"* {collection} ({dep_origin})"
+            if req_inf.requirement.type == "requires_ansible":
+                cause += f" requires {req_inf.requirement.fqcn!s} {req_inf.requirement.ver!s}"
+
+            conflict_causes.append(cause)
+
         error_msg_lines = list(chain(
             (
                 'Failed to resolve the requested '
@@ -1865,6 +1884,9 @@ def _resolve_depenency_map(
             ),
             conflict_causes,
         ))
+        if any(req_inf.requirement.type == "requires_ansible" for req_inf in dep_exc.causes):
+            dep_exc = None
+            error_msg_lines.append(requires_ansible_hint)
         error_msg_lines.append(pre_release_hint)
         raise AnsibleError('\n'.join(error_msg_lines)) from dep_exc
     except CollectionDependencyInconsistentCandidate as dep_exc:
diff --git a/lib/ansible/galaxy/collection/concrete_artifact_manager.py b/lib/ansible/galaxy/collection/concrete_artifact_manager.py
index 1659bc46b49d27..9dcf3c7af03506 100644
--- a/lib/ansible/galaxy/collection/concrete_artifact_manager.py
+++ b/lib/ansible/galaxy/collection/concrete_artifact_manager.py
@@ -12,8 +12,11 @@
 import typing as t
 import yaml
 
-from contextlib import contextmanager
+from collections.abc import Mapping
+from contextlib import contextmanager, suppress
+from functools import cache
 from hashlib import sha256
+from pathlib import Path
 from urllib.error import URLError
 from urllib.parse import urldefrag
 from shutil import rmtree
@@ -338,6 +341,33 @@ def get_direct_collection_meta(self, collection):
         self._artifact_meta_cache[collection.src] = collection_meta
         return collection_meta
 
+    def get_direct_requires_ansible(self, collection: Candidate) -> str | None:
+        """Extract requires_ansible from the on-disk collection artifact."""
+        if collection.is_concrete_artifact:
+            b_artifact_path = self.get_artifact_path(collection)
+        else:
+            b_artifact_path = self.get_galaxy_artifact_path(collection)
+
+        if collection.is_url or collection.is_file or collection.is_online_index_pointer:
+            runtime = _get_runtime_from_tar(b_artifact_path) or {}
+        elif collection.is_dir:
+            runtime = _get_runtime_from_dir(b_artifact_path) or {}
+        elif collection.is_virtual:
+            runtime = {}
+
+        if not isinstance(runtime, Mapping):
+            raise AnsibleError(
+                f"The collection {collection} (type {collection.type}) (from {collection.src}) "
+                "has an invalid meta/runtime.yml metadata. This file must contain a YAML dictionary."
+            )
+        if "requires_ansible" in runtime and not isinstance(runtime["requires_ansible"], str):
+            raise AnsibleError(
+                f"The collection {collection} (type {collection.type}) from {collection.src}) "
+                "has invalid meta/runtime.yml metadata. The value for requires_ansible must be a string."
+            )
+        # NOTE: Using None as a sentinel since it's not a valid value otherwise.
+        return runtime.get("requires_ansible")
+
     def save_collection_source(self, collection, url, sha256_hash, token, signatures_url, signatures):
         # type: (Candidate, str, str, GalaxyToken, str, list[dict[str, str]]) -> None
         """Store collection URL, SHA256 hash and Galaxy API token.
@@ -756,3 +786,21 @@ def _tarfile_extract(
     finally:
         if tar_obj is not None:
             tar_obj.close()
+
+
+@cache
+def _get_runtime_from_dir(b_path: bytes) -> object:
+    """Load the meta/runtime.yml from a collection directory."""
+    runtime_path = Path(b_path.decode()) / "meta" / "runtime.yml"
+    with suppress(OSError):
+        return yaml_load(runtime_path.read_text())
+
+
+@cache
+def _get_runtime_from_tar(b_path: bytes) -> object:
+    """Load the meta/runtime.yml from a collection artifact."""
+    with suppress(tarfile.TarError, KeyError):
+        with tarfile.open(b_path, mode='r') as collection_tar:
+            runtime = collection_tar.getmember("meta/runtime.yml")
+            with _tarfile_extract(collection_tar, runtime) as (_member, member_obj):
+                return yaml_load(member_obj)
diff --git a/lib/ansible/galaxy/dependency_resolution/dataclasses.py b/lib/ansible/galaxy/dependency_resolution/dataclasses.py
index 389eef7122abd3..76489087aa63ec 100644
--- a/lib/ansible/galaxy/dependency_resolution/dataclasses.py
+++ b/lib/ansible/galaxy/dependency_resolution/dataclasses.py
@@ -26,11 +26,14 @@
         '_ComputedReqKindsMixin',
     )
 
+from ansible import constants as C
 from ansible.errors import AnsibleError, AnsibleAssertionError
 from ansible.galaxy.api import GalaxyAPI
 from ansible.galaxy.collection import HAS_PACKAGING, PkgReq
 from ansible.module_utils.common.text.converters import to_bytes, to_native, to_text
 from ansible.module_utils.common.arg_spec import ArgumentSpecValidator
+from ansible.plugins.loader import _does_collection_support_ansible_version
+from ansible.release import __version__
 from ansible.utils.collection_loader import AnsibleCollectionRef
 from ansible.utils.display import Display
 
@@ -543,7 +546,7 @@ def name(self) -> str:
 
     @property
     def canonical_package_id(self) -> str:
-        if not self.is_virtual:
+        if not self.is_virtual or self.type == "requires_ansible":
             return to_native(self.fqcn)
 
         return (
@@ -633,6 +636,13 @@ def __new__(cls, *args: object, **kwargs: object) -> t.Self:
 
     def __init__(self, *args: object, **kwargs: object) -> None:
         super(Requirement, self).__init__()
+        # NOTE: Hack to display the origin of impossible collection requirements when requires_ansible is incompatible
+        # e.g. Requirement ns.col -> ns.col:$ver -> Requirement ns.dep -> ns.dep:$ver -> Requirement ansible-core<2.19
+        #   - ResolutionImpossible.causes[0].requirement is Requirement ansible-core<2.19
+        #   - ResolutionImpossible.causes[0].parent is Candidate ns.dep:$ver
+        #   - ResolutionImpossible.causes[0].parent._requirements[0] is Requirement ns.dep
+        #   - ResolutionImpossible.causes[0].parent._requirements[0]._parent is Candidate ns.col:$ver
+        self._parent: Candidate | None = None
 
 
 class Candidate(
@@ -647,6 +657,8 @@ def __new__(cls, *args: object, **kwargs: object) -> t.Self:
 
     def __init__(self, *args: object, **kwargs: object) -> None:
         super(Candidate, self).__init__()
+        # NOTE: Hack to display the origin of impossible collection requirements when requires_ansible is incompatible
+        self._requirements: list[Requirement] = []
 
     def with_signatures_repopulated(self) -> Candidate:
         """Populate a new Candidate instance with Galaxy signatures.
@@ -657,3 +669,43 @@ def with_signatures_repopulated(self) -> Candidate:
 
         signatures = self.src.get_collection_signatures(self.namespace, self.name, self.ver)
         return self.__class__(self.fqcn, self.ver, self.src, self.type, frozenset([*self.signatures, *signatures]))
+
+
+class AnsibleRequirement(Requirement):
+    def __init__(self, *args: object, **kwargs: object) -> None:
+        super(AnsibleRequirement, self).__init__()
+
+        self.has_candidate: None | Candidate
+        if _does_collection_support_ansible_version(self.ver, __version__):
+            self.has_candidate = Candidate("ansible-core", __version__, None, "requires_ansible", None)
+        else:
+            self.has_candidate = None
+
+    @classmethod
+    def from_collection(cls, concrete_art_mgr: ConcreteArtifactsManager, candidate: Candidate) -> None | t.Self:
+        """
+        Create a Requirement from a collection Candidate's requires_ansible metadata.
+        """
+        if (
+            C.COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH == "ignore"
+            or candidate.is_virtual
+            or candidate.type == "requires_ansible"
+        ):
+            return None
+
+        if candidate.type == 'galaxy':
+            requires_ansible = (candidate.src.requires_ansible.get(candidate.fqcn) or {}).get(candidate.ver)
+        else:
+            requires_ansible = concrete_art_mgr.get_direct_requires_ansible(candidate)
+
+        if requires_ansible is None:
+            display.warning(f"{candidate!s} does not have requires_ansible metadata.")
+            return None
+
+        # Passing the "fqcn" attribute so __unicode__ doesn't need to be overridden.
+        res = cls("ansible-core", requires_ansible, None, "requires_ansible", None)
+        res._parent = candidate
+        return res
+
+    def is_satisfied_by(self, candidate: Candidate) -> bool:
+        return self.has_candidate == candidate
diff --git a/lib/ansible/galaxy/dependency_resolution/providers.py b/lib/ansible/galaxy/dependency_resolution/providers.py
index 8571c4bc91763b..20df84e29bee9c 100644
--- a/lib/ansible/galaxy/dependency_resolution/providers.py
+++ b/lib/ansible/galaxy/dependency_resolution/providers.py
@@ -22,6 +22,7 @@
 from ansible.galaxy.dependency_resolution.dataclasses import (
     Candidate,
     Requirement,
+    AnsibleRequirement,
 )
 from ansible.galaxy.dependency_resolution.versioning import (
     is_pre_release,
@@ -87,6 +88,10 @@ def __init__(
             Requirement.from_requirement_dict,
             art_mgr=concrete_artifacts_manager,
         )
+        self._make_ansible_requirement = functools.partial(
+            AnsibleRequirement.from_collection,
+            concrete_artifacts_manager,
+        )
         self._preferred_candidates = set(preferred_candidates or ())
         self._with_deps = with_deps
         self._with_pre_releases = with_pre_releases
@@ -188,10 +193,14 @@ def find_matches(
         to find concrete candidates for this requirement. If there's a
         pre-installed candidate, it's prepended in front of others.
         """
-        return [
-            match for match in self._find_matches(list(requirements[identifier]))
-            if not any(match.ver == incompat.ver for incompat in incompatibilities[identifier])
-        ]
+        results = []
+        for match in self._find_matches(list(requirements[identifier])):
+            if any(match.ver == incompat.ver for incompat in incompatibilities[identifier]):
+                continue
+
+            match._requirements = list(requirements[identifier])
+            results.append(match)
+        return results
 
     def _find_matches(self, requirements: list[Requirement]) -> list[Candidate]:
         # FIXME: The first requirement may be a Git repo followed by
@@ -204,6 +213,12 @@ def _find_matches(self, requirements: list[Requirement]) -> list[Candidate]:
         version_req = "A SemVer-compliant version or '*' is required. See https://semver.org to learn how to compose it correctly. "
         version_req += "This is an issue with the collection."
 
+        if first_req.type == "requires_ansible":
+            for r in requirements:
+                if r.has_candidate is None:
+                    return []
+            return [first_req.has_candidate]
+
         # If we're upgrading collections, we can't calculate preinstalled_candidates until the latest matches are found.
         # Otherwise, we can potentially avoid a Galaxy API call by doing this first.
         preinstalled_candidates = set()
@@ -390,17 +405,23 @@ def is_satisfied_by(
         ):
             return True
 
+        if requirement.type == 'requires_ansible':
+            return requirement.is_satisfied_by(candidate)
+
         return meets_requirements(
             version=candidate.ver,
             requirements=requirement.ver,
         )
 
-    def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
+    def get_dependencies(self, candidate: Candidate) -> t.Iterator[Requirement]:
         r"""Get direct dependencies of a candidate.
 
         :returns: A collection of requirements that `candidate` \
                   specifies as its dependencies.
         """
+        if candidate.type == "requires_ansible":
+            return
+
         # FIXME: If there's several galaxy servers set, there may be a
         # FIXME: situation when the metadata of the same collection
         # FIXME: differs. So how do we resolve this case? Priority?
@@ -409,6 +430,10 @@ def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
         # NOTE: The underlying implementation currently uses first found
         req_map = self._api_proxy.get_collection_dependencies(candidate)
 
+        if (requires_ansible := self._make_ansible_requirement(candidate)):
+            requires_ansible._parent = candidate
+            yield requires_ansible
+
         # NOTE: This guard expression MUST perform an early exit only
         # NOTE: after the `get_collection_dependencies()` call because
         # NOTE: internally it populates the artifact URL of the candidate,
@@ -419,10 +444,9 @@ def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
         #
         # NOTE: Virtual candidates should always return dependencies
         # NOTE: because they are ephemeral and non-installable.
-        if not self._with_deps and not candidate.is_virtual:
-            return []
-
-        return [
-            self._make_req_from_dict({'name': dep_name, 'version': dep_req})
-            for dep_name, dep_req in req_map.items()
-        ]
+        for dep_name, dep_req in req_map.items():
+            if not (self._with_deps or candidate.is_virtual):
+                continue
+            dependency = self._make_req_from_dict({'name': dep_name, 'version': dep_req})
+            dependency._parent = candidate
+            yield dependency
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
