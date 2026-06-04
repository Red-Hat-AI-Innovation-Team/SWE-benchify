"""Tests for GoEnvironmentSpec, compute_env_spec_hash, and GoSpecRegistry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebenchify.go_registry import GoSpecRegistry, get_go_environment_setup_commit
from swebenchify.models import GoEnvironmentSpec, compute_env_spec_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(**overrides) -> GoEnvironmentSpec:
    defaults = dict(
        language="go",
        go_version="1.22",
        build_cmd="make build",
        test_cmd="go test ./pkg/...",
        module_mode="modules",
        goflags="",
        system_dependencies=[],
    )
    defaults.update(overrides)
    return GoEnvironmentSpec(**defaults)


# ---------------------------------------------------------------------------
# TestGoEnvironmentSpec
# ---------------------------------------------------------------------------

class TestGoEnvironmentSpec:
    def test_construction_defaults(self) -> None:
        spec = GoEnvironmentSpec()
        assert spec.language == "go"
        assert spec.module_mode == "modules"
        assert spec.system_dependencies == []
        assert spec.env_spec_hash == ""

    def test_construction_with_values(self) -> None:
        spec = _make_spec(go_version="1.21", module_mode="vendored")
        assert spec.go_version == "1.21"
        assert spec.module_mode == "vendored"

    def test_system_dependencies_independent(self) -> None:
        # Default mutable should not be shared between instances
        a = GoEnvironmentSpec()
        b = GoEnvironmentSpec()
        a.system_dependencies.append("git")
        assert b.system_dependencies == []

    def test_language_always_go(self) -> None:
        spec = GoEnvironmentSpec()
        assert spec.language == "go"


# ---------------------------------------------------------------------------
# TestComputeEnvSpecHash
# ---------------------------------------------------------------------------

class TestComputeEnvSpecHash:
    def test_returns_64_char_hex(self) -> None:
        spec = _make_spec()
        h = compute_env_spec_hash(spec)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_identical_specs_produce_same_hash(self) -> None:
        a = _make_spec()
        b = _make_spec()
        assert compute_env_spec_hash(a) == compute_env_spec_hash(b)

    def test_different_go_version_changes_hash(self) -> None:
        a = _make_spec(go_version="1.21")
        b = _make_spec(go_version="1.22")
        assert compute_env_spec_hash(a) != compute_env_spec_hash(b)

    def test_different_test_cmd_changes_hash(self) -> None:
        a = _make_spec(test_cmd="go test ./...")
        b = _make_spec(test_cmd="make test")
        assert compute_env_spec_hash(a) != compute_env_spec_hash(b)

    def test_different_module_mode_changes_hash(self) -> None:
        a = _make_spec(module_mode="modules")
        b = _make_spec(module_mode="vendored")
        assert compute_env_spec_hash(a) != compute_env_spec_hash(b)

    def test_system_dep_order_does_not_affect_hash(self) -> None:
        # sorted() is applied before hashing
        a = _make_spec(system_dependencies=["git", "make"])
        b = _make_spec(system_dependencies=["make", "git"])
        assert compute_env_spec_hash(a) == compute_env_spec_hash(b)

    def test_env_spec_hash_field_excluded_from_computation(self) -> None:
        spec = _make_spec()
        h1 = compute_env_spec_hash(spec)
        spec.env_spec_hash = "some_previous_value"
        h2 = compute_env_spec_hash(spec)
        assert h1 == h2

    def test_hash_stable_across_calls(self) -> None:
        spec = _make_spec()
        hashes = {compute_env_spec_hash(spec) for _ in range(10)}
        assert len(hashes) == 1


# ---------------------------------------------------------------------------
# TestGoSpecRegistry
# ---------------------------------------------------------------------------

class TestGoSpecRegistry:
    def test_register_returns_version_string(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec(go_version="1.22")
        version = reg.register("kubernetes/kubectl", "abc123", spec)
        assert version.startswith("1.22-")

    def test_register_idempotent(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec()
        v1 = reg.register("kubernetes/kubectl", "abc123", spec)
        v2 = reg.register("kubernetes/kubectl", "def456", spec)
        assert v1 == v2  # same spec → same version string

    def test_get_version_returns_registered(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec()
        h = compute_env_spec_hash(spec)
        reg.register("kubernetes/kubectl", "abc123", spec)
        assert reg.get_version(h) is not None

    def test_get_version_unknown_returns_none(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        assert reg.get_version("nonexistent_hash") is None

    def test_get_era_commit_returns_registered(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec()
        h = compute_env_spec_hash(spec)
        reg.register("kubernetes/kubectl", "abc123", spec)
        assert reg.get_era_commit(h) == "abc123"

    def test_get_era_commit_unknown_returns_none(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        assert reg.get_era_commit("nonexistent") is None

    def test_persistence_survives_reload(self, tmp_path: Path) -> None:
        spec = _make_spec()
        h = compute_env_spec_hash(spec)

        reg1 = GoSpecRegistry(tmp_path)
        version = reg1.register("kubernetes/kubectl", "abc123", spec)

        reg2 = GoSpecRegistry(tmp_path)
        assert reg2.get_version(h) == version
        assert reg2.get_era_commit(h) == "abc123"

    def test_different_specs_different_versions(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec_a = _make_spec(go_version="1.21")
        spec_b = _make_spec(go_version="1.22")
        v_a = reg.register("kubernetes/kubectl", "abc", spec_a)
        v_b = reg.register("kubernetes/kubectl", "def", spec_b)
        assert v_a != v_b

    def test_registry_file_created(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        reg.register("kubernetes/kubectl", "abc", _make_spec())
        registry_file = tmp_path / "go-spec-registry.json"
        assert registry_file.exists()
        data = json.loads(registry_file.read_text())
        assert isinstance(data, dict)
        assert len(data) == 1

    def test_no_go_version_falls_back_to_hash(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec(go_version="")
        version = reg.register("kubernetes/kubectl", "abc", spec)
        assert len(version) >= 8  # hash-based fallback


# ---------------------------------------------------------------------------
# TestGoVersionString
# ---------------------------------------------------------------------------

class TestGoVersionString:
    def test_version_string_format(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        spec = _make_spec(go_version="1.22")
        v = reg.register("kubernetes/kubectl", "abc", spec)
        parts = v.split("-")
        assert parts[0] == "1.22"
        assert len(parts[1]) == 8

    def test_version_string_unique_per_spec(self, tmp_path: Path) -> None:
        reg = GoSpecRegistry(tmp_path)
        versions = set()
        for go_ver in ["1.20", "1.21", "1.22"]:
            spec = _make_spec(go_version=go_ver)
            versions.add(reg.register("kubernetes/kubectl", "abc", spec))
        assert len(versions) == 3
