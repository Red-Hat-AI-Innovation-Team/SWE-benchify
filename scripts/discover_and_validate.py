#!/usr/bin/env python3
"""Unified pipeline: collect PRs, extract candidates, validate, emit instances.

Runs the full SWE-benchify pipeline for any supported language (Python, Java,
Rust). Language-specific behavior (env detection, test filtering, patch
refinement) is dispatched via a registry.

Usage::

    python scripts/discover_and_validate.py --language python \
        --repo pallets/flask --max-prs 300

    python scripts/discover_and_validate.py --language java \
        --repo apache/commons-lang --max-prs 500

    python scripts/discover_and_validate.py --language rust \
        --repo cloudflare/pingora --max-prs 200

    # With env spec overrides:
    python scripts/discover_and_validate.py --language python \
        --repo ansible/awx --lang-version 3.11 \
        --pre-install "pip install -r requirements/requirements.txt"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from swebenchify.backends import get_backend, refine_patch_split
from swebenchify.collector import collect_prs, save_prs
from swebenchify.extractor import extract_all, save_candidates
from swebenchify.grader import compute_f2p
from swebenchify.models import (
    CandidateInstance,
    EnvironmentSpec,
    RustEnvironmentSpec,
    Repository,
    ValidationResult,
    compute_java_env_spec_hash,
    compute_python_env_spec_hash,
    compute_rust_env_spec_hash,
)
from swebenchify.remote import build_task_instances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language-specific env detection
# ---------------------------------------------------------------------------

def _detect_python(repo: str, root: Path) -> dict:
    detected: dict = {}
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        m = re.search(r'requires-python\s*=\s*["\']>=?\s*(\d+\.\d+)', content)
        if m:
            detected["python_version"] = m.group(1)

    setup_cfg = root / "setup.cfg"
    if setup_cfg.exists():
        content = setup_cfg.read_text()
        m = re.search(r'python_requires\s*=\s*>=?\s*(\d+\.\d+)', content)
        if m and "python_version" not in detected:
            detected["python_version"] = m.group(1)

    pre_install: list[str] = []
    for req_file in [
        "requirements.txt", "test-requirements.txt",
        "requirements-test.txt", "requirements-dev.txt",
    ]:
        if (root / req_file).exists():
            pre_install.append(f"pip install -r {req_file}")
    if pre_install:
        detected["pre_install"] = pre_install
    return detected


def _detect_java(repo: str, root: Path) -> dict:
    detected: dict = {}
    pom = root / "pom.xml"
    if not pom.exists():
        return detected
    content = pom.read_text()

    for pattern in [
        r"<maven\.compiler\.release>\s*(\d+)\s*</maven\.compiler\.release>",
        r"<maven\.compiler\.source>\s*([\d.]+)\s*</maven\.compiler\.source>",
        r"<java\.version>\s*([\d.]+)\s*</java\.version>",
    ]:
        if "java_version" not in detected:
            m = re.search(pattern, content)
            if m:
                ver = m.group(1)
                if ver.startswith("1."):
                    ver = ver[2:]
                detected["java_version"] = ver
    return detected


def _detect_rust(repo: str, root: Path) -> dict:
    detected: dict = {}
    for toolchain_file in ["rust-toolchain.toml", "rust-toolchain"]:
        tc_path = root / toolchain_file
        if tc_path.exists():
            content = tc_path.read_text()
            m = re.search(r'channel\s*=\s*"(\d+\.\d+(?:\.\d+)?)"', content)
            if m:
                detected["rust_version"] = m.group(1)
                break
            m = re.search(r'^(\d+\.\d+(?:\.\d+)?)', content.strip())
            if m:
                detected["rust_version"] = m.group(1)
                break

    cargo_toml = root / "Cargo.toml"
    if cargo_toml.exists():
        content = cargo_toml.read_text()
        if "[workspace]" in content:
            detected["workspace_mode"] = "workspace"
            m = re.search(r'members\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if m:
                members = re.findall(r'"([^"]+)"', m.group(1))
                if members:
                    detected["workspace_members"] = members
        m = re.search(r'edition\s*=\s*"(\d+)"', content)
        if m:
            detected["edition"] = m.group(1)
        m = re.search(r'rust-version\s*=\s*"(\d+\.\d+(?:\.\d+)?)"', content)
        if m and "rust_version" not in detected:
            detected["rust_version"] = m.group(1)
    return detected


_DETECTORS = {
    "python": _detect_python,
    "java": _detect_java,
    "rust": _detect_rust,
}


def detect_env(language: str, repo: str, token: str | None) -> dict:
    """Clone repo shallowly and run language-specific env detection."""
    detector = _DETECTORS.get(language)
    if not detector:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["git", "clone", "--depth=1", f"https://github.com/{repo}.git", tmp],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.warning("Failed to clone %s for env detection: %s",
                           repo, result.stderr[:200])
            return {}
        return detector(repo, Path(tmp))


# ---------------------------------------------------------------------------
# Env spec construction
# ---------------------------------------------------------------------------

def _clamp_python_version(version: str) -> str:
    try:
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        if major < 3 or (major == 3 and minor < 9):
            return "3.11"
    except (ValueError, IndexError):
        return "3.11"
    return version


def build_env_spec(
    language: str, args: argparse.Namespace, repo: str, token: str | None,
) -> EnvironmentSpec | RustEnvironmentSpec:
    auto = detect_env(language, repo, token) if not args.skip_detection else {}

    pre_install: list[str] = []
    if args.pre_install:
        pre_install = [cmd.strip() for cmd in args.pre_install.split(";") if cmd.strip()]

    system_deps: list[str] = []
    if args.system_deps:
        system_deps = [d.strip() for d in args.system_deps.split(",") if d.strip()]

    if language == "python":
        if not pre_install and "pre_install" in auto:
            pre_install = auto["pre_install"]
        detected_ver = args.lang_version or auto.get("python_version", "3.11")
        python_version = _clamp_python_version(detected_ver)
        if python_version != detected_ver:
            logger.warning("Clamped Python version %s -> %s", detected_ver, python_version)
        spec = EnvironmentSpec(
            language="python",
            language_version=python_version,
            package_manager="pip",
            install_cmd=args.install_cmd or "pip install -e .",
            test_cmd=args.test_cmd or "pytest",
            pre_install=pre_install,
            pip_packages=[],
            system_dependencies=system_deps,
            base_image=args.base_image or "",
            run_preamble=args.run_preamble or "",
        )
        spec.env_spec_hash = compute_python_env_spec_hash(spec)
        return spec

    if language == "java":
        if not pre_install:
            pre_install = ["mvn dependency:resolve -q -B"]
        spec = EnvironmentSpec(
            language="java",
            language_version=str(args.lang_version or auto.get("java_version", "8")),
            package_manager="maven",
            install_cmd="",
            test_cmd=args.test_cmd or "mvn test -B",
            pre_install=pre_install,
            pip_packages=[],
            system_dependencies=system_deps,
            base_image="",
            run_preamble="",
        )
        spec.env_spec_hash = compute_java_env_spec_hash(spec)
        return spec

    if language == "rust":
        workspace_members: list[str] = []
        if isinstance(auto.get("workspace_members"), list):
            workspace_members = auto["workspace_members"]
        rust_spec = RustEnvironmentSpec(
            rust_version=args.lang_version or str(auto.get("rust_version", "")),
            build_cmd=args.build_cmd or "",
            test_cmd=args.test_cmd or "cargo test",
            workspace_mode=str(auto.get("workspace_mode", "single")),
            workspace_members=workspace_members,
            edition=str(auto.get("edition", "")),
            features=args.features or "",
            system_dependencies=system_deps,
        )
        rust_spec.env_spec_hash = compute_rust_env_spec_hash(rust_spec)
        return rust_spec

    raise ValueError(f"Unsupported language: {language}")


# ---------------------------------------------------------------------------
# Test filtering
# ---------------------------------------------------------------------------

def has_tests(language: str, test_patch: str) -> bool:
    backend = get_backend(language)
    if backend:
        return bool(backend.test_scope(test_patch))
    if language == "rust":
        return any(
            line.startswith("diff --git") and ".rs" in line
            for line in test_patch.splitlines()
        )
    return bool(test_patch)


# ---------------------------------------------------------------------------
# Defaults per language
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "python": {"max_prs": 300, "timeout": 600},
    "java": {"max_prs": 500, "timeout": 900},
    "rust": {"max_prs": 500, "timeout": 600},
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full SWE-benchify pipeline for a GitHub repo.",
    )
    parser.add_argument("--language", required=True,
                        choices=["python", "java", "rust"],
                        help="Target language")
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: output/{repo_slug}/)")
    parser.add_argument("--max-prs", type=int, default=None,
                        help="Max PRs to scan (default: language-dependent)")
    parser.add_argument("--pr-after", default=None,
                        help="Only PRs created after this date (ISO 8601)")
    parser.add_argument("--pr-before", default=None,
                        help="Only PRs created before this date (ISO 8601)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout per validation phase in seconds")
    parser.add_argument("--n-runs", type=int, default=1,
                        help="Number of validation runs for flake detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and extract only, skip validation")
    parser.add_argument("--skip-valid", action="store_true",
                        help="Skip candidates already in the task-instances output")

    env_group = parser.add_argument_group("environment spec overrides")
    env_group.add_argument("--lang-version", default=None,
                           help="Language/toolchain version (e.g. 3.11, 17, 1.84)")
    env_group.add_argument("--install-cmd", default=None,
                           help="Install command")
    env_group.add_argument("--test-cmd", default=None,
                           help="Test command")
    env_group.add_argument("--pre-install", default=None,
                           help="Semicolon-separated pre-install commands")
    env_group.add_argument("--system-deps", default=None,
                           help="Comma-separated system packages to install")
    env_group.add_argument("--skip-detection", action="store_true",
                           help="Skip auto-detection, use defaults + overrides only")

    py_group = parser.add_argument_group("python-specific options")
    py_group.add_argument("--base-image", default=None,
                          help="Custom Docker base image (python only)")
    py_group.add_argument("--run-preamble", default=None,
                          help="Shell commands to run before tests (python only)")

    rust_group = parser.add_argument_group("rust-specific options")
    rust_group.add_argument("--build-cmd", default=None,
                            help="Build command (rust only)")
    rust_group.add_argument("--features", default=None,
                            help="Cargo feature flags (rust only)")

    issue_group = parser.add_argument_group("issue tracking")
    issue_group.add_argument("--jira-projects", default=None,
                             help="Comma-separated Jira project keys (java only)")

    args = parser.parse_args(argv)
    language = args.language

    defaults = _DEFAULTS.get(language, {})
    max_prs = args.max_prs or defaults.get("max_prs", 300)
    timeout = args.timeout or defaults.get("timeout", 600)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("error: GITHUB_TOKEN environment variable required", file=sys.stderr)
        return 2

    repo_slug = args.repo.replace("/", "__")
    output_dir = args.output or Path("output") / repo_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    prs_path = output_dir / f"{repo_slug}-prs.jsonl"
    candidates_path = output_dir / f"{repo_slug}-candidates.jsonl"
    instances_path = output_dir / f"{repo_slug}-task-instances.jsonl"

    # --- Stage 1: Collect PRs ---
    logger.info("Stage 1: Collecting PRs from %s (max=%s)...", args.repo, max_prs)
    repo_obj = Repository(full_name=args.repo, access_token=token)

    jira_projects = None
    if args.jira_projects:
        jira_projects = [p.strip() for p in args.jira_projects.split(",")]

    if prs_path.exists():
        logger.info("  Resuming from existing %s", prs_path)
        prs_data = [json.loads(line) for line in prs_path.read_text().splitlines()
                    if line.strip()]
        from swebenchify.models import CandidatePR
        prs = [CandidatePR(**d) for d in prs_data]
    else:
        prs = collect_prs(
            repo_obj, max_prs=max_prs,
            pr_after=args.pr_after, pr_before=args.pr_before,
            rh_jira_projects=jira_projects,
        )
        save_prs(prs, str(prs_path))

    logger.info("  Collected %d PRs", len(prs))

    # --- Stage 2: Extract candidates ---
    logger.info("Stage 2: Extracting candidates...")

    if candidates_path.exists():
        logger.info("  Resuming from existing %s", candidates_path)
        cand_data = [json.loads(line) for line in candidates_path.read_text().splitlines()
                     if line.strip()]
        candidates = [CandidateInstance(**d) for d in cand_data]
    else:
        candidates = extract_all(prs, github_token=token)
        save_candidates(candidates, str(candidates_path))

    logger.info("  Extracted %d candidates", len(candidates))

    # --- Stage 2.5: Refine patch split (if backend supports it) ---
    backend = get_backend(language)
    if backend and backend.is_test_hunk:
        refined = 0
        for c in candidates:
            if c.patch:
                new_gold, new_test = refine_patch_split(
                    c.patch, c.test_patch, backend)
                if new_test != c.test_patch:
                    c.patch = new_gold
                    c.test_patch = new_test
                    refined += 1
        if refined:
            logger.info("  Refined patch split for %d candidates "
                        "(extracted inline test hunks)", refined)

    # --- Stage 3: Filter to viable test candidates ---
    viable = [
        c for c in candidates
        if c.patch and c.test_patch and has_tests(language, c.test_patch)
    ]
    logger.info("  Viable %s test candidates: %d / %d",
                language, len(viable), len(candidates))

    if not viable:
        logger.warning("No viable %s test candidates found for %s",
                       language, args.repo)
        return 0

    if args.skip_valid and instances_path.exists():
        existing_ids: set[str] = set()
        for line in instances_path.read_text().splitlines():
            if line.strip():
                existing_ids.add(json.loads(line)["instance_id"])
        before = len(viable)
        viable = [c for c in viable if c.instance_id not in existing_ids]
        logger.info("  --skip-valid: skipping %d already-validated, %d remaining",
                     before - len(viable), len(viable))
        if not viable:
            logger.info("All candidates already validated.")
            return 0

    if args.dry_run:
        logger.info("Dry run — skipping validation. Would validate %d candidates.",
                    len(viable))
        for c in viable[:10]:
            logger.info("  %s", c.instance_id)
        if len(viable) > 10:
            logger.info("  ... and %d more", len(viable) - 10)
        return 0

    # --- Stage 4: Build env spec and validate ---
    env_spec = build_env_spec(language, args, args.repo, token)
    logger.info("Environment spec: language=%s version=%s test='%s'",
                language, getattr(env_spec, 'language_version',
                                  getattr(env_spec, 'rust_version', '?')),
                env_spec.test_cmd)

    results: dict[str, ValidationResult] = {}
    for i, c in enumerate(viable, 1):
        logger.info("[%d/%d] Validating %s ...", i, len(viable), c.instance_id)
        try:
            result = compute_f2p(
                repo=c.repo,
                base_commit=c.base_commit,
                test_patch=c.test_patch or "",
                gold_patch=c.patch or "",
                env_spec=env_spec,
                timeout=timeout,
                n_runs=args.n_runs,
            )
        except Exception as exc:
            logger.error("  %s failed: %s", c.instance_id, exc)
            result = ValidationResult(status="error", error_message=str(exc))
        results[c.instance_id] = result
        if result.error_message:
            logger.info("  %s -> %s (f2p=%d, p2p=%d) error=%s",
                        c.instance_id, result.status,
                        len(result.FAIL_TO_PASS), len(result.PASS_TO_PASS),
                        result.error_message[:500])
        else:
            logger.info("  %s -> %s (f2p=%d, p2p=%d)",
                        c.instance_id, result.status,
                        len(result.FAIL_TO_PASS), len(result.PASS_TO_PASS))

    valid = sum(1 for v in results.values() if v.status == "valid")
    invalid = sum(1 for v in results.values() if v.status == "invalid")
    errors = sum(1 for v in results.values() if v.status == "error")
    logger.info("Results: %d valid, %d invalid, %d errors (of %d)",
                valid, invalid, errors, len(results))

    # --- Stage 5: Build and emit task instances ---
    instances = build_task_instances(viable, results, env_spec)
    logger.info("Built %d task instances", len(instances))

    write_mode = "a" if args.skip_valid else "w"
    with open(instances_path, write_mode) as f:
        for inst in instances:
            f.write(json.dumps(asdict(inst)) + "\n")
    logger.info("Wrote %d instances to %s (mode=%s)",
                len(instances), instances_path, write_mode)

    spec_path = output_dir / "env_spec.json"
    spec_path.write_text(json.dumps(asdict(env_spec), indent=2) + "\n")
    logger.info("Saved env spec to %s (hash=%s)",
                spec_path, env_spec.env_spec_hash)

    return 0


if __name__ == "__main__":
    sys.exit(main())
