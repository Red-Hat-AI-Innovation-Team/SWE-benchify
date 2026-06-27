#!/usr/bin/env python3
"""Generic Java repo pipeline: collect PRs, extract candidates, validate.

Runs the full SWE-benchify pipeline for Maven-based Java repos:
  1. Collect merged PRs with linked issues
  2. Extract gold/test patches
  3. Filter to Maven test candidates
  4. Validate via Docker (compute f2p/p2p)
  5. Emit task instances

Usage::

    python scripts/discover_and_validate_java.py \
        --repo FasterXML/jackson-databind \
        --max-prs 500 \
        --output output/jackson-databind/

    # With env spec overrides:
    python scripts/discover_and_validate_java.py \
        --repo FasterXML/jackson-databind \
        --java-version 8 \
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

from swebenchify.backends import _java_test_scope
from swebenchify.collector import collect_prs, save_prs
from swebenchify.extractor import extract_all, save_candidates
from swebenchify.grader import compute_f2p
from swebenchify.models import (
    CandidateInstance,
    EnvironmentSpec,
    Repository,
    ValidationResult,
    compute_java_env_spec_hash,
)
from swebenchify.remote import build_task_instances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _has_maven_tests(test_patch: str) -> bool:
    """True if test_patch contains Java test files under src/test/."""
    return bool(_java_test_scope(test_patch))


def _detect_env_spec(repo: str, token: str | None) -> dict[str, str | list[str]]:
    """Auto-detect env spec fields from pom.xml."""
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
        pom = root / "pom.xml"
        if not pom.exists():
            return detected

        content = pom.read_text()

        # Try maven.compiler.release (Java 9+)
        m = re.search(
            r"<maven\.compiler\.release>\s*(\d+)\s*</maven\.compiler\.release>",
            content,
        )
        if m:
            detected["java_version"] = m.group(1)

        # Try maven.compiler.source
        if "java_version" not in detected:
            m = re.search(
                r"<maven\.compiler\.source>\s*([\d.]+)\s*</maven\.compiler\.source>",
                content,
            )
            if m:
                ver = m.group(1)
                if ver.startswith("1."):
                    ver = ver[2:]
                detected["java_version"] = ver

        # Try java.version property (common in Spring projects)
        if "java_version" not in detected:
            m = re.search(
                r"<java\.version>\s*([\d.]+)\s*</java\.version>",
                content,
            )
            if m:
                ver = m.group(1)
                if ver.startswith("1."):
                    ver = ver[2:]
                detected["java_version"] = ver

    return detected


def build_env_spec(args: argparse.Namespace, repo: str, token: str | None) -> EnvironmentSpec:
    """Build EnvironmentSpec from CLI args + auto-detection for Java."""
    auto = _detect_env_spec(repo, token) if not args.skip_detection else {}

    pre_install: list[str] = []
    if args.pre_install:
        pre_install = [cmd.strip() for cmd in args.pre_install.split(";") if cmd.strip()]
    else:
        pre_install = ["mvn dependency:resolve -q -B"]

    java_version = args.java_version or auto.get("java_version", "8")

    spec = EnvironmentSpec(
        language="java",
        language_version=str(java_version),
        package_manager="maven",
        install_cmd="",
        test_cmd=args.test_cmd or "mvn test -B",
        pre_install=pre_install,
        pip_packages=[],
        system_dependencies=[],
        base_image="",
        run_preamble="",
    )
    spec.env_spec_hash = compute_java_env_spec_hash(spec)
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full Java pipeline for a Maven-based GitHub repo.",
    )
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: output/{repo_slug}/)")
    parser.add_argument("--max-prs", type=int, default=500,
                        help="Max PRs to scan (default: 500)")
    parser.add_argument("--pr-after", default=None,
                        help="Only PRs created after this date (ISO 8601)")
    parser.add_argument("--pr-before", default=None,
                        help="Only PRs created before this date (ISO 8601)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="Timeout per validation phase in seconds (default: 900)")
    parser.add_argument("--n-runs", type=int, default=1,
                        help="Number of validation runs for flake detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and extract only, skip validation")
    parser.add_argument("--skip-valid", action="store_true",
                        help="Skip candidates already in the task-instances output")

    env_group = parser.add_argument_group("environment spec overrides")
    env_group.add_argument("--java-version", default=None,
                           help="JDK version (default: auto-detect or 8)")
    env_group.add_argument("--test-cmd", default=None,
                           help="Test command (default: mvn test -B)")
    env_group.add_argument("--pre-install", default=None,
                           help="Semicolon-separated pre-install commands")
    env_group.add_argument("--skip-detection", action="store_true",
                           help="Skip auto-detection, use defaults + overrides only")

    issue_group = parser.add_argument_group("issue tracking")
    issue_group.add_argument("--jira-projects", default=None,
                             help="Comma-separated Jira project keys (e.g. JACKSON)")

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

    jira_projects = None
    if args.jira_projects:
        jira_projects = [p.strip() for p in args.jira_projects.split(",")]

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
            rh_jira_projects=jira_projects,
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

    # --- Stage 3: Filter to viable Maven test candidates ---
    viable = [
        c for c in candidates
        if c.patch and c.test_patch and _has_maven_tests(c.test_patch)
    ]
    logger.info("  Viable Maven test candidates: %d / %d", len(viable), len(candidates))

    if not viable:
        logger.warning("No viable Maven test candidates found for %s", args.repo)
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
        logger.info("Dry run — skipping validation. Would validate %d candidates.", len(viable))
        for c in viable[:10]:
            logger.info("  %s", c.instance_id)
        if len(viable) > 10:
            logger.info("  ... and %d more", len(viable) - 10)
        return 0

    # --- Stage 4: Build env spec and validate ---
    env_spec = build_env_spec(args, args.repo, token)
    logger.info("Environment spec: java=%s test='%s' pre_install=%s",
                env_spec.language_version, env_spec.test_cmd, env_spec.pre_install)

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
    logger.info("Wrote %d instances to %s (mode=%s)", len(instances), instances_path, write_mode)

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
