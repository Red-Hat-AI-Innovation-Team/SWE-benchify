#!/usr/bin/env python3
"""Generic Python repo pipeline: collect PRs, extract candidates, validate.

Runs the full SWE-benchify pipeline for any Python GitHub repo:
  1. Collect merged PRs with linked issues
  2. Extract gold/test patches
  3. Filter to pytest-compatible candidates
  4. Validate via Docker (compute f2p/p2p)
  5. Emit task instances

Usage::

    python scripts/discover_and_validate_python.py \
        --repo ansible/ansible-navigator \
        --max-prs 300 \
        --output output/ansible-navigator/

    # With env spec overrides:
    python scripts/discover_and_validate_python.py \
        --repo ansible/awx \
        --python-version 3.11 \
        --pre-install "pip install -r requirements/requirements.txt" \
        --max-prs 300
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

from swebenchify.backends import _python_test_scope
from swebenchify.collector import collect_prs, save_prs
from swebenchify.extractor import extract_all, save_candidates
from swebenchify.grader import compute_f2p
from swebenchify.models import (
    CandidateInstance,
    EnvironmentSpec,
    Repository,
    ValidationResult,
    compute_python_env_spec_hash,
)
from swebenchify.remote import build_task_instances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _has_pytest_tests(test_patch: str) -> bool:
    """True if test_patch contains pytest-discoverable test files."""
    return bool(_python_test_scope(test_patch))


def _detect_env_spec(repo: str, token: str | None) -> dict[str, str | list[str]]:
    """Auto-detect env spec fields from repo files.

    Clones the repo shallowly and reads pyproject.toml / setup.cfg /
    requirements files to guess Python version and pre-install steps.
    """
    detected: dict[str, str | list[str]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        clone_url = f"https://github.com/{repo}.git"
        result = subprocess.run(
            ["git", "clone", "--depth=1", clone_url, tmp],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.warning("Failed to clone %s for env detection: %s", repo, result.stderr[:200])
            return detected

        root = Path(tmp)

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
            "requirements.txt",
            "test-requirements.txt",
            "requirements-test.txt",
            "requirements-dev.txt",
        ]:
            if (root / req_file).exists():
                pre_install.append(f"pip install -r {req_file}")

        if pre_install:
            detected["pre_install"] = pre_install

    return detected


def build_env_spec(args: argparse.Namespace, repo: str, token: str | None) -> EnvironmentSpec:
    """Build EnvironmentSpec from CLI args + auto-detection."""
    auto = _detect_env_spec(repo, token) if not args.skip_detection else {}

    pre_install: list[str] = []
    if args.pre_install:
        pre_install = [cmd.strip() for cmd in args.pre_install.split(";") if cmd.strip()]
    elif "pre_install" in auto:
        pre_install = auto["pre_install"]  # type: ignore[assignment]

    spec = EnvironmentSpec(
        language="python",
        language_version=args.python_version or auto.get("python_version", "3.11"),  # type: ignore[arg-type]
        package_manager="pip",
        install_cmd=args.install_cmd or "pip install -e .",
        test_cmd=args.test_cmd or "pytest",
        pre_install=pre_install,
        pip_packages=[],
        system_dependencies=[],
    )
    spec.env_spec_hash = compute_python_env_spec_hash(spec)
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full Python pipeline for a GitHub repo.",
    )
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: output/{repo_slug}/)")
    parser.add_argument("--max-prs", type=int, default=300,
                        help="Max PRs to scan (default: 300)")
    parser.add_argument("--pr-after", default=None,
                        help="Only PRs created after this date (ISO 8601)")
    parser.add_argument("--pr-before", default=None,
                        help="Only PRs created before this date (ISO 8601)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout per validation phase in seconds (default: 600)")
    parser.add_argument("--n-runs", type=int, default=1,
                        help="Number of validation runs for flake detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and extract only, skip validation")

    env_group = parser.add_argument_group("environment spec overrides")
    env_group.add_argument("--python-version", default=None,
                           help="Python version (default: auto-detect or 3.11)")
    env_group.add_argument("--install-cmd", default=None,
                           help="Install command (default: pip install -e .)")
    env_group.add_argument("--test-cmd", default=None,
                           help="Test command (default: pytest)")
    env_group.add_argument("--pre-install", default=None,
                           help="Semicolon-separated pre-install commands")
    env_group.add_argument("--skip-detection", action="store_true",
                           help="Skip auto-detection, use defaults + overrides only")

    args = parser.parse_args(argv)

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
    logger.info("Stage 1: Collecting PRs from %s (max=%s)...", args.repo, args.max_prs)
    repo_obj = Repository(full_name=args.repo, access_token=token)

    if prs_path.exists():
        logger.info("  Resuming from existing %s", prs_path)
        prs_data = [json.loads(line) for line in prs_path.read_text().splitlines() if line.strip()]
        from swebenchify.models import CandidatePR
        prs = [CandidatePR(**d) for d in prs_data]
    else:
        prs = collect_prs(
            repo_obj,
            max_prs=args.max_prs,
            pr_after=args.pr_after,
            pr_before=args.pr_before,
        )
        save_prs(prs, str(prs_path))

    logger.info("  Collected %d PRs", len(prs))

    # --- Stage 2: Extract candidates ---
    logger.info("Stage 2: Extracting candidates...")

    if candidates_path.exists():
        logger.info("  Resuming from existing %s", candidates_path)
        cand_data = [json.loads(line) for line in candidates_path.read_text().splitlines() if line.strip()]
        candidates = [CandidateInstance(**d) for d in cand_data]
    else:
        candidates = extract_all(prs, github_token=token)
        save_candidates(candidates, str(candidates_path))

    logger.info("  Extracted %d candidates", len(candidates))

    # --- Stage 3: Filter to viable pytest candidates ---
    viable = [
        c for c in candidates
        if c.patch and c.test_patch and _has_pytest_tests(c.test_patch)
    ]
    logger.info("  Viable pytest candidates: %d / %d", len(viable), len(candidates))

    if not viable:
        logger.warning("No viable pytest candidates found for %s", args.repo)
        return 0

    if args.dry_run:
        logger.info("Dry run — skipping validation. Would validate %d candidates.", len(viable))
        for c in viable[:10]:
            logger.info("  %s", c.instance_id)
        if len(viable) > 10:
            logger.info("  ... and %d more", len(viable) - 10)
        return 0

    # --- Stage 4: Build env spec and validate ---
    env_spec = build_env_spec(args, args.repo, token)
    logger.info("Environment spec: python=%s install='%s' test='%s' pre_install=%s",
                env_spec.language_version, env_spec.install_cmd,
                env_spec.test_cmd, env_spec.pre_install)

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
                timeout=args.timeout,
                n_runs=args.n_runs,
            )
        except Exception as exc:
            logger.error("  %s failed: %s", c.instance_id, exc)
            result = ValidationResult(status="error", error_message=str(exc))
        results[c.instance_id] = result
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

    with open(instances_path, "w") as f:
        for inst in instances:
            f.write(json.dumps(asdict(inst)) + "\n")
    logger.info("Wrote %d instances to %s", len(instances), instances_path)

    # Also save the env spec for later image building
    spec_path = output_dir / "env_spec.json"
    spec_dict = {
        "language": env_spec.language,
        "language_version": env_spec.language_version,
        "package_manager": env_spec.package_manager,
        "install_cmd": env_spec.install_cmd,
        "test_cmd": env_spec.test_cmd,
        "pre_install": env_spec.pre_install,
        "pip_packages": env_spec.pip_packages,
        "system_dependencies": env_spec.system_dependencies,
    }
    spec_path.write_text(json.dumps(spec_dict, indent=2) + "\n")
    logger.info("Saved env spec to %s (hash=%s)", spec_path, env_spec.env_spec_hash)

    return 0


if __name__ == "__main__":
    sys.exit(main())
