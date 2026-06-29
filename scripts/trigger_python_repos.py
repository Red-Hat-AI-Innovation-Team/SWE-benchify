#!/usr/bin/env python3
"""Trigger the Python Pipeline GHA workflow for multiple repos in parallel.

Usage::

    python scripts/trigger_python_repos.py
    python scripts/trigger_python_repos.py --max-prs 100  # override for all
    python scripts/trigger_python_repos.py --dry-run       # show commands only
"""

from __future__ import annotations

import argparse
import subprocess
import sys

REPOS: list[dict[str, str]] = [
    {"repo": "RedHatInsights/insights-core"},
    {"repo": "ansible/awx"},
    {"repo": "ansible/ansible-navigator"},
    {"repo": "oamg/leapp-repository"},
    {"repo": "ansible/galaxy_ng"},
    {"repo": "RedHatInsights/insights-host-inventory"},
    {"repo": "candlepin/subscription-manager"},
    {"repo": "pulp/pulpcore"},
    {"repo": "openshift/lightspeed-service"},
    {"repo": "containers/podman-compose"},
]

GH_REPO = "Red-Hat-AI-Innovation-Team/SWE-benchify"
WORKFLOW = "Python Pipeline"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger Python Pipeline for multiple repos")
    parser.add_argument("--max-prs", default="300", help="Max PRs per repo (default: 300)")
    parser.add_argument("--timeout", default="600", help="Validation timeout (default: 600)")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")
    args = parser.parse_args(argv)

    results: list[tuple[str, str]] = []

    for entry in REPOS:
        repo = entry["repo"]
        cmd = [
            "gh", "workflow", "run", WORKFLOW,
            "-R", GH_REPO,
            "-f", f"repo={repo}",
            "-f", f"max_prs={args.max_prs}",
            "-f", f"timeout={args.timeout}",
        ]
        if "python_version" in entry:
            cmd += ["-f", f"python_version={entry['python_version']}"]
        if "pre_install" in entry:
            cmd += ["-f", f"pre_install={entry['pre_install']}"]

        if args.dry_run:
            print(f"[dry-run] {' '.join(cmd)}")
            results.append((repo, "(dry-run)"))
            continue

        print(f"Triggering {repo}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  FAILED: {result.stderr.strip()}", file=sys.stderr)
            results.append((repo, "FAILED"))
        else:
            url = result.stdout.strip()
            print(f"  {url}")
            results.append((repo, url))

    print(f"\n{'='*60}")
    print(f"Triggered {len(results)} repos:")
    for repo, url in results:
        print(f"  {repo}: {url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
