#!/usr/bin/env python
"""Run mechanical stages (1-2) on all SWE-bench repos (Phase 1.3a).

Collects PRs and extracts patches for each of the 13 SWE-bench Python repos,
then measures instance_id overlap against the published SWE-bench dataset.

Usage:
    # Run on all repos
    GITHUB_TOKEN=... python scripts/run_mechanical_all_repos.py

    # Run on specific repos
    GITHUB_TOKEN=... python scripts/run_mechanical_all_repos.py \
        --repos pallets/flask,psf/requests

    # Just measure overlap (skip collection, use existing output)
    python scripts/run_mechanical_all_repos.py --overlap-only

    # Dry run
    python scripts/run_mechanical_all_repos.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SWEBENCH_REPOS = [
    "astropy/astropy",
    "django/django",
    "matplotlib/matplotlib",
    "mwaskom/seaborn",
    "pallets/flask",
    "psf/requests",
    "pydata/xarray",
    "pylint-dev/astroid",
    "pylint-dev/pylint",
    "pytest-dev/pytest",
    "scikit-learn/scikit-learn",
    "sphinx-doc/sphinx",
    "sympy/sympy",
]

REPO_DATE_RANGES: dict[str, tuple[str, str]] = {
    "astropy/astropy": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "django/django": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "matplotlib/matplotlib": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "mwaskom/seaborn": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "pallets/flask": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "psf/requests": ("2012-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "pydata/xarray": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "pylint-dev/astroid": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "pylint-dev/pylint": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "pytest-dev/pytest": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "scikit-learn/scikit-learn": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "sphinx-doc/sphinx": ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    "sympy/sympy": ("2012-01-01T00:00:00Z", "2024-06-01T00:00:00Z"),
}


def load_swebench_instance_ids(
    dataset_name: str = "princeton-nlp/SWE-bench",
    split: str = "test",
) -> dict[str, set[str]]:
    """Load instance_ids from SWE-bench dataset, grouped by repo."""
    from datasets import load_dataset

    ds = load_dataset(dataset_name, split=split)
    by_repo: dict[str, set[str]] = {}
    for row in ds:
        repo = row["repo"]
        by_repo.setdefault(repo, set()).add(row["instance_id"])
    return by_repo


def run_mechanical_stages(
    repo_name: str,
    token: str,
    output_dir: Path,
    pr_after: str,
    pr_before: str,
) -> tuple[int, int, set[str]]:
    """Run stages 1-2 on a single repo.

    Returns (num_prs, num_candidates, candidate_instance_ids).
    """
    from swebenchify.collector import collect_prs, save_prs
    from swebenchify.extractor import extract_all, save_candidates
    from swebenchify.models import Repository

    repo = Repository(full_name=repo_name, access_token=token)
    slug = repo_name.replace("/", "__")

    candidates_path = output_dir / f"{slug}-candidates.jsonl"
    if candidates_path.exists():
        logger.info("Loading cached candidates for %s", repo_name)
        ids = set()
        with open(candidates_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    ids.add(data["instance_id"])
        return -1, len(ids), ids

    logger.info("Collecting PRs for %s (%s to %s)", repo_name, pr_after, pr_before)
    prs = collect_prs(repo, pr_after=pr_after, pr_before=pr_before)
    prs_path = output_dir / f"{slug}-prs.jsonl"
    save_prs(prs, str(prs_path))
    logger.info("Collected %d PRs for %s", len(prs), repo_name)

    logger.info("Extracting patches for %s", repo_name)
    candidates = extract_all(prs, github_token=token)
    save_candidates(candidates, str(candidates_path))

    viable = [c for c in candidates if c.patch and c.test_patch and c.problem_statement]
    logger.info("Extracted %d candidates (%d viable) for %s",
                len(candidates), len(viable), repo_name)

    ids = {c.instance_id for c in viable}
    return len(prs), len(viable), ids


def measure_overlap(
    our_ids: dict[str, set[str]],
    swebench_ids: dict[str, set[str]],
) -> dict:
    """Measure instance_id overlap between our output and SWE-bench."""
    results = {}
    total_overlap = 0
    total_swebench = 0
    total_ours = 0

    for repo in sorted(set(our_ids.keys()) | set(swebench_ids.keys())):
        ours = our_ids.get(repo, set())
        theirs = swebench_ids.get(repo, set())
        overlap = ours & theirs
        missing = theirs - ours
        extra = ours - theirs

        results[repo] = {
            "ours": len(ours),
            "swebench": len(theirs),
            "overlap": len(overlap),
            "missing": len(missing),
            "extra": len(extra),
            "overlap_rate": len(overlap) / len(theirs) if theirs else 0.0,
        }

        total_overlap += len(overlap)
        total_swebench += len(theirs)
        total_ours += len(ours)

    results["_total"] = {
        "ours": total_ours,
        "swebench": total_swebench,
        "overlap": total_overlap,
        "overlap_rate": total_overlap / total_swebench if total_swebench else 0.0,
    }

    return results


def format_overlap(results: dict) -> str:
    """Format overlap results as a report."""
    lines = [
        "=" * 70,
        "Mechanical Stages (1-2): Instance ID Overlap with SWE-bench",
        "=" * 70,
        "",
        f"{'Repo':<35} {'Ours':>6} {'SWE':>6} {'Overlap':>8} {'Rate':>8}",
        "-" * 70,
    ]

    for repo, data in sorted(results.items()):
        if repo == "_total":
            continue
        lines.append(
            f"{repo:<35} {data['ours']:>6} {data['swebench']:>6} "
            f"{data['overlap']:>8} {data['overlap_rate']:>7.0%}"
        )

    total = results["_total"]
    lines.append("-" * 70)
    lines.append(
        f"{'TOTAL':<35} {total['ours']:>6} {total['swebench']:>6} "
        f"{total['overlap']:>8} {total['overlap_rate']:>7.0%}"
    )
    lines.append("")

    target = 0.90
    status = "PASS" if total["overlap_rate"] >= target else "FAIL"
    lines.append(f"Target: >={target:.0%} — [{status}]")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mechanical stages on all SWE-bench repos (1.3a)")
    parser.add_argument("--repos", help="Comma-separated repos (default: all 13)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="Output directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overlap-only", action="store_true",
                        help="Skip collection, just measure overlap on existing output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", type=Path, help="Save results to file")
    args = parser.parse_args()

    repos = args.repos.split(",") if args.repos else SWEBENCH_REPOS
    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading SWE-bench ground truth instance IDs...")
    swebench_ids = load_swebench_instance_ids()
    logger.info("Loaded %d total SWE-bench instances across %d repos",
                sum(len(v) for v in swebench_ids.values()), len(swebench_ids))

    if args.dry_run:
        print(f"\nWould run mechanical stages on {len(repos)} repos:")
        for repo in repos:
            swe_count = len(swebench_ids.get(repo, set()))
            dates = REPO_DATE_RANGES.get(repo, ("?", "?"))
            print(f"  {repo}: {swe_count} SWE-bench instances, dates {dates[0][:10]} to {dates[1][:10]}")
        return

    our_ids: dict[str, set[str]] = {}

    if args.overlap_only:
        for repo in repos:
            slug = repo.replace("/", "__")
            candidates_path = args.output_dir / f"{slug}-candidates.jsonl"
            if candidates_path.exists():
                ids = set()
                with open(candidates_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            if data.get("patch") and data.get("test_patch") and data.get("problem_statement"):
                                ids.add(data["instance_id"])
                our_ids[repo] = ids
                logger.info("Loaded %d viable candidates for %s", len(ids), repo)
            else:
                logger.warning("No candidates file for %s — skipping", repo)
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Set GITHUB_TOKEN to run collection", file=sys.stderr)
            sys.exit(1)

        for repo in repos:
            dates = REPO_DATE_RANGES.get(repo, ("2016-01-01T00:00:00Z", "2024-06-01T00:00:00Z"))
            try:
                num_prs, num_candidates, ids = run_mechanical_stages(
                    repo, token, args.output_dir, dates[0], dates[1],
                )
                our_ids[repo] = ids
            except Exception as e:
                logger.error("Failed to process %s: %s", repo, e)

    results = measure_overlap(our_ids, swebench_ids)

    if args.json:
        json_str = json.dumps(results, indent=2, default=str)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json_str)
            logger.info("Results saved to %s", args.save)
        else:
            print(json_str)
    else:
        print(format_overlap(results))

    if args.save and not args.json:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
