"""Language backend registry for deterministic Docker validation.

Each ``LanguageBackend`` encapsulates the language-specific pieces needed
to build a Docker image, run tests, and parse output. The generic
orchestration in ``grader.compute_f2p()`` dispatches through this registry
so adding a new language is configuration, not forked code.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Callable

from unidiff import PatchSet

from swebenchify.models import (
    AnyEnvironmentSpec,
    EnvironmentSpec,
    GoEnvironmentSpec,
    RustEnvironmentSpec,
)
from swebenchify.parsers import (
    GoJSONParser,
    MavenSurefireParser,
    PytestVerboseParser,
    RustTestParser,
    TestLogParser,
    normalize_go_f2p,
    normalize_rust_f2p,
)

logger = logging.getLogger(__name__)


@dataclass
class LanguageBackend:
    """Language-specific configuration for Docker-based validation."""

    name: str
    test_file_pattern: str
    failure_grep: str
    default_timeout: int
    parser: TestLogParser
    make_dockerfile: Callable[..., str]
    make_test_cmd: Callable[[AnyEnvironmentSpec], str]
    test_scope: Callable[[str], str]
    normalize_f2p: Callable[[list[str]], list[str]]
    is_test_hunk: Callable[[Any, list[tuple[int, int]] | None], bool] | None = field(default=None)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, LanguageBackend] = {}


def register_backend(backend: LanguageBackend) -> None:
    logger.debug("Registering backend", extra={"language": backend.name})
    _BACKENDS[backend.name] = backend


def get_backend(language: str) -> LanguageBackend | None:
    backend = _BACKENDS.get(language)
    if backend is None:
        logger.warning("No backend registered", extra={"language": language, "available": list(_BACKENDS.keys())})
    return backend


def _reconstruct_file_diff(patched_file: Any, hunks: list[Any]) -> str:
    """Build a valid unified diff string from a file header and a subset of hunks."""
    header = f"diff --git a/{patched_file.path} b/{patched_file.path}\n"
    header += f"--- {patched_file.source_file}\n"
    header += f"+++ {patched_file.target_file}\n"
    return header + "".join(str(h) for h in hunks)


def refine_patch_split(
    gold_patch: str | None,
    test_patch: str | None,
    backend: LanguageBackend,
    source_callback: Callable[[str], str | None] | None = None,
) -> tuple[str | None, str | None]:
    """Re-split patches using a backend's ``is_test_hunk`` callback.

    The generic extractor splits at the file level. Some languages (e.g.
    Rust) put unit tests inline in source files. This function re-examines
    hunks in the gold patch and moves any that the backend identifies as
    test code into the test patch.

    If the backend has no ``is_test_hunk`` callback, returns the inputs
    unchanged.

    When *source_callback* is provided, it is called for ``.rs`` files to
    retrieve the base-commit source so that :func:`_rust_parse_test_regions`
    can compute precise test-module boundaries.  The callback signature is
    ``(file_path: str) -> str | None``.
    """
    if not backend.is_test_hunk or not gold_patch:
        return gold_patch, test_patch

    if not gold_patch.strip():
        logger.warning("empty gold_patch input, skipping refinement")
        return gold_patch, test_patch

    try:
        patch_set = PatchSet(StringIO(gold_patch))
    except Exception:
        logger.warning("Failed to parse gold patch for hunk-level split", extra={"backend": backend.name})
        return gold_patch, test_patch

    ext = {"rust": ".rs"}.get(backend.name)
    if not ext:
        return gold_patch, test_patch

    new_gold: list[str] = []
    extra_test: list[str] = []

    for patched_file in patch_set:
        if not patched_file.path.endswith(ext) or len(patched_file) == 0:
            new_gold.append(str(patched_file))
            continue

        test_regions: list[tuple[int, int]] | None = None
        if source_callback is not None:
            source = source_callback(patched_file.path)
            if source is not None:
                test_regions = _rust_parse_test_regions(source)
            else:
                logger.warning(
                    "source_callback returned None for path=%s, falling back to heuristic",
                    patched_file.path,
                )

        gold_hunks = []
        test_hunks = []
        for hunk in patched_file:
            is_test = backend.is_test_hunk(hunk, test_regions)
            logger.debug(
                "hunk file=%s lines=%d-%d classified=%s",
                patched_file.path,
                hunk.source_start,
                hunk.source_start + hunk.source_length,
                "test" if is_test else "gold",
            )
            if is_test:
                test_hunks.append(hunk)
            else:
                gold_hunks.append(hunk)

        if gold_hunks:
            new_gold.append(_reconstruct_file_diff(patched_file, gold_hunks))
        if test_hunks:
            extra_test.append(_reconstruct_file_diff(patched_file, test_hunks))

    refined_gold = "".join(new_gold) if new_gold else None
    if extra_test:
        combined = (test_patch or "") + "".join(extra_test)
        refined_test = combined if combined else None
        logger.info(
            "Refined patch split: moved test hunks from gold to test patch",
            extra={"backend": backend.name, "moved_hunks": len(extra_test)},
        )
    else:
        refined_test = test_patch

    moved = len(extra_test)
    if moved:
        logger.info("patch split refined: hunks_moved_to_test=%d", moved)
    return refined_gold, refined_test


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

def _go_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec, *, repo_tarball: bool = False) -> str:
    spec = env_spec if isinstance(env_spec, GoEnvironmentSpec) else None
    if spec and spec.go_version:
        base = f"golang:{spec.go_version}"
    else:
        base = "golang:latest"
    logger.debug("Building Go Dockerfile", extra={"repo": repo, "base_image": base, "tarball": repo_tarball})

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
    ]

    if repo_tarball:
        lines.append("COPY repo.tar.gz /tmp/repo.tar.gz")
        lines.append("RUN mkdir -p /repo && cd /repo && tar xzf /tmp/repo.tar.gz")
    else:
        lines.append(_git_clone_or_archive(repo, base_commit))

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
    """Return Go package scope from diff headers.

    In Go, the test scope is the directory containing the test file,
    expressed as a relative package path (e.g. ./internal/foo).
    """
    pkgs: set[str] = set()
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        pkg_dir = str(Path(path).parent)
        if pkg_dir == ".":
            pkgs.add("./...")
        else:
            pkgs.add(f"./{pkg_dir}")

    scope = " ".join(sorted(pkgs)) if pkgs else "./..."
    logger.debug("Resolved Go test scope", extra={"packages": scope})
    return scope


# ---------------------------------------------------------------------------
# Python backend helpers
# ---------------------------------------------------------------------------

def _python_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec, *, repo_tarball: bool = False) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None

    if spec and spec.base_image:
        base = spec.base_image
    else:
        version = (spec.language_version if spec else None) or "3.11"
        base = f"python:{version}-slim"
    logger.debug("Building Python Dockerfile", extra={"repo": repo, "base_image": base, "tarball": repo_tarball})

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

    if repo_tarball:
        lines.append("COPY repo.tar.gz /tmp/repo.tar.gz")
        lines.append("RUN mkdir -p /repo && cd /repo && tar xzf /tmp/repo.tar.gz")
    else:
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

def _java_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec, *, repo_tarball: bool = False) -> str:
    spec = env_spec if isinstance(env_spec, EnvironmentSpec) else None

    java_version = (spec.language_version if spec else None) or "17"
    base = f"maven:3-eclipse-temurin-{java_version}"
    logger.debug("Building Java Dockerfile", extra={"repo": repo, "base_image": base, "tarball": repo_tarball})

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
    ]

    if repo_tarball:
        lines.append("COPY repo.tar.gz /tmp/repo.tar.gz")
        lines.append("RUN mkdir -p /repo && cd /repo && tar xzf /tmp/repo.tar.gz")
    else:
        lines.append(_git_clone_or_archive(repo, base_commit))

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
        logger.debug("No Java test classes found in patch")
        return ""
    scope = "-Dtest=" + ",".join(classes)
    logger.debug("Resolved Java test scope", extra={"classes": classes})
    return scope


def _java_normalize_f2p(test_ids: list[str]) -> list[str]:
    return sorted(set(test_ids))


# ---------------------------------------------------------------------------
# Rust backend helpers
# ---------------------------------------------------------------------------

def _rust_make_dockerfile(repo: str, base_commit: str, env_spec: AnyEnvironmentSpec, *, repo_tarball: bool = False) -> str:
    spec = env_spec if isinstance(env_spec, RustEnvironmentSpec) else None
    if spec and spec.rust_version:
        base = f"rust:{spec.rust_version}-slim"
    else:
        base = "rust:latest"
    logger.debug("Building Rust Dockerfile", extra={"repo": repo, "base_image": base, "tarball": repo_tarball})

    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={source_url}",
        "RUN apt-get update -qq && apt-get install -y --no-install-recommends "
        "git ca-certificates && rm -rf /var/lib/apt/lists/*",
    ]

    if repo_tarball:
        lines.append("COPY repo.tar.gz /tmp/repo.tar.gz")
        lines.append("RUN mkdir -p /repo && cd /repo && tar xzf /tmp/repo.tar.gz")
    else:
        lines.append(_git_clone_or_archive(repo, base_commit))

    if spec and spec.system_dependencies:
        pkgs = " ".join(spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs} && "
            "rm -rf /var/lib/apt/lists/*"
        )

    if spec and spec.features:
        lines.append(f'ENV CARGO_TEST_FLAGS="{spec.features}"')

    lines.append("COPY test.patch /patches/test.patch")
    lines.append("COPY gold.patch /patches/gold.patch")
    return "\n".join(lines) + "\n"


def _rust_make_test_cmd(env_spec: AnyEnvironmentSpec) -> str:
    spec = env_spec if isinstance(env_spec, RustEnvironmentSpec) else None
    return (spec.test_cmd if spec and spec.test_cmd else None) or "cargo test"


def _rust_test_scope(test_patch: str) -> str:
    """Rust tests are typically run workspace-wide; return empty scope."""
    return ""


_CFG_TEST_MOD_RE = re.compile(
    r"#\[cfg\(test\)\]"
    r"(?:\s*(?:#\[[^\]]*\])\s*)*"  # optional attributes between #[cfg(test)] and mod
    r"\s+mod\s+(\w+)\s*\{",
    re.DOTALL,
)


def _rust_parse_test_regions(source: str) -> list[tuple[int, int]]:
    """Find ``#[cfg(test)] mod <name> { ... }`` regions in Rust source.

    Returns a list of ``(start_line, end_line)`` tuples using 1-indexed
    line numbers.  Uses regex to locate the opening pattern, then counts
    braces to find the matching ``}``.
    """
    regions: list[tuple[int, int]] = []
    for m in _CFG_TEST_MOD_RE.finditer(source):
        cfg_start = source.count("\n", 0, m.start()) + 1
        depth = 1
        i = m.end()
        while i < len(source) and depth > 0:
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        end_line = source.count("\n", 0, i) + 1
        regions.append((cfg_start, end_line))
    logger.debug(
        "test regions found: count=%d ranges=%s",
        len(regions),
        [(s, e) for s, e in regions],
    )
    return regions


def _rust_is_test_hunk(
    hunk: Any,
    test_regions: list[tuple[int, int]] | None = None,
) -> bool:
    """True if a diff hunk is inside a ``#[cfg(test)]`` / ``mod tests`` block.

    When *test_regions* is provided (from :func:`_rust_parse_test_regions`),
    classification is based on whether the hunk's source line numbers fall
    within a test region.  When *test_regions* is ``None`` the original
    content-based heuristic is used as a fallback.
    """
    if test_regions is not None:
        source_lines = [
            line.source_line_no
            for line in hunk
            if line.source_line_no is not None
        ]
        if not source_lines:
            return False
        in_test = sum(
            1
            for ln in source_lines
            if any(start <= ln <= end for start, end in test_regions)
        )
        if in_test == len(source_lines):
            return True
        return False

    # Fallback: content-based heuristic
    if hunk.section_header and "mod tests" in hunk.section_header:
        return True
    for line in hunk:
        if line.line_type in (" ", "+"):
            text = line.value
            if "#[cfg(test)]" in text or ("mod tests" in text and "{" in text):
                return True
    return False


# ---------------------------------------------------------------------------
# Register built-in backends
# ---------------------------------------------------------------------------

register_backend(LanguageBackend(
    name="go",
    test_file_pattern="_test.go",
    failure_grep='"Action":"fail"',
    default_timeout=600,
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

register_backend(LanguageBackend(
    name="rust",
    test_file_pattern=".rs",
    failure_grep="FAILED\\|error\\[E",
    default_timeout=600,
    parser=RustTestParser(),
    make_dockerfile=_rust_make_dockerfile,
    make_test_cmd=_rust_make_test_cmd,
    test_scope=_rust_test_scope,
    normalize_f2p=normalize_rust_f2p,
    is_test_hunk=_rust_is_test_hunk,
))
