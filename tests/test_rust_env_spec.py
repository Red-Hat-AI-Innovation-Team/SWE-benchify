"""Tests for RustEnvironmentSpec, compute_rust_env_spec_hash, and RustSpecRegistry."""

from __future__ import annotations

from typing import Any

from swebenchify.models import RustEnvironmentSpec, compute_rust_env_spec_hash
from swebenchify.rust_registry import RustSpecRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(**overrides: Any) -> RustEnvironmentSpec:
    defaults: dict[str, Any] = dict(
        language="rust",
        rust_version="1.84",
        build_cmd="cargo build",
        test_cmd="cargo test --workspace",
        workspace_mode="single",
        workspace_members=[],
        edition="2021",
        features="",
        system_dependencies=[],
    )
    defaults.update(overrides)
    return RustEnvironmentSpec(**defaults)


# ---------------------------------------------------------------------------
# TestRustEnvironmentSpec
# ---------------------------------------------------------------------------

class TestRustEnvironmentSpec:
    def test_default_values(self) -> None:
        spec = RustEnvironmentSpec()
        assert spec.language == "rust"
        assert spec.workspace_mode == "single"
        assert spec.rust_version == ""
        assert spec.build_cmd == ""
        assert spec.test_cmd == ""
        assert spec.workspace_members == []
        assert spec.edition == ""
        assert spec.features == ""
        assert spec.system_dependencies == []
        assert spec.env_spec_hash == ""

    def test_construction_with_values(self) -> None:
        spec = _make_spec(
            rust_version="1.84",
            workspace_mode="workspace",
            edition="2024",
            features="--all-features",
            workspace_members=["crate-a", "crate-b"],
        )
        assert spec.rust_version == "1.84"
        assert spec.workspace_mode == "workspace"
        assert spec.edition == "2024"
        assert spec.features == "--all-features"
        assert spec.workspace_members == ["crate-a", "crate-b"]

    def test_independent_mutable_defaults(self) -> None:
        a = RustEnvironmentSpec()
        b = RustEnvironmentSpec()
        a.workspace_members.append("crate-x")
        a.system_dependencies.append("git")
        assert b.workspace_members == []
        assert b.system_dependencies == []

    def test_language_always_rust(self) -> None:
        spec = RustEnvironmentSpec()
        assert spec.language == "rust"


# ---------------------------------------------------------------------------
# TestComputeRustEnvSpecHash
# ---------------------------------------------------------------------------

class TestComputeRustEnvSpecHash:
    def test_returns_64_char_hex(self) -> None:
        spec = _make_spec()
        h = compute_rust_env_spec_hash(spec)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_identical_specs_same_hash(self) -> None:
        a = _make_spec()
        b = _make_spec()
        assert compute_rust_env_spec_hash(a) == compute_rust_env_spec_hash(b)

    def test_different_rust_version_changes_hash(self) -> None:
        a = _make_spec(rust_version="1.84")
        b = _make_spec(rust_version="1.80")
        assert compute_rust_env_spec_hash(a) != compute_rust_env_spec_hash(b)

    def test_different_test_cmd_changes_hash(self) -> None:
        a = _make_spec(test_cmd="cargo test --workspace")
        b = _make_spec(test_cmd="make test")
        assert compute_rust_env_spec_hash(a) != compute_rust_env_spec_hash(b)

    def test_different_workspace_mode_changes_hash(self) -> None:
        a = _make_spec(workspace_mode="single")
        b = _make_spec(workspace_mode="workspace")
        assert compute_rust_env_spec_hash(a) != compute_rust_env_spec_hash(b)

    def test_system_dep_order_irrelevant(self) -> None:
        a = _make_spec(system_dependencies=["git", "make"])
        b = _make_spec(system_dependencies=["make", "git"])
        assert compute_rust_env_spec_hash(a) == compute_rust_env_spec_hash(b)

    def test_workspace_members_order_irrelevant(self) -> None:
        a = _make_spec(workspace_members=["crate-a", "crate-b"])
        b = _make_spec(workspace_members=["crate-b", "crate-a"])
        assert compute_rust_env_spec_hash(a) == compute_rust_env_spec_hash(b)

    def test_env_spec_hash_excluded(self) -> None:
        spec = _make_spec()
        h1 = compute_rust_env_spec_hash(spec)
        spec.env_spec_hash = "some_previous_value"
        h2 = compute_rust_env_spec_hash(spec)
        assert h1 == h2

    def test_hash_stable_across_calls(self) -> None:
        spec = _make_spec()
        hashes = {compute_rust_env_spec_hash(spec) for _ in range(10)}
        assert len(hashes) == 1


# ---------------------------------------------------------------------------
# TestRustSpecRegistry
# ---------------------------------------------------------------------------

class TestRustSpecRegistry:
    def test_register_returns_version_string(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec(rust_version="1.84")
        version = reg.register("owner/repo", "abc123", spec)
        assert version.startswith("1.84-")

    def test_register_idempotent(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec()
        v1 = reg.register("owner/repo", "abc123", spec)
        v2 = reg.register("owner/repo", "abc123", spec)
        assert v1 == v2

    def test_get_version_registered(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec()
        expected = reg.register("owner/repo", "abc123", spec)
        spec_hash = compute_rust_env_spec_hash(spec)
        assert reg.get_version(spec_hash) == expected

    def test_get_version_unknown(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        assert reg.get_version("nonexistent_hash") is None

    def test_get_era_commit_registered(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec()
        reg.register("owner/repo", "abc123def", spec)
        spec_hash = compute_rust_env_spec_hash(spec)
        assert reg.get_era_commit(spec_hash) == "abc123def"

    def test_get_era_commit_unknown(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        assert reg.get_era_commit("nonexistent_hash") is None

    def test_persistence_survives_reload(self, tmp_path) -> None:
        spec = _make_spec()
        reg1 = RustSpecRegistry(tmp_path)
        version = reg1.register("owner/repo", "abc123", spec)

        reg2 = RustSpecRegistry(tmp_path)
        spec_hash = compute_rust_env_spec_hash(spec)
        assert reg2.get_version(spec_hash) == version
        assert reg2.get_era_commit(spec_hash) == "abc123"

    def test_different_specs_different_versions(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec_a = _make_spec(rust_version="1.84")
        spec_b = _make_spec(rust_version="1.80")
        v_a = reg.register("owner/repo", "aaa", spec_a)
        v_b = reg.register("owner/repo", "bbb", spec_b)
        assert v_a != v_b

    def test_registry_file_created(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec()
        reg.register("owner/repo", "abc123", spec)
        assert (tmp_path / "rust-spec-registry.json").exists()

    def test_no_rust_version_falls_back_to_hash(self, tmp_path) -> None:
        reg = RustSpecRegistry(tmp_path)
        spec = _make_spec(rust_version="")
        version = reg.register("owner/repo", "abc123", spec)
        spec_hash = compute_rust_env_spec_hash(spec)
        assert version == spec_hash[:12]
        assert "-" not in version
