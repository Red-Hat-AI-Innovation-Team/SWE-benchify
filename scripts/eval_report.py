"""Multi-model eval report generator.

Reads eval result JSONL files for each model and produces a summary with:
- Per-model resolve rates
- Per-repo breakdown
- Hardest instances (solved by 0 models)
- Easiest instances (solved by all models)

Usage:
    python3 scripts/eval_report.py                                    # Auto-detect latest results
    python3 scripts/eval_report.py --timestamp 20260728-143000        # Specific run
    python3 scripts/eval_report.py --files data/eval-results-haiku.jsonl data/eval-results-sonnet.jsonl
    python3 scripts/eval_report.py --output data/eval-summary.json    # Save JSON report
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

MODELS = ["haiku", "sonnet", "opus"]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def load_results(path: str) -> list[dict]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


def find_result_files(timestamp: str | None = None) -> dict[str, str]:
    found = {}
    for model in MODELS:
        if timestamp:
            pattern = os.path.join(DATA_DIR, f"eval-results-{model}-{timestamp}.jsonl")
        else:
            pattern = os.path.join(DATA_DIR, f"eval-results-{model}*.jsonl")
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            found[model] = matches[0]
    return found


def generate_report(model_files: dict[str, str]) -> dict:
    model_results: dict[str, list[dict]] = {}
    for model, path in model_files.items():
        model_results[model] = load_results(path)

    instance_models: dict[str, dict[str, bool]] = defaultdict(dict)
    instance_repos: dict[str, str] = {}
    for model, results in model_results.items():
        for r in results:
            iid = r.get("instance_id", "")
            instance_models[iid][model] = r.get("resolved", False)
            repo = r.get("repo", "")
            if not repo and "-" in iid:
                parts = iid.rsplit("-", 1)[0]
                parts2 = parts.split("-", 1)
                if len(parts2) == 2:
                    repo = f"{parts2[0]}/{parts2[1]}"
            instance_repos[iid] = repo or "unknown"

    per_model = {}
    for model, results in model_results.items():
        n = len(results)
        resolved = sum(1 for r in results if r.get("resolved"))
        per_model[model] = {
            "total": n,
            "resolved": resolved,
            "failed": n - resolved,
            "resolve_rate": round(resolved / n, 4) if n else 0,
            "failure_rate": round((n - resolved) / n, 4) if n else 0,
            "source_file": model_files[model],
        }

    per_repo: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"total": 0, "resolved": 0}))
    for model, results in model_results.items():
        for r in results:
            iid = r.get("instance_id", "")
            repo = instance_repos.get(iid, "unknown")
            per_repo[repo][model]["total"] += 1
            if r.get("resolved"):
                per_repo[repo][model]["resolved"] += 1

    models_evaluated = list(model_results.keys())

    solved_by_none = []
    solved_by_all = []
    for iid, model_status in instance_models.items():
        n_solved = sum(1 for v in model_status.values() if v)
        if n_solved == 0:
            solved_by_none.append(iid)
        if n_solved == len(models_evaluated) and len(models_evaluated) == len(model_status):
            solved_by_all.append(iid)

    per_repo_summary = {}
    for repo, model_data in sorted(per_repo.items()):
        per_repo_summary[repo] = {}
        for model in models_evaluated:
            d = model_data[model]
            t, r = d["total"], d["resolved"]
            per_repo_summary[repo][model] = {
                "resolved": r,
                "total": t,
                "rate": round(r / t, 4) if t else 0,
            }

    return {
        "models_evaluated": models_evaluated,
        "per_model": per_model,
        "per_repo": per_repo_summary,
        "difficulty_analysis": {
            "solved_by_no_model": len(solved_by_none),
            "solved_by_all_models": len(solved_by_all),
            "hardest_instance_ids": sorted(solved_by_none)[:20],
            "easiest_instance_ids": sorted(solved_by_all)[:20],
        },
    }


def print_report(report: dict):
    models = report["models_evaluated"]

    print("=" * 70)
    print("  Multi-Model Eval Report")
    print("=" * 70)
    print()

    header = f"{'Model':>8s}  {'Resolved':>8s}  {'Total':>6s}  {'Resolve %':>9s}  {'Failure %':>9s}"
    print(header)
    print("-" * len(header))
    for model in models:
        d = report["per_model"][model]
        print(f"{model:>8s}  {d['resolved']:>8d}  {d['total']:>6d}  {100*d['resolve_rate']:>8.1f}%  {100*d['failure_rate']:>8.1f}%")

    print()
    print("Per-Repo Breakdown (resolve rate %)")
    print("-" * 70)
    repo_header = f"{'Repo':<45s}"
    for m in models:
        repo_header += f"  {m:>8s}"
    print(repo_header)
    print("-" * 70)
    for repo, model_data in sorted(report["per_repo"].items()):
        row = f"{repo:<45s}"
        for m in models:
            d = model_data.get(m, {})
            r, t = d.get("resolved", 0), d.get("total", 0)
            if t > 0:
                row += f"  {100*r/t:>7.0f}%"
            else:
                row += f"  {'n/a':>8s}"
        print(row)

    print()
    da = report["difficulty_analysis"]
    print(f"Solved by no model:   {da['solved_by_no_model']}")
    print(f"Solved by all models: {da['solved_by_all_models']}")
    if da["hardest_instance_ids"]:
        print(f"Hardest (sample):     {', '.join(da['hardest_instance_ids'][:5])}")


def main():
    parser = argparse.ArgumentParser(description="Multi-model eval report")
    parser.add_argument("--timestamp", type=str, help="Run timestamp (e.g. 20260728-143000)")
    parser.add_argument("--files", nargs="+", help="Explicit result JSONL files (auto-detects model from content)")
    parser.add_argument("--output", type=str, help="Save JSON report to file")
    args = parser.parse_args()

    if args.files:
        model_files = {}
        for path in args.files:
            results = load_results(path)
            if results:
                model = results[0].get("model", "unknown")
                model_files[model] = path
    else:
        model_files = find_result_files(args.timestamp)

    if not model_files:
        print("No eval result files found. Run the pipeline first or specify --files.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading results for: {', '.join(model_files.keys())}", file=sys.stderr)
    for model, path in model_files.items():
        print(f"  {model}: {path}", file=sys.stderr)

    report = generate_report(model_files)
    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nJSON report saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
