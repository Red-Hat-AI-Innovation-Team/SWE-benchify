#!/usr/bin/env python3
"""Generic Rust repo pipeline: collect PRs, extract candidates, validate.

Runs the full SWE-benchify pipeline for cargo-based Rust repos:
  1. Collect merged PRs with linked issues
  2. Extract gold/test patches
  3. Filter to Rust test candidates
  4. Validate via Docker (compute f2p/p2p)
  5. Emit task instances

Usage::

    python scripts/discover_and_validate_rust.py \
        --repo stratis-storage/stratisd \
        --max-prs 500 \
        --output output/stratisd/

    # With env spec overrides:
    python scripts/discover_and_validate_rust.py \
        --repo stratis-storage/stratisd \
        --rust-version 1.84 \
        --test-cmd "cargo test --workspace" \
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

from swebenchify.backends import get_backend, refine_patch_split
from swebenchify.collector import collect_prs, save_prs
from swebenchify.extractor import extract_all, save_candidates
from swebenchify.grader import compute_f2p
from swebenchify.models import (
    CandidateInstance,
    RustEnvironmentSpec,
    Repository,
    ValidationResult,
    compute_rust_env_spec_hash,
)
from swebenchify.remote import build_task_instances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _has_rust_tests(test_patch: str) -> bool:
    """True if test_patch contains .rs files."""
    for line in test_patch.splitlines():
        if line.startswith("diff --git") and ".rs" in line:
            return True
    return False


def _detect_env_spec(repo: str, token: str | None) -> dict[str, str | list[str]]:
    """Auto-detect env spec fields from Cargo.toml and rust-toolchain.toml."""
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

        # Check rust-toolchain.toml for Rust version
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

        # Check Cargo.toml for workspace and edition
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.exists():
            content = cargo_toml.read_text()

            if "[workspace]" in content:
                detected["workspace_mode"] = "workspace"
                members: list[str] = []
                m = re.search(r'members\s*=\s*\[(.*?)\]', content, re.DOTALL)
                if m:
                    for member in re.findall(r'"([^"]+)"', m.group(1)):
                        members.append(member)
                if members:
                    detected["workspace_members"] = members

            m = re.search(r'edition\s*=\s*"(\d+)"', content)
            if m:
                detected["edition"] = m.group(1)

            m = re.search(r'rust-version\s*=\s*"(\d+\.\d+(?:\.\d+)?)"', content)
            if m and "rust_version" not in detected:
                detected["rust_version"] = m.group(1)

    return detected


def build_env_spec(args: argparse.Namespace, repo: str, token: str | None) -> RustEnvironmentSpec:
    """Build RustEnvironmentSpec from CLI args + auto-detection."""
    auto = _detect_env_spec(repo, token) if not args.skip_detection else {}

    system_deps: list[str] = []
    if args.system_deps:
        system_deps = [d.strip() for d in args.system_deps.split(",") if d.strip()]

    workspace_members: list[str] = []
    if isinstance(auto.get("workspace_members"), list):
        workspace_members = auto["workspace_members"]

    spec = RustEnvironmentSpec(
        rust_version=args.rust_version or str(auto.get("rust_version", "")),
        build_cmd=args.build_cmd or "",
        test_cmd=args.test_cmd or "cargo test",
        workspace_mode=str(auto.get("workspace_mode", "single")),
        workspace_members=workspace_members,
        edition=str(auto.get("edition", "")),
        features=args.features or "",
        system_dependencies=system_deps,
    )
    spec.env_spec_hash = compute_rust_env_spec_hash(spec)
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full Rust pipeline for a cargo-based GitHub repo.",
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
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout per validation phase in seconds (default: 600)")
    parser.add_argument("--n-runs", type=int, default=1,
                        help="Number of validation runs for flake detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and extract only, skip validation")
    parser.add_argument("--skip-valid", action="store_true",
                        help="Skip candidates already in the task-instances output")

    env_group = parser.add_argument_group("environment spec overrides")
    env_group.add_argument("--rust-version", default=None,
                           help="Rust toolchain version (default: auto-detect)")
    env_group.add_argument("--test-cmd", default=None,
                           help="Test command (default: cargo test)")
    env_group.add_argument("--build-cmd", default=None,
                           help="Build command (default: none)")
    env_group.add_argument("--features", default=None,
                           help="Cargo feature flags (e.g. --all-features)")
    env_group.add_argument("--system-deps", default=None,
                           help="Comma-separated system packages to install")
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

    # --- Stage 2.5: Refine patch split for Rust inline tests ---
    rust_backend = get_backend("rust")
    if rust_backend:
        refined = 0
        for c in candidates:
            if c.patch:
                new_gold, new_test = refine_patch_split(c.patch, c.test_patch, rust_backend)
                if new_test != c.test_patch:
                    c.patch = new_gold
                    c.test_patch = new_test
                    refined += 1
        if refined:
            logger.info("  Refined patch split for %d candidates (extracted inline test hunks)", refined)

    # --- Stage 3: Filter to viable Rust test candidates ---
    viable = [
        c for c in candidates
        if c.patch and c.test_patch and _has_rust_tests(c.test_patch)
    ]
    logger.info("  Viable Rust test candidates: %d / %d", len(viable), len(candidates))

    if not viable:
        logger.warning("No viable Rust test candidates found for %s", args.repo)
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
        logger.info("Dry run -- skipping validation. Would validate %d candidates.", len(viable))
        for c in viable[:10]:
            logger.info("  %s", c.instance_id)
        if len(viable) > 10:
            logger.info("  ... and %d more", len(viable) - 10)
        return 0

    # --- Stage 4: Build env spec and validate ---
    env_spec = build_env_spec(args, args.repo, token)
    logger.info("Environment spec: rust=%s test='%s' workspace=%s edition=%s",
                env_spec.rust_version, env_spec.test_cmd,
                env_spec.workspace_mode, env_spec.edition)

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

    spec_path = output_dir / "env_spec.json"
    spec_dict = {
        "language": env_spec.language,
        "rust_version": env_spec.rust_version,
        "build_cmd": env_spec.build_cmd,
        "test_cmd": env_spec.test_cmd,
        "workspace_mode": env_spec.workspace_mode,
        "workspace_members": env_spec.workspace_members,
        "edition": env_spec.edition,
        "features": env_spec.features,
        "system_dependencies": env_spec.system_dependencies,
    }
    spec_path.write_text(json.dumps(spec_dict, indent=2) + "\n")
    logger.info("Saved env spec to %s (hash=%s)", spec_path, env_spec.env_spec_hash)

    return 0


if __name__ == "__main__":
    sys.exit(main())
