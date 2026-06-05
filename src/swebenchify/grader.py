"""Agent-free Go instance grader — importable grade() API.

Consumed by the RH-org evaluator (swe-routing-eval). Requires only
Docker; no Anthropic API key.

Usage::

    from swebenchify.grader import grade

    result = grade(instance, candidate_patch)
    if result.resolved:
        print("Resolved!")
    print(result.f2p)        # per-test outcomes for recorded F2P tests
    print(result.compiled)   # False if the patch didn't compile

The gold patch should always resolve an instance — that's the sanity
check. Any other patch may or may not.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swebenchify.parsers import GoJSONParser, normalize_go_f2p, normalize_go_test_id

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

_DOCKER = os.environ.get("DOCKER_PATH", "docker")
_DEFAULT_IMAGE = "golang:latest"
_DEFAULT_TIMEOUT = 300  # seconds per test run


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class GoTestResult:
    """Outcome of a single test from the grading run."""

    test_id: str
    status: str  # "passed" | "failed" | "skipped" | "error" | "missing"


@dataclass
class GradeResult:
    """Result of grading one candidate patch against one benchmark instance.

    Attributes:
        resolved: ``True`` iff every recorded FAIL_TO_PASS test now passes
            *and* every recorded PASS_TO_PASS test still passes.
        f2p: Per-test outcomes for the recorded FAIL_TO_PASS tests.
        p2p: Per-test outcomes for the recorded PASS_TO_PASS tests.
        compiled: ``False`` if the candidate patch caused a build failure.
            This is a distinct outcome — not the same as a test failure.
        telemetry: Timing, exit codes, raw output, and grader version.
    """

    resolved: bool
    f2p: list[GoTestResult] = field(default_factory=list)
    p2p: list[GoTestResult] = field(default_factory=list)
    compiled: bool = True
    telemetry: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade(
    instance: dict | Any,
    candidate_patch: str,
    *,
    docker_image: str = _DEFAULT_IMAGE,
    timeout: int = _DEFAULT_TIMEOUT,
) -> GradeResult:
    """Grade a candidate patch against a Go benchmark instance.

    Applies *candidate_patch* alongside the instance's canonical
    ``test_patch`` at ``base_commit``, runs ``go test -json``, and
    checks whether every recorded FAIL_TO_PASS test now passes and every
    PASS_TO_PASS test still passes.

    No Anthropic API key is required — the function runs Docker directly.

    Args:
        instance: A ``TaskInstance`` dataclass or a plain dict containing
            at minimum:

            - ``repo``         — ``"owner/repo"`` (GitHub)
            - ``base_commit``  — commit SHA to check out
            - ``test_patch``   — the canonical test patch (unified diff)
            - ``FAIL_TO_PASS`` — JSON-encoded or plain list of test IDs
            - ``PASS_TO_PASS`` — JSON-encoded or plain list of test IDs

        candidate_patch: Unified diff of the model's proposed fix.
        docker_image: Go Docker image (default: ``golang:latest``).
        timeout: Seconds to allow for the test run (default: 300).

    Returns:
        :class:`GradeResult` with resolved, f2p, p2p, compiled, telemetry.

    Raises:
        RuntimeError: If Docker is not available or the repo cannot be cloned.
    """
    # Normalise instance to dict regardless of whether it's a dataclass
    if not isinstance(instance, dict):
        try:
            from dataclasses import asdict
            inst = asdict(instance)
        except TypeError:
            inst = vars(instance)
    else:
        inst = instance

    repo = inst["repo"]
    base_commit = inst["base_commit"]
    test_patch = inst.get("test_patch") or ""
    candidate_patch = candidate_patch or ""

    # Decode recorded F2P/P2P (may be JSON-encoded strings or plain lists)
    recorded_f2p: list[str] = _decode_list(inst.get("FAIL_TO_PASS", "[]"))
    recorded_p2p: list[str] = _decode_list(inst.get("PASS_TO_PASS", "[]"))

    if not _docker_available():
        raise RuntimeError("Docker is not available — cannot run grade()")

    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "test.patch").write_text(test_patch)
        (tmp / "candidate.patch").write_text(candidate_patch)

        # Identify which packages the test_patch touches so we can scope
        # the test run (running ./... on kubernetes/kubernetes takes hours).
        # Returns (module_root, rel_pkg) pairs to handle multi-module repos.
        pkg_pairs = _affected_packages(test_patch) or [(".", "./...")]
        pkg_scope = " ".join(
            f"{r}:{p}" if r != "." else p for r, p in pkg_pairs
        )  # human-readable for telemetry only

        build_tag = f"swebenchify-grade-{_short_hash(repo + base_commit)}"

        # --- Build Docker image (clone + checkout baked in) ---
        build_start = time.monotonic()
        build_rc, build_log = _docker_build(
            tag=build_tag,
            context_dir=str(tmp),
            dockerfile=_make_dockerfile(docker_image, repo, base_commit),
        )
        build_elapsed = time.monotonic() - build_start

        if build_rc != 0:
            elapsed = time.monotonic() - t0
            return GradeResult(
                resolved=False,
                compiled=False,
                telemetry={
                    "grader_version": __version__,
                    "elapsed_s": round(elapsed, 2),
                    "build_rc": build_rc,
                    "build_log": build_log[-2000:],
                    "error": "docker build failed",
                },
            )

        # --- Run: apply test_patch + candidate_patch, then go test -json ---
        run_start = time.monotonic()
        run_rc, raw_output = _docker_run(
            image=build_tag,
            script=_make_run_script(pkg_pairs),
            timeout=timeout,
        )
        run_elapsed = time.monotonic() - run_start

        # Clean up image
        subprocess.run([_DOCKER, "rmi", build_tag], capture_output=True)

    total_elapsed = time.monotonic() - t0

    # --- Parse output ---
    parser = GoJSONParser()
    parse_result = parser.parse(raw_output)
    compiled = parse_result["compiled"]
    actual_tests = parse_result["tests"]  # test_id -> status (full qualified)

    # Build a lookup: normalised bare name -> actual status
    # (handles package-prefix and subtest suffix differences)
    normalised_lookup: dict[str, str] = {}
    for full_id, status in actual_tests.items():
        bare = normalize_go_test_id(full_id)
        # In case of collisions (subtests), "failed" takes priority
        if bare not in normalised_lookup or status == "failed":
            normalised_lookup[bare] = status

    # --- Evaluate F2P and P2P ---
    f2p_results: list[GoTestResult] = []
    for test_id in recorded_f2p:
        bare = normalize_go_test_id(test_id)
        actual = normalised_lookup.get(bare, "missing")
        f2p_results.append(GoTestResult(test_id=test_id, status=actual))

    p2p_results: list[GoTestResult] = []
    for test_id in recorded_p2p:
        bare = normalize_go_test_id(test_id)
        actual = normalised_lookup.get(bare, "missing")
        p2p_results.append(GoTestResult(test_id=test_id, status=actual))

    # Resolved iff: compiled AND all F2P now pass AND all P2P still pass
    f2p_all_pass = all(r.status == "passed" for r in f2p_results)
    p2p_all_pass = all(r.status == "passed" for r in p2p_results)
    resolved = compiled and f2p_all_pass and p2p_all_pass

    return GradeResult(
        resolved=resolved,
        f2p=f2p_results,
        p2p=p2p_results,
        compiled=compiled,
        telemetry={
            "grader_version": __version__,
            "elapsed_s": round(total_elapsed, 2),
            "build_elapsed_s": round(build_elapsed, 2),
            "run_elapsed_s": round(run_elapsed, 2),
            "run_rc": run_rc,
            "pkg_scope": pkg_scope,
            "docker_image": docker_image,
            "raw_output_lines": raw_output.count("\n"),
            "f2p_pass": f2p_all_pass,
            "p2p_pass": p2p_all_pass,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_list(value: str | list | None) -> list[str]:
    """Accept JSON string or plain list; always return list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _short_hash(text: str, length: int = 12) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def _docker_available() -> bool:
    try:
        r = subprocess.run([_DOCKER, "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _docker_build(tag: str, context_dir: str, dockerfile: str) -> tuple[int, str]:
    Path(context_dir, "Dockerfile").write_text(dockerfile)
    r = subprocess.run(
        [_DOCKER, "build", "-t", tag, context_dir],
        capture_output=True,
        text=True,
        timeout=900,
    )
    return r.returncode, r.stdout + r.stderr


def _docker_run(image: str, script: str, timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(
            [_DOCKER, "run", "--rm", "--network", "host", image, "sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"


def _make_dockerfile(go_image: str, repo: str, base_commit: str) -> str:
    return (
        f"FROM {go_image}\n"
        f"RUN git clone https://github.com/{repo}.git /repo && "
        f"cd /repo && git checkout {base_commit}\n"
        "COPY test.patch /patches/test.patch\n"
        "COPY candidate.patch /patches/candidate.patch\n"
    )


def _make_run_script(pkg_pairs: list[tuple[str, str]]) -> str:
    """Build the shell script that applies patches and runs scoped tests.

    For sub-module repos (e.g. etcd's ``server/`` directory has its own
    ``go.mod``), each pair is ``(module_root, rel_pkg)`` and the test must
    run from the sub-module directory, not the repo root.
    """
    test_cmds: list[str] = []
    for module_root, rel_pkg in pkg_pairs:
        # Always use /... to include sub-packages (e.g. etcdhttp/types alongside etcdhttp)
        scope = rel_pkg if rel_pkg.endswith("...") else f"{rel_pkg}/..."
        if module_root == ".":
            test_cmds.append(f"go test -json -count=1 {scope} 2>&1 || true")
        else:
            # cd into the sub-module so Go picks up the right go.mod
            test_cmds.append(
                f"(cd /repo/{module_root} && go test -json -count=1 {scope} 2>&1) || true"
            )
    test_body = "\n".join(test_cmds) if test_cmds else "go test -json -count=1 ./... 2>&1 || true"
    return (
        "set -e\n"
        "cd /repo\n"
        "git apply /patches/test.patch /patches/candidate.patch "
        "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }\n"
        f"{test_body}\n"
    )


def _affected_packages(test_patch: str) -> list[tuple[str, str]]:
    """Return ``(module_root, rel_pkg)`` pairs for packages touched by the test_patch.

    ``module_root`` is ``"."`` for the main module or the top-level directory
    name for a sub-module (e.g. ``"server"`` for etcd's ``server/`` sub-module).
    ``rel_pkg`` is the ``./``-prefixed relative package path within that module.

    Handles etcd-style multi-module repos where a top-level directory such as
    ``server/`` owns its own ``go.mod`` — those packages must be tested with
    ``cd /repo/server && go test ./etcdserver/api/...`` not from the repo root.
    """
    seen: dict[str, set[str]] = {}  # module_root -> {rel_pkg}
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        path_parts = Path(path).parts
        if not path_parts:
            continue
        top = path_parts[0]
        if len(path_parts) > 2:
            # e.g. server/etcdserver/api/etcdhttp/health_test.go
            # module_root=server, rel_pkg=./etcdserver/api/etcdhttp
            inner = str(Path(*path_parts[1:-1]))
            rel_pkg = f"./{inner}"
        elif len(path_parts) == 2:
            # e.g. server/main.go → test in root of that module
            rel_pkg = "./..."
        else:
            # File at repo root → main module, test ./...
            top = "."
            rel_pkg = "./..."

        seen.setdefault(top, set()).add(rel_pkg)

    result: list[tuple[str, str]] = []
    for root in sorted(seen):
        for pkg in sorted(seen[root]):
            result.append((root, pkg))
    return result
