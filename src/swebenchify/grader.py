"""Language-aware instance grader — importable grade() API.

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
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swebenchify.backends import get_backend
from swebenchify.models import AnyEnvironmentSpec, EnvironmentSpec, GoEnvironmentSpec, ValidationResult
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
    env_spec: EnvironmentSpec | None = None,
) -> GradeResult:
    """Grade a candidate patch against a benchmark instance.

    Applies *candidate_patch* alongside the instance's canonical
    ``test_patch`` at ``base_commit``, runs the language-appropriate
    test command, and checks whether every recorded FAIL_TO_PASS test
    now passes and every PASS_TO_PASS test still passes.

    Language is detected from ``instance["repo_language"]`` (default: Go).

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
        docker_image: Docker image override (default: language-specific).
        timeout: Seconds to allow for the test run (default: 300).

    Returns:
        :class:`GradeResult` with resolved, f2p, p2p, compiled, telemetry.

    Raises:
        RuntimeError: If Docker is not available or the repo cannot be cloned.
    """
    if not isinstance(instance, dict):
        try:
            from dataclasses import asdict
            inst = asdict(instance)
        except TypeError:
            inst = vars(instance)
    else:
        inst = instance

    language = inst.get("repo_language", "go")
    backend = get_backend(language)

    if backend and language != "go":
        return _grade_generic(inst, candidate_patch, backend,
                              docker_image=docker_image, timeout=timeout,
                              env_spec=env_spec)

    return _grade_go(inst, candidate_patch,
                     docker_image=docker_image, timeout=timeout)


def _grade_go(
    inst: dict,
    candidate_patch: str,
    *,
    docker_image: str = _DEFAULT_IMAGE,
    timeout: int = _DEFAULT_TIMEOUT,
) -> GradeResult:
    """Go-specific grading path (original implementation)."""
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    test_patch = inst.get("test_patch") or ""
    candidate_patch = candidate_patch or ""

    recorded_f2p: list[str] = _decode_list(inst.get("FAIL_TO_PASS", "[]"))
    recorded_p2p: list[str] = _decode_list(inst.get("PASS_TO_PASS", "[]"))

    if not _docker_available():
        raise RuntimeError("Docker is not available — cannot run grade()")

    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "test.patch").write_text(test_patch)
        (tmp / "candidate.patch").write_text(candidate_patch)

        pkg_scope = " ".join(_affected_packages(test_patch)) or "./..."
        build_tag = f"swebenchify-grade-{_short_hash(repo + base_commit)}"

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

        run_start = time.monotonic()
        run_rc, raw_output = _docker_run(
            image=build_tag,
            script=_make_run_script(pkg_scope),
            timeout=timeout,
        )
        run_elapsed = time.monotonic() - run_start

        subprocess.run([_DOCKER, "rmi", build_tag], capture_output=True)

    total_elapsed = time.monotonic() - t0

    parser = GoJSONParser()
    parse_result = parser.parse(raw_output)
    compiled = parse_result["compiled"]
    actual_tests = parse_result["tests"]

    normalised_lookup: dict[str, str] = {}
    for full_id, status in actual_tests.items():
        bare = normalize_go_test_id(full_id)
        if bare not in normalised_lookup or status == "failed":
            normalised_lookup[bare] = status

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


def _grade_generic(
    inst: dict,
    candidate_patch: str,
    backend: Any,
    *,
    docker_image: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    env_spec: EnvironmentSpec | None = None,
) -> GradeResult:
    """Language-generic grading via the backend registry."""
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    test_patch = inst.get("test_patch") or ""
    candidate_patch = candidate_patch or ""

    recorded_f2p: list[str] = _decode_list(inst.get("FAIL_TO_PASS", "[]"))
    recorded_p2p: list[str] = _decode_list(inst.get("PASS_TO_PASS", "[]"))

    if not _docker_available():
        raise RuntimeError("Docker is not available — cannot run grade()")

    if env_spec is None:
        env_spec = EnvironmentSpec(
            language=backend.name,
            language_version="3.11",
            package_manager="pip",
            install_cmd="pip install -e .",
            test_cmd="pytest",
            pre_install=[],
            pip_packages=[],
            system_dependencies=[],
        )

    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "test.patch").write_text(test_patch)
        (tmp / "candidate.patch").write_text(candidate_patch)

        test_scope = backend.test_scope(test_patch)
        test_cmd = backend.make_test_cmd(env_spec)
        build_tag = f"swebenchify-grade-{_short_hash(repo + base_commit)}"

        build_start = time.monotonic()
        dockerfile = backend.make_dockerfile(repo, base_commit, env_spec)
        dockerfile = dockerfile.replace(
            "COPY gold.patch /patches/gold.patch",
            "COPY candidate.patch /patches/candidate.patch",
        )
        build_rc, build_log = _docker_build(
            tag=build_tag,
            context_dir=str(tmp),
            dockerfile=dockerfile,
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

        run_script = _make_grade_run_script(test_cmd, test_scope)
        run_start = time.monotonic()
        run_rc, raw_output = _docker_run(
            image=build_tag,
            script=run_script,
            timeout=timeout,
        )
        run_elapsed = time.monotonic() - run_start

        subprocess.run([_DOCKER, "rmi", build_tag], capture_output=True)

    total_elapsed = time.monotonic() - t0

    parse_result = backend.parser.parse(raw_output)
    compiled = parse_result["compiled"]
    actual_tests = parse_result["tests"]

    f2p_results: list[GoTestResult] = []
    for test_id in recorded_f2p:
        actual = actual_tests.get(test_id, "missing")
        f2p_results.append(GoTestResult(test_id=test_id, status=actual))

    p2p_results: list[GoTestResult] = []
    for test_id in recorded_p2p:
        actual = actual_tests.get(test_id, "missing")
        p2p_results.append(GoTestResult(test_id=test_id, status=actual))

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
            "test_scope": test_scope,
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
        f"cd /repo && (git checkout {base_commit} || "
        f"(git fetch origin {base_commit} && git checkout {base_commit}))\n"
        "COPY test.patch /patches/test.patch\n"
        "COPY candidate.patch /patches/candidate.patch\n"
    )


def _make_run_script(pkg_scope: str) -> str:
    return (
        "set -e\n"
        "cd /repo\n"
        "git apply /patches/test.patch /patches/candidate.patch "
        "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }\n"
        f"go test -json -count=1 {pkg_scope} 2>&1 || true\n"
    )


def _make_grade_run_script(test_cmd: str, test_scope: str) -> str:
    """Generate a run script for grading: apply candidate+test patches, run tests."""
    return (
        "set -e\n"
        "cd /repo\n"
        "git apply /patches/test.patch /patches/candidate.patch "
        "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }\n"
        f"{test_cmd} {test_scope} 2>&1 || true\n"
    )


_F2P_PHASE_SEPARATOR = "===SWEBENCHIFY_PHASE_SEPARATOR==="


def _compute_f2p_p2p(
    pre_parse: dict[str, str],
    post_parse: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Compute FAIL_TO_PASS and PASS_TO_PASS from pre/post test results.

    Returns ``(FAIL_TO_PASS, PASS_TO_PASS)`` lists, both sorted.
    """
    pre_failed = {t for t, s in pre_parse.items() if s == "failed"}
    pre_passed = {t for t, s in pre_parse.items() if s == "passed"}
    post_passed = {t for t, s in post_parse.items() if s == "passed"}

    fail_to_pass = sorted(pre_failed & post_passed)
    pass_to_pass = sorted(pre_passed & post_passed)
    return fail_to_pass, pass_to_pass


