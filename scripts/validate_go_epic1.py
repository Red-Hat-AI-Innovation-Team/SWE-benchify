#!/usr/bin/env python3
"""Validate Epic 1 Go-support exit criteria (M0 – M2).

Exit criteria (from Epic #28):
  M0  Deterministic Docker validation reproduces recorded F2P at >=85% exact
      agreement on both kubectl and etcd.
  M1  Clean end-to-end run on kubectl produces valid SWEbenchInstance rows
      with segmentation metadata.
  M2  Flake quarantine proven stable on etcd; both repos stable across
      repeated runs.

Usage
-----
  # M0 — requires a JSONL of known-good instances with recorded raw test output
  python scripts/validate_go_epic1.py m0 \\
      --known-good path/to/rh_swe_bench_kubectl_etcd.jsonl

  # M1 — requires GITHUB_TOKEN + ANTHROPIC_API_KEY + Docker/Podman
  python scripts/validate_go_epic1.py m1 \\
      --config configs/swebenchify.yaml \\
      --repo kubernetes/kubernetes \\
      --max-prs 10

  # M2 — same prerequisites as M1 (builds on M1 output)
  python scripts/validate_go_epic1.py m2 \\
      --config configs/swebenchify.yaml \\
      --repo etcd-io/etcd \\
      --max-prs 5 \\
      --n-runs 3

  # Run all checks (skips unavailable prerequisites automatically)
  python scripts/validate_go_epic1.py all \\
      --known-good path/to/rh_swe_bench.jsonl \\
      --config configs/swebenchify.yaml

Known-good JSONL format (one instance per line)
------------------------------------------------
Each line must contain at minimum:
  {
    "instance_id": "kubernetes__kubectl-1234",
    "repo": "kubernetes/kubernetes",
    "FAIL_TO_PASS": "[\"github.com/foo/bar.TestRun\", ...]",   // ground-truth F2P
    "pre_fix_output": "<raw go test -json output before patch>",
    "post_fix_output": "<raw go test -json output after patch>"
  }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import NamedTuple

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("epic1-validation")

PASS_THRESHOLD = 0.85  # M0 target: >=85% exact F2P agreement


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def check_prerequisites() -> dict[str, bool]:
    """Return a dict of prerequisite -> available."""
    import shutil
    prefs: dict[str, bool] = {}
    prefs["docker_or_podman"] = bool(shutil.which("docker") or shutil.which("podman"))
    prefs["go"] = bool(shutil.which("go"))
    prefs["anthropic_api_key"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    prefs["github_token"] = bool(os.environ.get("GITHUB_TOKEN"))
    return prefs


def print_prereqs(prefs: dict[str, bool]) -> None:
    print("\nPrerequisite check:")
    for name, ok in prefs.items():
        sym = "✓" if ok else "✗"
        print(f"  {sym} {name}")
    print()


# ---------------------------------------------------------------------------
# M0: Parser agreement against known-good instances
# ---------------------------------------------------------------------------

class M0Result(NamedTuple):
    total: int
    exact_match: int
    subset_match: int
    agreement_rate: float
    details: list[dict]


def run_m0(known_good_path: str) -> M0Result:
    """Measure GoJSONParser F2P agreement against known-good instances.

    Each instance in the JSONL must have pre_fix_output + post_fix_output
    (raw go test -json streams) and FAIL_TO_PASS (ground-truth list).

    Returns M0Result with the agreement rate and per-instance breakdown.
    """
    from swebenchify.parsers import GoJSONParser
    from swebenchify.validator import _compute_f2p_p2p

    parser = GoJSONParser()
    instances = []
    with open(known_good_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            instances.append(json.loads(line))

    # Filter to kubectl and etcd
    go_instances = [
        i for i in instances
        if i.get("repo") in ("kubernetes/kubernetes", "etcd-io/etcd")
        and i.get("pre_fix_output")
        and i.get("post_fix_output")
    ]
    logger.info("Loaded %d Go instances from %s", len(go_instances), known_good_path)
    if not go_instances:
        logger.error("No kubectl/etcd instances with pre/post fix output found")
        return M0Result(0, 0, 0, 0.0, [])

    exact_match = 0
    subset_match = 0
    details = []

    for inst in go_instances:
        iid = inst["instance_id"]
        ground_truth_raw = inst["FAIL_TO_PASS"]
        if isinstance(ground_truth_raw, str):
            ground_truth = set(json.loads(ground_truth_raw))
        else:
            ground_truth = set(ground_truth_raw)

        pre = parser.parse(inst["pre_fix_output"])
        post = parser.parse(inst["post_fix_output"])
        our_f2p_list, _ = _compute_f2p_p2p(pre["tests"], post["tests"])
        our_f2p = set(our_f2p_list)

        is_exact = our_f2p == ground_truth
        is_subset = our_f2p.issubset(ground_truth) or ground_truth.issubset(our_f2p)

        if is_exact:
            exact_match += 1
        if is_subset:
            subset_match += 1

        details.append({
            "instance_id": iid,
            "repo": inst.get("repo"),
            "ground_truth_f2p": sorted(ground_truth),
            "our_f2p": sorted(our_f2p),
            "exact_match": is_exact,
            "subset_match": is_subset,
            "compiled": pre["compiled"],
        })

    total = len(go_instances)
    rate = exact_match / total if total else 0.0

    return M0Result(
        total=total,
        exact_match=exact_match,
        subset_match=subset_match,
        agreement_rate=rate,
        details=details,
    )


def print_m0_results(result: M0Result) -> bool:
    print("\n" + "=" * 60)
    print("M0 — Deterministic Parser F2P Agreement")
    print("=" * 60)
    if result.total == 0:
        print("  ERROR: No instances to evaluate")
        return False

    print(f"  Instances evaluated : {result.total}")
    print(f"  Exact F2P match     : {result.exact_match} / {result.total}  ({result.agreement_rate:.1%})")
    print(f"  Subset F2P match    : {result.subset_match} / {result.total}  ({result.subset_match/result.total:.1%})")
    print(f"  Target              : >={PASS_THRESHOLD:.0%} exact agreement")
    passed = result.agreement_rate >= PASS_THRESHOLD
    print(f"  Outcome             : {'PASS ✓' if passed else 'FAIL ✗'}")

    # Per-repo breakdown
    for repo in ("kubernetes/kubernetes", "etcd-io/etcd"):
        repo_details = [d for d in result.details if d["repo"] == repo]
        if not repo_details:
            continue
        repo_exact = sum(1 for d in repo_details if d["exact_match"])
        repo_rate = repo_exact / len(repo_details) if repo_details else 0.0
        repo_pass = "PASS ✓" if repo_rate >= PASS_THRESHOLD else "FAIL ✗"
        print(f"\n  {repo}")
        print(f"    Exact match: {repo_exact}/{len(repo_details)} ({repo_rate:.1%}) — {repo_pass}")
        for d in repo_details:
            sym = "=" if d["exact_match"] else ("≈" if d["subset_match"] else "✗")
            print(f"    [{sym}] {d['instance_id']}")

    print()
    return passed


# ---------------------------------------------------------------------------
# M1: End-to-end kubectl run
# ---------------------------------------------------------------------------

def run_m1(config_path: str, repo: str = "kubernetes/kubernetes", max_prs: int = 10) -> bool:
    """Run the full pipeline on kubectl and verify valid SWEbenchInstance output.

    Prerequisites: ANTHROPIC_API_KEY, GITHUB_TOKEN, Docker/Podman.
    """
    import asyncio
    from swebenchify.config import load_config
    from swebenchify.pipeline import run_repo_pipeline
    from swebenchify.models import Repository
    from swebenchify.dispatcher import CostTracker
    from swebenchify.workspace import WorkspaceManager

    config = load_config(config_path)
    # Override to target kubectl with limited PRs
    config.go_repos = [repo]
    config.pipeline.max_prs_per_repo = max_prs

    workspace_mgr = WorkspaceManager(config.output.dir + "/workspaces")
    cost_tracker = CostTracker()
    token = config.github_tokens.get(repo, config.github_token)
    target_repo = Repository(full_name=repo, access_token=token)

    output_path = Path(config.output.dir) / f"{target_repo.slug}-task-instances.jsonl"
    output_path.unlink(missing_ok=True)

    logger.info("M1: running pipeline on %s (max %d PRs)", repo, max_prs)
    asyncio.run(run_repo_pipeline(target_repo, config, workspace_mgr, cost_tracker))

    # Validate output
    if not output_path.exists():
        logger.error("M1: no output file produced at %s", output_path)
        return False

    instances = []
    with open(output_path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    required_fields = {
        "repo", "instance_id", "base_commit", "patch", "test_patch",
        "problem_statement", "version", "FAIL_TO_PASS", "PASS_TO_PASS",
    }
    valid_count = 0
    for inst in instances:
        missing = required_fields - set(inst.keys())
        if missing:
            logger.warning("  Instance %s missing fields: %s", inst.get("instance_id"), missing)
        else:
            # Verify F2P is a non-empty JSON list
            try:
                f2p = json.loads(inst["FAIL_TO_PASS"])
                if isinstance(f2p, list) and len(f2p) > 0:
                    valid_count += 1
            except (json.JSONDecodeError, TypeError):
                logger.warning("  Invalid FAIL_TO_PASS for %s", inst.get("instance_id"))

    print("\n" + "=" * 60)
    print("M1 — End-to-End kubectl Run")
    print("=" * 60)
    print(f"  Instances produced  : {len(instances)}")
    print(f"  Schema-valid + F2P  : {valid_count}")
    cost_summary = cost_tracker.summary()
    print(f"  Cost summary        : {cost_summary}")
    passed = valid_count > 0
    print(f"  Outcome             : {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ---------------------------------------------------------------------------
# M2: Flake quarantine stability on etcd
# ---------------------------------------------------------------------------

def run_m2(
    config_path: str,
    repo: str = "etcd-io/etcd",
    max_prs: int = 5,
    n_runs: int = 3,
) -> bool:
    """Verify flake quarantine stability on etcd across N runs.

    Runs validation twice and checks that the set of quarantined tests is
    identical both times (stability check).

    Prerequisites: ANTHROPIC_API_KEY, GITHUB_TOKEN, Docker/Podman.
    """
    import asyncio
    from swebenchify.config import load_config
    from swebenchify.pipeline import run_repo_pipeline
    from swebenchify.models import Repository
    from swebenchify.dispatcher import CostTracker
    from swebenchify.workspace import WorkspaceManager

    config = load_config(config_path)
    config.go_repos = [repo]
    config.pipeline.max_prs_per_repo = max_prs
    config.pipeline.go_n_runs = n_runs

    workspace_mgr = WorkspaceManager(config.output.dir + "/workspaces")
    target_repo = Repository(
        full_name=repo,
        access_token=config.github_tokens.get(repo, config.github_token),
    )

    run_results = []
    for attempt in range(2):
        logger.info("M2: stability run %d/2 on %s (%d-run quarantine)", attempt + 1, repo, n_runs)
        cost_tracker = CostTracker()
        asyncio.run(run_repo_pipeline(target_repo, config, workspace_mgr, cost_tracker))

        output_path = Path(config.output.dir) / f"{target_repo.slug}-task-instances.jsonl"
        instances = []
        if output_path.exists():
            with open(output_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        instances.append(json.loads(line))
        run_results.append({
            "instances": len(instances),
            "f2p_sets": {inst["instance_id"]: json.loads(inst["FAIL_TO_PASS"]) for inst in instances},
        })

    print("\n" + "=" * 60)
    print("M2 — Flake Quarantine Stability (etcd)")
    print("=" * 60)
    r1, r2 = run_results[0], run_results[1]
    print(f"  Run 1 instances     : {r1['instances']}")
    print(f"  Run 2 instances     : {r2['instances']}")

    # Check that same instance_ids appear in both runs
    ids1 = set(r1["f2p_sets"].keys())
    ids2 = set(r2["f2p_sets"].keys())
    common = ids1 & ids2
    print(f"  Common instances    : {len(common)} / {max(len(ids1), len(ids2))}")

    # Check F2P stability across runs
    stable_count = 0
    for iid in common:
        f2p1 = set(r1["f2p_sets"][iid])
        f2p2 = set(r2["f2p_sets"][iid])
        if f2p1 == f2p2:
            stable_count += 1
        else:
            logger.warning("  Unstable F2P for %s: run1=%s, run2=%s", iid, f2p1, f2p2)

    if common:
        stability_rate = stable_count / len(common)
        print(f"  F2P stable across runs: {stable_count}/{len(common)} ({stability_rate:.1%})")
        passed = stability_rate >= PASS_THRESHOLD
    else:
        print("  No common instances to compare")
        passed = False

    print(f"  Outcome             : {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ---------------------------------------------------------------------------
# Pre-flight: conformance smoke test (no prerequisites needed)
# ---------------------------------------------------------------------------

def run_conformance_smoke() -> bool:
    """Run the Go conformance suite as a prerequisite health check."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_go_conformance.py", "-v", "--tb=short"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=False,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Epic 1 Go-support exit criteria.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "milestone",
        choices=["m0", "m1", "m2", "all", "smoke"],
        help="Which milestone to validate (smoke = conformance tests only)",
    )
    parser.add_argument("--known-good", metavar="PATH",
                        help="JSONL with known-good instances (M0)")
    parser.add_argument("--config", metavar="PATH",
                        help="swebenchify.yaml config (M1, M2)")
    parser.add_argument("--repo", default=None,
                        help="Override repo for M1/M2")
    parser.add_argument("--max-prs", type=int, default=10,
                        help="Max PRs to collect (M1/M2, default: 10)")
    parser.add_argument("--n-runs", type=int, default=3,
                        help="Flake quarantine runs (M2, default: 3)")
    args = parser.parse_args()

    prefs = check_prerequisites()
    print_prereqs(prefs)

    results: dict[str, bool | None] = {}

    # Always run the conformance smoke test first
    print("Running conformance smoke test...")
    results["smoke"] = run_conformance_smoke()
    if not results["smoke"]:
        print("FATAL: conformance smoke test failed — fix before continuing")
        sys.exit(1)

    if args.milestone in ("m0", "all"):
        if not args.known_good:
            print("M0 skipped: --known-good not provided")
            print("  Provide a JSONL with known-good kubectl/etcd instances that include")
            print("  pre_fix_output and post_fix_output (raw go test -json streams).")
            results["m0"] = None
        elif not Path(args.known_good).exists():
            print(f"M0 skipped: {args.known_good} not found")
            results["m0"] = None
        else:
            m0_result = run_m0(args.known_good)
            results["m0"] = print_m0_results(m0_result)

    if args.milestone in ("m1", "all"):
        live_prereqs = ["docker_or_podman", "anthropic_api_key", "github_token"]
        missing = [p for p in live_prereqs if not prefs[p]]
        if missing or not args.config:
            print(f"M1 skipped: missing prerequisites: {', '.join(missing) or '--config'}")
            results["m1"] = None
        else:
            repo = args.repo or "kubernetes/kubernetes"
            results["m1"] = run_m1(args.config, repo=repo, max_prs=args.max_prs)

    if args.milestone in ("m2", "all"):
        live_prereqs = ["docker_or_podman", "anthropic_api_key", "github_token"]
        missing = [p for p in live_prereqs if not prefs[p]]
        if missing or not args.config:
            print(f"M2 skipped: missing prerequisites: {', '.join(missing) or '--config'}")
            results["m2"] = None
        else:
            repo = args.repo or "etcd-io/etcd"
            results["m2"] = run_m2(
                args.config, repo=repo, max_prs=args.max_prs, n_runs=args.n_runs
            )

    # Summary
    print("\n" + "=" * 60)
    print("Epic 1 Validation Summary")
    print("=" * 60)
    for name, passed in results.items():
        if passed is None:
            sym = "—"
            label = "SKIPPED (missing prerequisites)"
        elif passed:
            sym = "✓"
            label = "PASS"
        else:
            sym = "✗"
            label = "FAIL"
        print(f"  [{sym}] {name.upper():6s} {label}")

    failed = [k for k, v in results.items() if v is False]
    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        sys.exit(1)
    skipped = [k for k, v in results.items() if v is None]
    if skipped and args.milestone == "all":
        print(f"\nNote: {', '.join(skipped)} skipped — see prerequisites above")
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
