#!/usr/bin/env python
"""Run the Docker spec generation benchmark (Phase 1.1).

Loads ground truth from SWE-bench's MAP_REPO_VERSION_TO_SPECS, loads
agent-generated specs from a directory, and scores them.

Usage:
    # Score pre-generated specs
    python scripts/run_spec_bench.py --repo pallets/flask --specs-dir output/env_specs/

    # Score a single spec file against all versions
    python scripts/run_spec_bench.py --repo pallets/flask --spec-file output/env_spec.json

    # List available ground truth repos and versions
    python scripts/run_spec_bench.py --list-repos

    # Show ground truth for a repo
    python scripts/run_spec_bench.py --show-truth pallets/flask
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swebenchify.spec_bench import (
    benchmark_specs,
    load_ground_truth,
    score_spec,
)


def list_repos() -> None:
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS

    for repo in sorted(MAP_REPO_VERSION_TO_SPECS.keys()):
        versions = sorted(MAP_REPO_VERSION_TO_SPECS[repo].keys())
        print(f"{repo}: {len(versions)} versions — {', '.join(versions)}")


def show_truth(repo: str) -> None:
    truth = load_ground_truth(repo)
    if not truth:
        print(f"No ground truth for {repo}")
        return
    for version in sorted(truth.keys()):
        print(f"\n=== {repo} v{version} ===")
        print(json.dumps(truth[version], indent=2, default=str))


def load_generated_specs(specs_dir: Path, repo: str) -> dict[str, dict]:
    """Load generated specs from a directory.

    Expects either:
    - {version}/env_spec.json files
    - {repo_slug}/{version}/env_spec.json files
    """
    specs: dict[str, dict] = {}
    slug = repo.replace("/", "__")

    for candidate_dir in [specs_dir, specs_dir / slug]:
        if not candidate_dir.is_dir():
            continue
        for version_dir in sorted(candidate_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            spec_file = version_dir / "env_spec.json"
            if spec_file.exists():
                try:
                    spec = json.loads(spec_file.read_text())
                    specs[version_dir.name] = spec
                except (json.JSONDecodeError, OSError) as e:
                    print(f"Warning: failed to load {spec_file}: {e}", file=sys.stderr)
    return specs


def main() -> None:
    parser = argparse.ArgumentParser(description="Docker spec generation benchmark")
    parser.add_argument("--repo", help="Repository name (e.g. pallets/flask)")
    parser.add_argument("--specs-dir", type=Path, help="Directory with generated specs")
    parser.add_argument("--spec-file", type=Path, help="Single spec file to score against all versions")
    parser.add_argument("--list-repos", action="store_true", help="List available ground truth repos")
    parser.add_argument("--show-truth", metavar="REPO", help="Show ground truth for a repo")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    if args.list_repos:
        list_repos()
        return

    if args.show_truth:
        show_truth(args.show_truth)
        return

    if not args.repo:
        parser.error("--repo is required")

    truth = load_ground_truth(args.repo)
    if not truth:
        print(f"No ground truth for {args.repo}", file=sys.stderr)
        sys.exit(1)

    if args.spec_file:
        spec = json.loads(args.spec_file.read_text())
        generated = {v: spec for v in truth.keys()}
    elif args.specs_dir:
        generated = load_generated_specs(args.specs_dir, args.repo)
        if not generated:
            print(f"No generated specs found in {args.specs_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.error("--specs-dir or --spec-file is required")

    result = benchmark_specs(generated, args.repo, ground_truth=truth)

    if args.json:
        output = {
            "repo": args.repo,
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
        print(json.dumps(output, indent=2))
    else:
        print(result.summary())


if __name__ == "__main__":
    main()