def _make_f2p_run_script_generic(
    test_cmd: str,
    test_scope: str,
    failure_grep: str,
    n_runs: int = 1,
    reinstall_cmd: str | None = None,
    run_preamble: str = "",
) -> str:
    """Generate a two-phase run script parameterized by language."""
    parts = ["set -e"]

    if run_preamble:
        parts.append(run_preamble)

    parts.append("cd /repo")

    for i in range(1, n_runs + 1):
        parts.append("git checkout -- . && git clean -fd -q")
        if reinstall_cmd:
            parts.append(f"{reinstall_cmd} 2>&1 || true")
        parts.append(
            "git apply /patches/test.patch "
            "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }"
        )
        parts.append(f"echo '{_F2P_PHASE_SEPARATOR}_RUN_{i}_PRE'")
        parts.append(f"{test_cmd} {test_scope} 2>&1 | tee /tmp/pre_out.txt || true")
        parts.append(
            f'grep -q \'{failure_grep}\' /tmp/pre_out.txt || '
            "{ echo NO_FAILING_TESTS; exit 0; }"
        )
        parts.append(
            "git apply /patches/gold.patch "
            "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }"
        )
        parts.append(f"echo '{_F2P_PHASE_SEPARATOR}_RUN_{i}_POST'")
        parts.append(f"{test_cmd} {test_scope} 2>&1 || true")

    return "\n".join(parts) + "\n"


