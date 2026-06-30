"""SWE-bench harness compatibility.

Ensures our generated instances can be run through the standard
SWE-bench evaluation harness (swebench.harness.run_evaluation).

Two requirements:
1. version must match MAP_REPO_VERSION_TO_SPECS for supported repos
2. environment_setup_commit must be a real commit SHA
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swebenchify.go_registry import GoSpecRegistry
    from swebenchify.models import GoEnvironmentSpec

logger = logging.getLogger(__name__)

# Lazy-loaded to avoid hard dependency on swebench package
_SUPPORTED_VERSIONS: dict[str, set[str]] | None = None


def _load_supported_versions() -> dict[str, set[str]]:
    global _SUPPORTED_VERSIONS
    if _SUPPORTED_VERSIONS is not None:
        return _SUPPORTED_VERSIONS
    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
        _SUPPORTED_VERSIONS = {
            repo: set(versions.keys())
            for repo, versions in MAP_REPO_VERSION_TO_SPECS.items()
        }
    except ImportError:
        logger.warning("swebench not installed — cannot validate version compatibility")
        _SUPPORTED_VERSIONS = {}
    return _SUPPORTED_VERSIONS


def is_version_supported(repo: str, version: str) -> bool:
    """Check if a repo/version pair is supported by the SWE-bench harness."""
    supported = _load_supported_versions()
    if repo not in supported:
        return False
    return version in supported[repo]


def get_supported_versions(repo: str) -> set[str]:
    """Get the set of versions supported by SWE-bench for a repo."""
    supported = _load_supported_versions()
    return supported.get(repo, set())


def snap_version(repo: str, detected_version: str) -> str | None:
    """Snap a detected version to the closest SWE-bench supported version.

    For example, detected '2.3.1' snaps to '2.3' if '2.3' is supported.
    Returns None if no match found.
    """
    supported = get_supported_versions(repo)
    if not supported:
        return None

    if detected_version in supported:
        return detected_version

    # Try major.minor from detected version
    parts = detected_version.split(".")
    if len(parts) >= 2:
        major_minor = f"{parts[0]}.{parts[1]}"
        if major_minor in supported:
            return major_minor

    # Try just major
    if parts[0] in supported:
        return parts[0]

    return None


_ENV_SETUP_COMMITS: dict[str, dict[str, str]] | None = None


def _load_env_setup_commits() -> dict[str, dict[str, str]]:
    global _ENV_SETUP_COMMITS
    if _ENV_SETUP_COMMITS is not None:
        return _ENV_SETUP_COMMITS
    import json as _json
    commits_file = Path(__file__).parent / "env_setup_commits.json"
    if commits_file.exists():
        _ENV_SETUP_COMMITS = _json.loads(commits_file.read_text())
    else:
        _ENV_SETUP_COMMITS = {}
    return _ENV_SETUP_COMMITS


def get_environment_setup_commit(
    repo_name: str, version: str, repo_path: str | Path | None = None
) -> str | None:
    """Get the environment_setup_commit for a repo version.

    First checks the known mapping from SWE-bench data. Falls back to
    git tag lookup if repo_path is provided.
    """
    # Check known mapping first
    known = _load_env_setup_commits()
    if repo_name in known and version in known[repo_name]:
        return known[repo_name][version]

    # Fallback: git tag lookup
    if repo_path is None:
        return None
    repo_path = str(repo_path)
    try:
        result = subprocess.run(
            ["git", "tag", "-l", f"v{version}*", f"{version}*", "--sort=-v:refname"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            tag = result.stdout.strip().split("\n")[0]
            sha_result = subprocess.run(
                ["git", "rev-parse", f"{tag}^{{commit}}"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if sha_result.returncode == 0:
                return sha_result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_go_version_string(
    spec: "GoEnvironmentSpec",
    registry: "GoSpecRegistry",
) -> str:
    """Return the version string for a Go spec from the registry.

    Falls back to a hash-based string if not found (should not happen after
    a successful ``discover_go_environment`` call).
    """
    from swebenchify.models import compute_env_spec_hash
    spec_hash = compute_env_spec_hash(spec)
    version = registry.get_version(spec_hash)
    if version:
        return version
    # Fallback: construct inline (registry may not be loaded yet)
    return f"{spec.go_version}-{spec_hash[:8]}" if spec.go_version else spec_hash[:12]


def filter_compatible_instances(instances: list, repo: str) -> tuple[list, list]:
    """Split instances into compatible (version supported) and incompatible.

    Returns (compatible, incompatible) lists.
    """
    compatible = []
    incompatible = []
    for inst in instances:
        version = getattr(inst, "version", None) or inst.get("version")
        snapped = snap_version(repo, version) if version else None
        if snapped:
            compatible.append(inst)
        else:
            incompatible.append(inst)
    return compatible, incompatible
