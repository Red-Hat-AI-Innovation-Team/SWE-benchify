"""Agent-free Rust instance grader — importable compute_rust_f2p() API.

Mirrors the Go grader (swebenchify.grader) but for Rust repositories
validated with ``cargo test``.

Usage::

    from swebenchify.rust_grader import compute_rust_f2p

    result = compute_rust_f2p(
        repo, base_commit, test_patch, gold_patch,
        env_spec=spec,
    )
    print(result.FAIL_TO_PASS)
    print(result.status)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from swebenchify.models import RustEnvironmentSpec, ValidationResult
from swebenchify.parsers import RustTestParser, normalize_rust_f2p
from swebenchify.sandbox import RustDockerfile, RustImageCache

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

_DOCKER = os.environ.get("DOCKER_PATH", "docker")
_DEFAULT_IMAGE = "rust:latest"
_DEFAULT_TIMEOUT = 600

_F2P_PHASE_SEPARATOR = "===SWEBENCHIFY_PHASE_SEPARATOR==="


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    newline = text.find("\n", start)
    if newline != -1:
        start = newline + 1
    end = text.find(end_marker, start)
    if end == -1:
        return text[start:]
    return text[start:end]


def _compute_f2p_p2p(
    pre_parse: dict[str, str],
    post_parse: dict[str, str],
) -> tuple[list[str], list[str]]:
    pre_failed = {t for t, s in pre_parse.items() if s == "failed"}
    pre_passed = {t for t, s in pre_parse.items() if s == "passed"}
    post_passed = {t for t, s in post_parse.items() if s == "passed"}

    fail_to_pass = sorted(pre_failed & post_passed)
    pass_to_pass = sorted(pre_passed & post_passed)
    return fail_to_pass, pass_to_pass


# ---------------------------------------------------------------------------
# Dockerfile and run script generators
# ---------------------------------------------------------------------------

def _make_rust_dockerfile(
    rust_image: str,
    repo: str,
    base_commit: str,
    env_spec: RustEnvironmentSpec | None = None,
) -> str:
    if env_spec and env_spec.rust_version:
        base = f"rust:{env_spec.rust_version}-slim"
    else:
        base = rust_image

    lines = [
        f"FROM {base}",
        "RUN apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*",
        f"RUN git clone https://github.com/{repo}.git /repo && "
        f"cd /repo && git checkout {base_commit}",
    ]

    if env_spec and env_spec.system_dependencies:
        pkgs = " ".join(env_spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs} && "
            "rm -rf /var/lib/apt/lists/*"
        )

    if env_spec and env_spec.features:
        lines.append(f'ENV CARGO_TEST_FLAGS="{env_spec.features}"')

    lines.append("COPY test.patch /patches/test.patch")
    lines.append("COPY gold.patch /patches/gold.patch")
    return "\n".join(lines) + "\n"


def _make_rust_run_script(test_cmd: str, n_runs: int = 1) -> str:
    if not test_cmd:
        test_cmd = "cargo test"

    parts = ["set -e", "cd /repo"]

    for i in range(1, n_runs + 1):
        parts.append("git checkout -- . && git clean -fd -q")
        parts.append(
            "git apply /patches/test.patch "
            "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }"
        )
        parts.append(f"echo '{_F2P_PHASE_SEPARATOR}_RUN_{i}_PRE'")
        parts.append(f"{test_cmd} 2>&1 | tee /tmp/pre_out.txt || true")
        parts.append(
            "grep -q 'FAILED' /tmp/pre_out.txt || "
            "{ echo NO_FAILING_TESTS; exit 0; }"
        )
        parts.append(
            "git apply /patches/gold.patch "
            "2>&1 || { echo PATCH_APPLY_FAILED; exit 0; }"
        )
        parts.append(f"echo '{_F2P_PHASE_SEPARATOR}_RUN_{i}_POST'")
        parts.append(f"{test_cmd} 2>&1 || true")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------

def _parse_rust_f2p_output(
    raw_output: str,
    n_runs: int = 1,
) -> ValidationResult:
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

    parser = RustTestParser()
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

        per_run_f2p.append(set(normalize_rust_f2p(f2p_raw)))
        per_run_p2p.append(set(normalize_rust_f2p(p2p_raw)))

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_rust_f2p(
    repo: str,
    base_commit: str,
    test_patch: str,
    gold_patch: str,
    *,
    env_spec: RustEnvironmentSpec | None = None,
    docker_image: str = _DEFAULT_IMAGE,
    timeout: int = _DEFAULT_TIMEOUT,
    n_runs: int = 1,
) -> ValidationResult:
    """Compute FAIL_TO_PASS and PASS_TO_PASS for a Rust instance.

    Runs ``cargo test`` twice in a single Docker container — once with
    only the test patch applied (pre-fix), once with both the test and
    gold patches applied (post-fix) — then diffs the results.

    When ``n_runs > 1``, repeats the two-phase test execution N times
    within the same container and quarantines flaky tests.

    No Anthropic API key is required.
    """
    if not _docker_available():
        raise RuntimeError("Docker is not available — cannot run compute_rust_f2p()")

    has_rust_test = any(
        line.startswith("diff --git") and (".rs" in line)
        for line in test_patch.splitlines()
    )
    if not has_rust_test:
        logger.info(
            "compute_rust_f2p finished: repo=%s status=invalid f2p=0 p2p=0 elapsed=0.0s",
            repo,
        )
        return ValidationResult(
            status="invalid",
            error_message="test_patch contains no .rs files",
        )

    test_cmd = "cargo test"
    if env_spec and env_spec.test_cmd:
        test_cmd = env_spec.test_cmd

    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "test.patch").write_text(test_patch)
        (tmp / "gold.patch").write_text(gold_patch)

        build_tag = f"swebenchify-rust-f2p-{_short_hash(repo + base_commit)}"

        build_rc, build_log = _docker_build(
            tag=build_tag,
            context_dir=str(tmp),
            dockerfile=_make_rust_dockerfile(docker_image, repo, base_commit, env_spec),
        )

        if build_rc != 0:
            return ValidationResult(
                status="error",
                compiled=False,
                error_message=f"Docker build failed (rc={build_rc}): {build_log[-500:]}",
            )

        scaled_timeout = timeout * n_runs * 2
        run_rc, raw_output = _docker_run(
            image=build_tag,
            script=_make_rust_run_script(test_cmd, n_runs),
            timeout=scaled_timeout,
        )

        subprocess.run([_DOCKER, "rmi", build_tag], capture_output=True)

    elapsed = time.monotonic() - t0

    if run_rc == -1 and "TIMEOUT" in raw_output:
        return ValidationResult(
            status="error",
            error_message=f"Docker run timed out after {scaled_timeout}s",
        )

    result = _parse_rust_f2p_output(raw_output, n_runs)
    logger.info(
        "compute_rust_f2p finished: repo=%s status=%s f2p=%d p2p=%d elapsed=%.1fs",
        repo, result.status, len(result.FAIL_TO_PASS),
        len(result.PASS_TO_PASS), elapsed,
    )
    return result
