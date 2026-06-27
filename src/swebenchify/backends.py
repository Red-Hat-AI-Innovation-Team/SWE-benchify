"""Language backend registry for deterministic Docker validation.

Each ``LanguageBackend`` encapsulates the language-specific pieces needed
to build a Docker image, run tests, and parse output. The generic
orchestration in ``grader.compute_f2p()`` dispatches through this registry
so adding a new language is configuration, not forked code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from swebenchify.models import AnyEnvironmentSpec, EnvironmentSpec, GoEnvironmentSpec
from swebenchify.parsers import (
    GoJSONParser,
    MavenSurefireParser,
    PytestVerboseParser,
    TestLogParser,
    normalize_go_f2p,
)


@dataclass
class LanguageBackend:
    """Language-specific configuration for Docker-based validation."""

    name: str
    test_file_pattern: str
    failure_grep: str
    default_timeout: int
    parser: TestLogParser
    make_dockerfile: Callable[[str, str, AnyEnvironmentSpec], str]
    make_test_cmd: Callable[[AnyEnvironmentSpec], str]
    test_scope: Callable[[str], str]
    normalize_f2p: Callable[[list[str]], list[str]]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, LanguageBackend] = {}


def register_backend(backend: LanguageBackend) -> None:
    _BACKENDS[backend.name] = backend


def get_backend(language: str) -> LanguageBackend | None:
    return _BACKENDS.get(language)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _git_clone_or_archive(repo: str, base_commit: str) -> str:
    """RUN instruction that checks out *base_commit*, falling back to the
    GitHub archive API when the commit is unreachable (e.g. GC'd merge SHA)."""
    return (
        f"RUN (git clone https://github.com/{repo}.git /repo && "
        f"cd /repo && (git checkout {base_commit} || "
        f"(git fetch origin {base_commit} && git checkout {base_commit}))) "
        f"|| (rm -rf /repo && mkdir -p /repo && cd /repo && git init && "
        f"curl -sL https://github.com/{repo}/archive/{base_commit}.tar.gz | "
        f"tar xz --strip-components=1 && git add -A && git commit -q -m base)"
    )


# ---------------------------------------------------------------------------
# Go backend helpers
# ---------------------------------------------------------------------------

def _go_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, GoEnvironmentSpec) else None
    if spec and spec.go_version:
        base = f"golang:{spec.go_version}"
    else:
        base = "golang:latest"

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
        _git_clone_or_archive(repo, base_commit),
    ]

    if spec and spec.system_dependencies:
        pkgs = " ".join(spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs} && "
            "rm -rf /var/lib/apt/lists/*"
        )

    if spec and spec.goflags:
        lines.append(f'ENV GOFLAGS="{spec.goflags}"')

    lines.append("COPY test.patch /patches/test.patch")
    lines.append("COPY gold.patch /patches/gold.patch")
    return "\n".join(lines) + "\n"


def _go_make_test_cmd(env_spec: AnyEnvironmentSpec) -> str:
    return "go test -json -count=1"


def _go_test_scope(test_patch: str) -> str:
    """Return Go package scope from diff headers."""
    seen: dict[str, list[str]] = {}
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        top = Path(path).parts[0] if Path(path).parts else "."
        rel_pkg = str(Path(*Path(path).parts[1:-1])) if len(Path(path).parts) > 2 else "."
        pkg = f"./{rel_pkg}" if rel_pkg != "." else "./..."
        if top not in seen:
            seen[top] = []
        if pkg not in seen[top]:
            seen[top].append(pkg)

    cmds: list[str] = []
    for root, pkgs in seen.items():
        if root == ".":
            cmds.extend(pkgs)
        else:
            for pkg in pkgs:
                cmds.append(f"./{root}/{pkg.lstrip('./')}")
    return " ".join(cmds) if cmds else "./..."


# ---------------------------------------------------------------------------
# Python backend helpers
# ---------------------------------------------------------------------------

def _python_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None

    if spec and spec.base_image:
        base = spec.base_image
    else:
        version = (spec.language_version if spec else None) or "3.11"
        base = f"python:{version}-slim"

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
    ]

    if not (spec and spec.base_image):
        lines.append(
            "RUN apt-get update -qq && "
            "apt-get install -y --no-install-recommends git"
        )

    if spec and spec.system_dependencies:
        pkgs = " ".join(spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs}"
        )

    lines.append("RUN rm -rf /var/lib/apt/lists/*")

    lines.append(_git_clone_or_archive(repo, base_commit))

    if spec:
        for cmd in spec.pre_install:
            lines.append(f"RUN cd /repo && {cmd}")
        if spec.install_cmd:
            lines.append(f"RUN cd /repo && {spec.install_cmd}")
        if spec.pip_packages:
            pkg_str = " ".join(f"'{p}'" for p in spec.pip_packages)
            lines.append(f"RUN pip install --no-deps {pkg_str}")

    lines.append("COPY test.patch /patches/test.patch")
    lines.append("COPY gold.patch /patches/gold.patch")
    return "\n".join(lines) + "\n"