def _parse_f2p_output_generic(
    raw_output: str,
    parser: Any,
    normalize: Any,
    n_runs: int = 1,
) -> ValidationResult:
    """Parse two-phase Docker output into a ValidationResult."""
    if "PATCH_APPLY_FAILED" in raw_output:
        return ValidationResult(
            status="error",
            error_message="Patch apply failed",
        )

    if "NO_FAILING_TESTS" in raw_output:
        return ValidationResult(
            status="invalid",
            error_message="No tests failed in pre-fix run",
        )

    per_run_f2p: list[set[str]] = []
    per_run_p2p: list[set[str]] = []
    first_compiled = True

    for i in range(1, n_runs + 1):
        pre_marker = f"{_F2P_PHASE_SEPARATOR}_RUN_{i}_PRE"
        post_marker = f"{_F2P_PHASE_SEPARATOR}_RUN_{i}_POST"

        pre_section = _extract_section(raw_output, pre_marker, post_marker)
        next_pre = f"{_F2P_PHASE_SEPARATOR}_RUN_{i + 1}_PRE"
        post_section = _extract_section(raw_output, post_marker, next_pre)

        pre_result = parser.parse(pre_section)
        post_result = parser.parse(post_section)

        if not pre_result["compiled"]:
            first_compiled = False

        f2p_raw, p2p_raw = _compute_f2p_p2p(
            pre_result["tests"], post_result["tests"]
        )

        per_run_f2p.append(set(normalize(f2p_raw)))
        per_run_p2p.append(set(normalize(p2p_raw)))

    if n_runs == 1:
        f2p = sorted(per_run_f2p[0])
        p2p = sorted(per_run_p2p[0])
        status = "valid" if f2p else "invalid"
        return ValidationResult(
            status=status,
            FAIL_TO_PASS=f2p,
            PASS_TO_PASS=p2p,
            compiled=first_compiled,
        )

    # Multi-run quarantine
    f2p_union = per_run_f2p[0].copy()
    stable_f2p = per_run_f2p[0].copy()
    for run_set in per_run_f2p[1:]:
        f2p_union |= run_set
        stable_f2p &= run_set

    f2p = sorted(stable_f2p)
    quarantined = sorted(f2p_union - stable_f2p)

    stable_p2p = per_run_p2p[0].copy()
    for run_set in per_run_p2p[1:]:
        stable_p2p &= run_set
    p2p = sorted(stable_p2p)

    if not f2p:
        return ValidationResult(
            status="invalid",
            FAIL_TO_PASS=[],
            PASS_TO_PASS=p2p,
            compiled=first_compiled,
            n_runs=n_runs,
            flake_count=len(quarantined),
            quarantined_tests=quarantined,
            error_message="All F2P tests quarantined as flaky" if quarantined else None,
        )

    return ValidationResult(
        status="valid",
        FAIL_TO_PASS=f2p,
        PASS_TO_PASS=p2p,
        compiled=first_compiled,
        n_runs=n_runs,
        flake_count=len(quarantined),
        quarantined_tests=quarantined,
    )


def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
    """Extract text between two markers. Returns empty string if not found."""
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    # Skip the marker line itself
    newline = text.find("\n", start)
    if newline != -1:
        start = newline + 1

    end = text.find(end_marker, start)
    if end == -1:
        return text[start:]
    return text[start:end]


# ---------------------------------------------------------------------------
# Go-specific wrappers (backward compat for tests and grade() path)
# ---------------------------------------------------------------------------

def _make_f2p_run_script(pkg_scope: str, n_runs: int = 1) -> str:
    """Go-specific F2P run script — delegates to generic version."""
    return _make_f2p_run_script_generic(
        test_cmd="go test -json -count=1",
        test_scope=pkg_scope,
        failure_grep='"Action":"fail"',
        n_runs=n_runs,
    )


def _parse_f2p_output(raw_output: str, n_runs: int = 1) -> ValidationResult:
    """Go-specific F2P output parser — delegates to generic version."""
    return _parse_f2p_output_generic(
        raw_output=raw_output,
        parser=GoJSONParser(),
        normalize=normalize_go_f2p,
        n_runs=n_runs,
    )


# ---------------------------------------------------------------------------
# Generic compute_f2p — dispatches via backend registry
# ---------------------------------------------------------------------------

