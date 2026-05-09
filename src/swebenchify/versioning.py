"""Mechanical version detection from repository metadata files."""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_version(repo_path: str | Path, commit: str | None = None) -> str | None:
    """Detect the project version from metadata files at a given commit.

    Checks (in order):
    1. pyproject.toml — [project] version or [tool.poetry] version
    2. setup.cfg — [metadata] version
    3. setup.py — version= argument
    4. package.json — "version" field
    5. Cargo.toml — [package] version
    6. Git tags — most recent version-like tag

    Returns major.minor version string (e.g., "2.3") or None if not detected.
    """
    repo_path = Path(repo_path)

    # If commit specified, use git show to read files at that commit
    def read_file(relpath: str) -> str | None:
        if commit:
            try:
                result = subprocess.run(
                    ["git", "show", f"{commit}:{relpath}"],
                    cwd=repo_path, capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    return result.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            return None
        else:
            p = repo_path / relpath
            return p.read_text() if p.exists() else None

    # Try each source in order
    version = (
        _from_pyproject(read_file("pyproject.toml"))
        or _from_setup_cfg(read_file("setup.cfg"))
        or _from_setup_py(read_file("setup.py"))
        or _from_package_json(read_file("package.json"))
        or _from_cargo_toml(read_file("Cargo.toml"))
        or _from_git_tags(repo_path, commit)
    )

    if version:
        return _to_major_minor(version)
    return None


def _to_major_minor(version: str) -> str:
    """Convert a full version string to major.minor format."""
    # Strip leading v
    version = version.lstrip("v")
    # Match major.minor
    m = re.match(r"(\d+\.\d+)", version)
    return m.group(1) if m else version


def _from_pyproject(content: str | None) -> str | None:
    if not content:
        return None
    # Try [project] version = "..."
    m = re.search(r'\[project\].*?version\s*=\s*["\']([^"\']+)["\']', content, re.DOTALL)
    if m:
        return m.group(1)
    # Try [tool.poetry] version = "..."
    m = re.search(r'\[tool\.poetry\].*?version\s*=\s*["\']([^"\']+)["\']', content, re.DOTALL)
    if m:
        return m.group(1)
    return None


def _from_setup_cfg(content: str | None) -> str | None:
    if not content:
        return None
    m = re.search(r'\[metadata\].*?version\s*=\s*(\S+)', content, re.DOTALL)
    return m.group(1) if m else None


def _from_setup_py(content: str | None) -> str | None:
    if not content:
        return None
    m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    return m.group(1) if m else None


def _from_package_json(content: str | None) -> str | None:
    if not content:
        return None
    try:
        data = json.loads(content)
        return data.get("version")
    except (json.JSONDecodeError, TypeError):
        return None


def _from_cargo_toml(content: str | None) -> str | None:
    if not content:
        return None
    m = re.search(r'\[package\].*?version\s*=\s*["\']([^"\']+)["\']', content, re.DOTALL)
    return m.group(1) if m else None


def _from_git_tags(repo_path: Path, commit: str | None) -> str | None:
    try:
        cmd = ["git", "tag", "--sort=-v:refname"]
        if commit:
            cmd.extend(["--merged", commit])
        result = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for tag in result.stdout.strip().split("\n"):
                tag = tag.strip()
                if re.match(r"v?\d+\.\d+", tag):
                    return tag.lstrip("v")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None
