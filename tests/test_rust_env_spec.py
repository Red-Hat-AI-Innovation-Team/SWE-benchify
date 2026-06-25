"""Tests for RustEnvironmentSpec and compute_rust_env_spec_hash."""

from __future__ import annotations

from swebenchify.models import RustEnvironmentSpec, compute_rust_env_spec_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(**overrides) -> RustEnvironmentSpec:
    defaults = dict(
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