def compute_f2p(
    repo: str,
    base_commit: str,
    test_patch: str,
    gold_patch: str,
    *,
    env_spec: AnyEnvironmentSpec | None = None,
    docker_image: str = _DEFAULT_IMAGE,
    timeout: int | None = None,
    n_runs: int = 1,
) -> ValidationResult:
    """Compute FAIL_TO_PASS and PASS_TO_PASS via Docker-based validation.

    Builds a Docker container, runs tests twice (pre-fix and post-fix),
    and diffs the results. Language-specific behavior is dispatched
    through the backend registry.

    When ``env_spec`` is ``None``, defaults to Go for backward compatibility.
    """
    if not _docker_available():
        raise RuntimeError("Docker is not available — cannot run compute_f2p()")

    language = env_spec.language if env_spec else "go"
    backend = get_backend(language)
    if not backend:
        return ValidationResult(
            status="error",
            error_message=f"No backend registered for language: {language}",
        )

    if timeout is None:
        timeout = backend.default_timeout

    has_test_file = any(
        backend.test_file_pattern in line
        for line in test_patch.splitlines()
        if line.startswith("diff --git")
    )
    if not has_test_file:
        logger.info(
            "compute_f2p finished: repo=%s status=invalid f2p=0 p2p=0 elapsed=0.0s",
            repo,
        )
        return ValidationResult(
            status="invalid",
            error_message=f"test_patch contains no {backend.test_file_pattern} files",
        )

    t0 = time.monotonic()
    fallback_spec = env_spec or GoEnvironmentSpec()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "test.patch").write_text(test_patch)
        (tmp / "gold.patch").write_text(gold_patch)

        test_scope = backend.test_scope(test_patch)
        test_cmd = backend.make_test_cmd(fallback_spec)
        build_tag = f"swebenchify-f2p-{_short_hash(repo + base_commit)}"

        build_rc, build_log = _docker_build(
            tag=build_tag,
            context_dir=str(tmp),
            dockerfile=backend.make_dockerfile(repo, base_commit, fallback_spec),
        )

        if build_rc != 0:
            return ValidationResult(
                status="error",
                compiled=False,
                error_message=f"Docker build failed (rc={build_rc}): {build_log[-2000:]}",
            )

        reinstall_cmd = None
        if isinstance(fallback_spec, EnvironmentSpec) and fallback_spec.install_cmd:
            reinstall_cmd = fallback_spec.install_cmd

        run_preamble = ""
        if isinstance(fallback_spec, EnvironmentSpec):
            run_preamble = fallback_spec.run_preamble

        scaled_timeout = timeout * n_runs * 2
        run_rc, raw_output = _docker_run(
            image=build_tag,
            script=_make_f2p_run_script_generic(
                test_cmd=test_cmd,
                test_scope=test_scope,
                failure_grep=backend.failure_grep,
                n_runs=n_runs,
                reinstall_cmd=reinstall_cmd,
                run_preamble=run_preamble,
            ),
            timeout=scaled_timeout,
        )

        subprocess.run([_DOCKER, "rmi", build_tag], capture_output=True)

    elapsed = time.monotonic() - t0

    if run_rc == -1 and "TIMEOUT" in raw_output:
        return ValidationResult(
            status="error",
            error_message=f"Docker run timed out after {scaled_timeout}s",
        )

    result = _parse_f2p_output_generic(
        raw_output=raw_output,
        parser=backend.parser,
        normalize=backend.normalize_f2p,
        n_runs=n_runs,
    )
    logger.info(
        "compute_f2p finished: repo=%s status=%s f2p=%d p2p=%d elapsed=%.1fs",
        repo, result.status, len(result.FAIL_TO_PASS),
        len(result.PASS_TO_PASS), elapsed,
    )
    return result


def _affected_packages(test_patch: str) -> list[str]:
    """Return relative package paths touched by the test_patch.

    Handles etcd-style multi-module repos by detecting sub-module roots
    (top-level directories that own their own go.mod).
    """
    seen: dict[str, list[str]] = {}  # module_root -> [pkg_paths]
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
            # Sub-module: prefix with the module root directory
            for pkg in pkgs:
                cmds.append(f"./{root}/{pkg.lstrip('./')}")
    return cmds or ["./..."]


def compute_f2p_python(
    repo: str,
    base_commit: str,
    test_patch: str,
    gold_patch: str,
    *,
    env_spec: EnvironmentSpec,
    timeout: int = 600,
    n_runs: int = 1,
) -> ValidationResult:
    """Backward-compatible alias — delegates to generic compute_f2p()."""
    return compute_f2p(
        repo=repo,
        base_commit=base_commit,
        test_patch=test_patch,
        gold_patch=gold_patch,
        env_spec=env_spec,
        timeout=timeout,
        n_runs=n_runs,
    )
