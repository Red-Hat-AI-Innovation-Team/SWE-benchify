"""Download and sample SWE-Smith instances from HuggingFace.

Downloads the SWE-Smith dataset, samples instances stratified by repo,
and saves them in a format compatible with our eval infrastructure.

Usage:
    python3 scripts/download_swesmith.py                    # Download + sample 200
    python3 scripts/download_swesmith.py --n-samples 500    # Larger sample
    python3 scripts/download_swesmith.py --list-repos       # Show available repos
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def download_dataset():
    """Download SWE-Smith from HuggingFace."""
    from datasets import load_dataset
    print("Downloading SWE-Smith dataset from HuggingFace...", file=sys.stderr)
    ds = load_dataset("SWE-bench/SWE-smith", split="train")
    print(f"Downloaded {len(ds)} instances", file=sys.stderr)
    return ds


def sample_instances(ds, n_samples: int = 200, seed: int = 42):
    """Sample instances stratified by repo."""
    random.seed(seed)

    by_repo = defaultdict(list)
    for i, row in enumerate(ds):
        by_repo[row["repo"]].append(i)

    repos = sorted(by_repo.keys())
    per_repo = max(1, n_samples // len(repos))
    remainder = n_samples - per_repo * len(repos)

    sampled_indices = []
    for repo in repos:
        indices = by_repo[repo]
        k = min(per_repo, len(indices))
        sampled_indices.extend(random.sample(indices, k))

    if remainder > 0:
        remaining = [i for i in range(len(ds)) if i not in set(sampled_indices)]
        sampled_indices.extend(random.sample(remaining, min(remainder, len(remaining))))

    sampled_indices = sampled_indices[:n_samples]
    random.shuffle(sampled_indices)
    return sampled_indices


def convert_instance(row) -> dict:
    """Convert a HuggingFace row to our eval format."""
    f2p = row.get("FAIL_TO_PASS", [])
    p2p = row.get("PASS_TO_PASS", [])
    if isinstance(f2p, str):
        f2p = json.loads(f2p)
    if isinstance(p2p, str):
        p2p = json.loads(p2p)

    return {
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "patch": row["patch"],
        "problem_statement": row.get("problem_statement", ""),
        "FAIL_TO_PASS": json.dumps(f2p),
        "PASS_TO_PASS": json.dumps(p2p[:50]),
        "image_name": row.get("image_name", ""),
        "test_patch": "",
        "hints_text": "",
        "version": "1.0",
        "repo_language": "python",
        "provenance": "swesmith",
    }


def main():
    parser = argparse.ArgumentParser(description="Download and sample SWE-Smith")
    parser.add_argument("--n-samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--list-repos", action="store_true")
    args = parser.parse_args()

    ds = download_dataset()

    if args.list_repos:
        by_repo = defaultdict(int)
        for row in ds:
            by_repo[row["repo"]] += 1
        print(f"\n{len(by_repo)} repos, {len(ds)} total instances:")
        for repo, count in sorted(by_repo.items(), key=lambda x: -x[1]):
            print(f"  {repo}: {count}")
        return

    indices = sample_instances(ds, args.n_samples, args.seed)
    output = args.output or os.path.join(DATA_DIR, f"swesmith-sample-{args.n_samples}.jsonl")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    repos = defaultdict(int)
    with open(output, "w") as f:
        for idx in indices:
            row = ds[idx]
            inst = convert_instance(row)
            f.write(json.dumps(inst) + "\n")
            repos[inst["repo"]] += 1

    print(f"\nSampled {len(indices)} instances to {output}", file=sys.stderr)
    print(f"Repos: {len(repos)}", file=sys.stderr)
    for repo, count in sorted(repos.items(), key=lambda x: -x[1])[:10]:
        print(f"  {repo}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