def _ensure_pytest_verbose(cmd: str) -> str:
    if "-v" in cmd:
        return cmd
    if "pytest" in cmd:
        return cmd.replace("pytest", "pytest -v", 1)
    return cmd + " -v"


def _python_make_test_cmd(env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None
    raw_cmd = (spec.test_cmd if spec else None) or "pytest"
    return _ensure_pytest_verbose(raw_cmd)


def _python_test_scope(test_patch: str) -> str:
    """Return space-separated test .py file paths from diff headers.

    Only includes files matching pytest's default discovery pattern
    (test_*.py or *_test.py) to avoid collecting non-test modules.
    """
    files: list[str] = []
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        if not path.endswith(".py"):
            continue
        basename = Path(path).name
        if basename.startswith("test_") or basename.endswith("_test.py"):
            files.append(path)
    return " ".join(files)


# ---------------------------------------------------------------------------
# Java backend helpers
# ---------------------------------------------------------------------------

def _java_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None

    java_version = (spec.language_version if spec else None) or "17"
    base = f"maven:3-eclipse-temurin-{java_version}"

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
        _git_clone_or_archive(repo, base_commit),
    ]

    if spec and spec.system_dependencies:
        pkgs = " ".join(spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs} && "
            "rm -rf /var/lib/apt/lists/*"
        )

    if spec:
        for cmd in spec.pre_install:
            lines.append(f"RUN cd /repo && {cmd}")
        if spec.install_cmd:
            lines.append(f"RUN cd /repo && {spec.install_cmd}")

    lines.append("COPY test.patch /patches/test.patch")
    lines.append("COPY gold.patch /patches/gold.patch")
    return "\n".join(lines) + "\n"


def _java_make_test_cmd(env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None
    raw_cmd = (spec.test_cmd if spec else None) or "mvn test -B"
    if "-Dmaven.test.failure.ignore" not in raw_cmd:
        raw_cmd += " -Dmaven.test.failure.ignore=true"
    return raw_cmd


def _java_test_scope(test_patch: str) -> str:
    """Extract Maven test scope from diff headers.

    Converts paths like ``src/test/java/com/example/SomethingTest.java``
    to ``-Dtest=com.example.SomethingTest,...``.
    """
    classes: list[str] = []
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path

        if not path.endswith(".java"):
            continue

        idx = path.find("src/test/java/")
        if idx == -1:
            continue

        class_path = path[idx + len("src/test/java/"):]
        class_name = class_path.replace("/", ".").removesuffix(".java")
        if class_name and class_name not in classes:
            classes.append(class_name)

    if not classes:
        return ""
    return "-Dtest=" + ",".join(classes)


def _java_normalize_f2p(test_ids: list[str]) -> list[str]:
    return sorted(set(test_ids))


# ---------------------------------------------------------------------------
# Register built-in backends
# ---------------------------------------------------------------------------

register_backend(LanguageBackend(
    name="go",
    test_file_pattern="_test.go",
    failure_grep='"Action":"fail"',
    default_timeout=300,
    parser=GoJSONParser(),
    make_dockerfile=_go_make_dockerfile,
    make_test_cmd=_go_make_test_cmd,
    test_scope=_go_test_scope,
    normalize_f2p=normalize_go_f2p,
))

register_backend(LanguageBackend(
    name="python",
    test_file_pattern=".py",
    failure_grep="FAILED\\|ERROR",
    default_timeout=600,
    parser=PytestVerboseParser(),
    make_dockerfile=_python_make_dockerfile,
    make_test_cmd=_python_make_test_cmd,
    test_scope=_python_test_scope,
    normalize_f2p=sorted,
))

register_backend(LanguageBackend(
    name="java",
    test_file_pattern="Test.java",
    failure_grep="<<< FAILURE\\|<<< ERROR",
    default_timeout=900,
    parser=MavenSurefireParser(),
    make_dockerfile=_java_make_dockerfile,
    make_test_cmd=_java_make_test_cmd,
    test_scope=_java_test_scope,
    normalize_f2p=_java_normalize_f2p,
))
