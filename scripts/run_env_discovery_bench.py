#!/usr/bin/env python
"""Run agent-based env discovery on SWE-bench repos and benchmark results.

Phase 1.1b: For each (repo, version) in MAP_REPO_VERSION_TO_SPECS,
dispatch an agent to discover the environment spec, then score the
result against SWE-bench's ground truth.

Usage:
    # Run on Flask only (6 versions)
    python scripts/run_env_discovery_bench.py --repo pallets/flask

    # Run on Flask + Requests (34 versions total)
    python scripts/run_env_discovery_bench.py --repo pallets/flask --repo psf/requests

    # Dry run: show what would be done without running agents
    python scripts/run_env_discovery_bench.py --repo pallets/flask --dry-run

    # Score previously generated specs (skip agent, just benchmark)
    python scripts/run_env_discovery_bench.py --repo pallets/flask --score-only

    # Limit to specific versions
    python scripts/run_env_discovery_bench.py --repo pallets/flask --versions 2.0,2.3

    # Use a specific model
    python scripts/run_env_discovery_bench.py --repo pallets/flask --model sonnet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swebenchify.spec_bench import benchmark_specs, load_ground_truth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_version_commits(repo: str) -> dict[str, str]:
    """Get a representative commit for each version from the SWE-bench dataset.

    Returns {version: commit_sha}.
    """
    try:
        from datasets import load_dataset

        ds = load_dataset("princeton-nlp/SWE-bench", split="test")
        version_commits: dict[str, str] = {}
        for row in ds:
            if row["repo"] == repo:
                v = row["version"]
                if v not in version_commits:
                    version_commits[v] = row["base_commit"]
        return version_commits
    except Exception as e:
        logger.error("Failed to load SWE-bench dataset: %s", e)
        return {}


def get_version_commits_from_tags(repo_path: Path, versions: list[str]) -> dict[str, str]:
    """Fallback: get commits from git tags."""
    import subprocess

    commits = {}
    for version in versions:
        for tag_pattern in [f"v{version}", f"{version}", f"v{version}.0", f"{version}.0"]:
            result = subprocess.run(
                ["git", "rev-parse", f"{tag_pattern}^{{commit}}"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                commits[version] = result.stdout.strip()
                break
    return commits


async def run_discovery_for_version(
    repo_name: str,
    version: str,
    commit: str,
    workspace_root: Path,
    max_turns: int = 80,
    budget_usd: float = 5.0,
    model: str | None = None,
) -> dict | None:
    """Run agent-based env discovery for one (repo, version) pair.

    Returns the generated spec dict, or None on failure.
    """
    from swebenchify.discovery import discover_environment
    from swebenchify.dispatcher import CostTracker
    from swebenchify.models import Repository
    from swebenchify.workspace import WorkspaceManager

    repo = Repository(full_name=repo_name)
    ws = WorkspaceManager(workspace_root)
    cost_tracker = CostTracker()

    cached = ws.get_cached_env_spec(repo, version)
    if cached is not None:
        logger.info("Using cached spec for %s v%s", repo_name, version)
        return cached

    logger.info("Running env discovery for %s v%s (commit %s)", repo_name, version, commit[:12])

    env_spec, repo_version = await discover_environment(
        repo=repo,
        commit=commit,
        version=version,
        workspace_mgr=ws,
        cost_tracker=cost_tracker,
        max_turns=max_turns,
        budget_usd=budget_usd,
    )

    if env_spec is not None:
        from dataclasses import asdict
        spec_dict = asdict(env_spec)
        logger.info("Discovery succeeded for %s v%s — cost: $%.2f",
                     repo_name, version, cost_tracker.total_cost())
        return spec_dict
    else:
        logger.error("Discovery failed for %s v%s — cost: $%.2f",
                      repo_name, version, cost_tracker.total_cost())
        return None


async def run_all_discoveries(
    repo_name: str,
    version_commits: dict[str, str],
    workspace_root: Path,
    max_concurrent: int = 1,
    max_turns: int = 80,
    budget_usd: float = 5.0,
    model: str | None = None,
) -> dict[str, dict]:
    """Run env discovery for all versions of a repo.

    Returns {version: spec_dict} for successful discoveries.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, dict] = {}

    async def discover_one(version: str, commit: str) -> None:
        async with semaphore:
            spec = await run_discovery_for_version(
                repo_name=repo_name,
                version=version,
                commit=commit,
                workspace_root=workspace_root,
                max_turns=max_turns,
                budget_usd=budget_usd,
                model=model,
            )
            if spec is not None:
                results[version] = spec

    tasks = [
        discover_one(version, commit)
        for version, commit in sorted(version_commits.items())
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    return results


def load_cached_specs(workspace_root: Path, repo_name: str) -> dict[str, dict]:
    """Load previously generated specs from the workspace cache."""
    slug = repo_name.replace("/", "__")
    envs_dir = workspace_root / slug / "envs"
    specs: dict[str, dict] = {}
    if not envs_dir.is_dir():
        return specs
    for version_dir in sorted(envs_dir.iterdir()):
        if not version_dir.is_dir():
            continue
        spec_file = version_dir / "env_spec.json"
        if spec_file.exists():
            try:
                specs[version_dir.name] = json.loads(spec_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return specs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run env discovery benchmark (Phase 1.1b)")
    parser.add_argument("--repo", action="append", required=True,
                        help="Repository to benchmark (can specify multiple)")
    parser.add_argument("--workspace", type=Path, default=Path("output/workspaces"),
                        help="Workspace root directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without running agents")
    parser.add_argument("--score-only", action="store_true",
                        help="Only score cached specs, don't run agents")
    parser.add_argument("--versions", help="Comma-separated list of versions to run")
    parser.add_argument("--max-concurrent", type=int, default=1,
                        help="Max concurrent agent sessions")
    parser.add_argument("--max-turns", type=int, default=80,
                        help="Max turns per agent session")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="Budget per agent session in USD")
    parser.add_argument("--model", help="Model to use for agent sessions")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--output", type=Path, help="Save results to file")
    args = parser.parse_args()

    all_results = {}

    for repo_name in args.repo:
        logger.info("=== Benchmarking %s ===", repo_name)

        ground_truth = load_ground_truth(repo_name)
        if not ground_truth:
            logger.error("No ground truth for %s — skipping", repo_name)
            continue

        target_versions = set(ground_truth.keys())
        if args.versions:
            target_versions &= set(args.versions.split(","))

        logger.info("Ground truth versions: %s", sorted(target_versions))

        if args.dry_run:
            print(f"\n{repo_name}: would run discovery for {len(target_versions)} versions")
            for v in sorted(target_versions):
                gt = ground_truth[v]
                print(f"  {v}: python={gt.get('python')}, install={gt.get('install')}, test_cmd={gt.get('test_cmd')}")
            continue

        if args.score_only:
            generated = load_cached_specs(args.workspace, repo_name)
        else:
            version_commits = get_version_commits(repo_name)
            version_commits = {v: c for v, c in version_commits.items() if v in target_versions}

            missing = target_versions - set(version_commits.keys())
            if missing:
                logger.warning("No commits found for versions: %s", sorted(missing))

            if not version_commits:
                logger.error("No version-commit mappings found for %s", repo_name)
                continue

            logger.info("Will run discovery for %d versions: %s",
                        len(version_commits), sorted(version_commits.keys()))

            generated = asyncio.run(run_all_discoveries(
                repo_name=repo_name,
                version_commits=version_commits,
                workspace_root=args.workspace,
                max_concurrent=args.max_concurrent,
                max_turns=args.max_turns,
                budget_usd=args.budget,
                model=args.model,
            ))

        result = benchmark_specs(generated, repo_name, ground_truth=ground_truth)
        all_results[repo_name] = result

        if not args.json:
            print(f"\n{'='*60}")
            print(result.summary())
            print(f"{'='*60}\n")

    if args.json:
        output = {}
        for repo_name, result in all_results.items():
            output[repo_name] = {
                "overall_score": result.overall_score,
                "field_match_rates": result.field_match_rates,
                "versions": [
                    {
                        "version": s.version,
                        "overall": s.overall,
                        "fields": {
                            f.field: {"match": f.match, "detail": f.detail}
                            for f in s.field_scores
                        },
                    }
                    for s in result.scores
                ],
            }
        json_str = json.dumps(output, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_str)
            logger.info("Results saved to %s", args.output)
        else:
            print(json_str)

    if not args.json and all_results:
        total_versions = sum(len(r.scores) for r in all_results.values())
        total_score = sum(r.overall_score * len(r.scores) for r in all_results.values()) / max(total_versions, 1)
        print(f"\nOverall: {total_versions} versions scored, aggregate score: {total_score:.1%}")
        target = 0.80
        status = "PASS" if total_score >= target else "FAIL"
        print(f"Target: >={target:.0%} — [{status}]")


if __name__ == "__main__":
    main()
