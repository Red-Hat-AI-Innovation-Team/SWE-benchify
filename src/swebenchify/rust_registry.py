"""Rust spec registry — maps env_spec_hash to (version_string, era_commit).

The registry is persisted as a JSON file so version strings are stable
across pipeline re-runs. Each unique RustEnvironmentSpec gets a
``version_string`` of the form ``"{rust_version}-{hash_prefix}"`` (e.g.
``"1.84-ab3f1200"``), making it human-readable and unique.

The ``era_commit`` is the earliest commit at which the spec was valid —
used to populate ``environment_setup_commit`` for Rust instances.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from swebenchify.models import RustEnvironmentSpec, compute_rust_env_spec_hash

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "rust-spec-registry.json"


class RustSpecRegistry:
    """Persistent registry mapping env_spec_hash to version string and era commit.

    Backed by a JSON file at ``{workspace_dir}/rust-spec-registry.json``.
    """

    def __init__(self, workspace_dir: str | Path) -> None:
        self._path = Path(workspace_dir) / _REGISTRY_FILENAME
        self._data: dict[str, dict[str, str]] = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        repo: str,
        era_commit: str,
        spec: RustEnvironmentSpec,
    ) -> str:
        """Register a spec and return a stable version string.

        If the spec (identified by its ``env_spec_hash``) is already
        registered, the existing version string is returned unchanged.

        Args:
            repo: Repository full name (e.g. ``"nickel-org/nickel.rs"``).
            era_commit: Base commit at which the spec was discovered valid.
            spec: The ``RustEnvironmentSpec`` to register.

        Returns:
            A version string of the form ``"{rust_version}-{hash[:8]}"``.
        """
        spec_hash = compute_rust_env_spec_hash(spec)
        if spec_hash not in self._data:
            version_string = f"{spec.rust_version}-{spec_hash[:8]}" if spec.rust_version else spec_hash[:12]
            self._data[spec_hash] = {
                "version": version_string,
                "era_commit": era_commit,
                "repo": repo,
            }
            self._save()
            logger.debug(
                "Registered Rust spec for %s: %s -> %s (era %s)",
                repo, spec_hash[:12], version_string, era_commit[:12],
            )
        return self._data[spec_hash]["version"]

    def get_version(self, env_spec_hash: str) -> str | None:
        """Look up the version string for a given hash."""
        entry = self._data.get(env_spec_hash)
        return entry["version"] if entry else None

    def get_era_commit(self, env_spec_hash: str) -> str | None:
        """Look up the era commit for a given hash."""
        entry = self._data.get(env_spec_hash)
        return entry["era_commit"] if entry else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, str]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load Rust spec registry: %s", exc)
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))


def get_rust_environment_setup_commit(
    repo_path: str | Path,
    spec: RustEnvironmentSpec,
    registry: RustSpecRegistry | None = None,
) -> str | None:
    """Return the environment_setup_commit for a Rust spec.

    Checks the registry first (fastest). Falls back to scanning git log
    for the earliest commit whose ``rust-toolchain.toml`` or ``Cargo.toml``
    declares the same Rust version as the spec.

    Args:
        repo_path: Path to the bare or working-tree git clone.
        spec: The discovered ``RustEnvironmentSpec``.
        registry: Optional registry to check before git scanning.

    Returns:
        A commit SHA, or ``None`` if not found.
    """
    if registry is not None:
        spec_hash = compute_rust_env_spec_hash(spec)
        era_commit = registry.get_era_commit(spec_hash)
        if era_commit:
            return era_commit

    if not spec.rust_version:
        return None

    repo_path = Path(repo_path)
    try:
        result = subprocess.run(
            [
                "git", "log", "--format=%H",
                "--diff-filter=M", "--", "rust-toolchain.toml", "Cargo.toml",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        commits = result.stdout.strip().split("\n")
        for sha in reversed(commits):
            sha = sha.strip()
            if not sha:
                continue
            if _commit_matches_rust_version(repo_path, sha, spec.rust_version):
                return sha
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _commit_matches_rust_version(
    repo_path: Path, sha: str, rust_version: str,
) -> bool:
    """Check if a commit's rust-toolchain.toml or Cargo.toml matches the version."""
    for filename in ("rust-toolchain.toml", "Cargo.toml"):
        try:
            content_result = subprocess.run(
                ["git", "show", f"{sha}:{filename}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if content_result.returncode != 0:
                continue
            for line in content_result.stdout.splitlines():
                stripped = line.strip()
                if filename == "rust-toolchain.toml" and stripped.startswith("channel"):
                    value = stripped.split("=", 1)[1].strip().strip("'\"")
                    if value == rust_version:
                        return True
                elif filename == "Cargo.toml" and stripped.startswith("rust-version"):
                    value = stripped.split("=", 1)[1].strip().strip("'\"")
                    if value == rust_version:
                        return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return False
