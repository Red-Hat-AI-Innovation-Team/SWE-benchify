"""Compare SWE-benchify vs SWE-Smith: judge evasion + difficulty.

Reads eval results and judge evasion results, produces comparison tables
with statistical significance tests and LaTeX output.

Usage:
    python3 scripts/compare_swesmith.py \
        --judge-results data/judge-evasion-results.jsonl \
        --swebenchify-eval data/eval-results-{haiku,sonnet,opus}-saved.jsonl \
        --swesmith-eval data/eval-results-swesmith-{haiku,sonnet,opus}.jsonl \
        --output data/comparison-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict


def load_jsonl(path: str) -> list[dict]:
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


def fishers_exact_test(a: int, b: int, c: int, d: int) -> float:
    """Fisher's exact test p-value for a 2x2 contingency table.

    [[a, b], [c, d]] where:
    - a = system1 successes, b = system1 failures
    - c = system2 successes, d = system2 failures
    """
    try:
        from scipy.stats import fisher_exact
        _, p = fisher_exact([[a, b], [c, d]])
        return p
    except ImportError:
        from math import comb, log
        n = a + b + c + d
        def log_hypergeom(x):
            return (log(comb(a + b, x)) + log(comb(c + d, a + c - x))
                    - log(comb(n, a + c)))
        observed = log_hypergeom(a)
        p = 0.0
        for x in range(min(a + b, a + c) + 1):
            if log_hypergeom(x) <= observed + 1e-10:
                from math import exp
                p += exp(log_hypergeom(x))
        return min(p, 1.0)


def analyze_judge_evasion(judge_results: list[dict]) -> dict:
    """Analyze judge evasion results."""
    by_source_run = defaultdict(lambda: defaultdict(list))
    for r in judge_results:
        by_source_run[r["source"]][r["run"]].append(r)

    metrics = {}
    for source in ["swesmith", "swebenchify", "real_python", "real_go"]:
        runs = by_source_run.get(source, {})
        if not runs:
            continue

        run_rates = []
        for run_idx, results in sorted(runs.items()):
            n = len(results)
            if source in ("swesmith", "swebenchify"):
                evaded = sum(1 for r in results if r["classification"] == "REAL")
                run_rates.append(evaded / n if n else 0)
            else:
                correct = sum(1 for r in results if r["classification"] == "REAL")
                run_rates.append(correct / n if n else 0)

        mean = sum(run_rates) / len(run_rates)
        std = (sum((r - mean) ** 2 for r in run_rates) / len(run_rates)) ** 0.5

        conf_dist = defaultdict(int)
        all_results = [r for rs in runs.values() for r in rs]
        for r in all_results:
            conf_dist[r["confidence"]] += 1

        metrics[source] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "n_per_run": len(next(iter(runs.values()))),
            "n_runs": len(runs),
            "confidence_dist": dict(conf_dist),
        }

    # Statistical test: SWE-benchify evasion vs SWE-Smith evasion
    if "swesmith" in metrics and "swebenchify" in metrics:
        sw_all = [r for rs in by_source_run["swesmith"].values() for r in rs]
        sb_all = [r for rs in by_source_run["swebenchify"].values() for r in rs]
        sw_evaded = sum(1 for r in sw_all if r["classification"] == "REAL")
        sw_detected = len(sw_all) - sw_evaded
        sb_evaded = sum(1 for r in sb_all if r["classification"] == "REAL")
        sb_detected = len(sb_all) - sb_evaded
        p = fishers_exact_test(sb_evaded, sb_detected, sw_evaded, sw_detected)
        metrics["comparison"] = {
            "swebenchify_evasion": round(sb_evaded / len(sb_all), 4),
            "swesmith_evasion": round(sw_evaded / len(sw_all), 4),
            "fishers_p": round(p, 6),
            "significant_at_005": p < 0.05,
        }

    return metrics


def analyze_difficulty(swebenchify_results: dict, swesmith_results: dict) -> dict:
    """Analyze difficulty comparison across models."""
    models = sorted(set(list(swebenchify_results.keys()) + list(swesmith_results.keys())))

    metrics = {}
    for model in models:
        sb = swebenchify_results.get(model, [])
        sw = swesmith_results.get(model, [])

        sb_n = len(sb)
        sb_resolved = sum(1 for r in sb if r.get("resolved"))
        sw_n = len(sw)
        sw_resolved = sum(1 for r in sw if r.get("resolved"))

        sb_rate = sb_resolved / sb_n if sb_n else 0
        sw_rate = sw_resolved / sw_n if sw_n else 0

        p = fishers_exact_test(sb_resolved, sb_n - sb_resolved, sw_resolved, sw_n - sw_resolved) if sb_n and sw_n else 1.0

        metrics[model] = {
            "swebenchify": {"resolved": sb_resolved, "total": sb_n, "rate": round(sb_rate, 4)},
            "swesmith": {"resolved": sw_resolved, "total": sw_n, "rate": round(sw_rate, 4)},
            "difference": round(sw_rate - sb_rate, 4),
            "fishers_p": round(p, 6),
            "significant_at_005": p < 0.05,
        }

    return metrics


def print_report(judge_metrics: dict | None, difficulty_metrics: dict | None):
    """Print formatted comparison report."""
    print("=" * 70)
    print("  SWE-benchify vs SWE-Smith Comparison Report")
    print("=" * 70)

    if judge_metrics:
        print("\n--- Judge Evasion (higher = more realistic) ---\n")
        print(f"{'System':<30s} {'Evasion/Accuracy':>16s} {'Std':>8s} {'N':>6s}")
        print("-" * 62)
        for source in ["swebenchify", "swesmith", "real_python", "real_go"]:
            m = judge_metrics.get(source, {})
            if not m:
                continue
            label = {
                "swebenchify": "SWE-benchify (synthetic)",
                "swesmith": "SWE-Smith (synthetic)",
                "real_python": "Real Python (control)",
                "real_go": "Real Go (control)",
            }[source]
            print(f"{label:<30s} {100*m['mean']:>15.1f}% {100*m['std']:>7.1f}% {m['n_per_run']*m['n_runs']:>6d}")

        comp = judge_metrics.get("comparison", {})
        if comp:
            print(f"\nFisher's exact test: p = {comp['fishers_p']:.4f}"
                  f" {'(significant)' if comp['significant_at_005'] else '(not significant)'}")

    if difficulty_metrics:
        print("\n--- Difficulty (lower resolve rate = harder) ---\n")
        print(f"{'Model':<10s} {'SWE-benchify':>20s} {'SWE-Smith':>20s} {'Diff':>8s} {'p-value':>10s}")
        print("-" * 70)
        for model, m in sorted(difficulty_metrics.items()):
            sb = m["swebenchify"]
            sw = m["swesmith"]
            sig = "*" if m["significant_at_005"] else ""
            print(f"{model:<10s} {sb['resolved']:>4d}/{sb['total']:<4d} ({100*sb['rate']:>5.1f}%)"
                  f" {sw['resolved']:>4d}/{sw['total']:<4d} ({100*sw['rate']:>5.1f}%)"
                  f" {100*m['difference']:>+7.1f}% {m['fishers_p']:>9.4f}{sig}")


def generate_latex(judge_metrics: dict | None, difficulty_metrics: dict | None) -> str:
    """Generate LaTeX tables for the paper."""
    lines = []

    if judge_metrics:
        lines.append("% Judge Evasion Table")
        lines.append("\\begin{table}[h]")
        lines.append("\\centering")
        lines.append("\\begin{tabular}{lrr}")
        lines.append("\\toprule")
        lines.append("System & Evasion Rate & Std \\\\")
        lines.append("\\midrule")
        for source in ["swebenchify", "swesmith"]:
            m = judge_metrics.get(source, {})
            if not m:
                continue
            label = "SWE-benchify" if source == "swebenchify" else "SWE-Smith"
            lines.append(f"{label} & {100*m['mean']:.1f}\\% & $\\pm${100*m['std']:.1f}\\% \\\\")
        lines.append("\\bottomrule")
        lines.append("\\end{tabular}")
        comp = judge_metrics.get("comparison", {})
        if comp:
            lines.append(f"\\caption{{Judge evasion rates. Fisher's exact test $p = {comp['fishers_p']:.4f}$.}}")
        lines.append("\\end{table}")

    if difficulty_metrics:
        lines.append("")
        lines.append("% Difficulty Table")
        lines.append("\\begin{table}[h]")
        lines.append("\\centering")
        lines.append("\\begin{tabular}{lrrr}")
        lines.append("\\toprule")
        lines.append("Model & SWE-benchify & SWE-Smith & $p$ \\\\")
        lines.append("\\midrule")
        for model, m in sorted(difficulty_metrics.items()):
            sb = m["swebenchify"]
            sw = m["swesmith"]
            sig = "$^*$" if m["significant_at_005"] else ""
            lines.append(f"{model.capitalize()} & {100*sb['rate']:.1f}\\% & {100*sw['rate']:.1f}\\% & {m['fishers_p']:.4f}{sig} \\\\")
        lines.append("\\bottomrule")
        lines.append("\\end{tabular}")
        lines.append("\\caption{Resolve rates by model. Lower = harder. $^*$: $p < 0.05$.}")
        lines.append("\\end{table}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SWE-benchify vs SWE-Smith comparison")
    parser.add_argument("--judge-results", type=str, help="Judge evasion results JSONL")
    parser.add_argument("--swebenchify-eval", nargs="+", help="SWE-benchify eval result JSONL files")
    parser.add_argument("--swesmith-eval", nargs="+", help="SWE-Smith eval result JSONL files")
    parser.add_argument("--output", type=str, default="data/comparison-report.json")
    parser.add_argument("--latex", type=str, default=None, help="Output LaTeX tables to file")
    args = parser.parse_args()

    judge_metrics = None
    difficulty_metrics = None

    if args.judge_results and os.path.exists(args.judge_results):
        judge_results = load_jsonl(args.judge_results)
        judge_metrics = analyze_judge_evasion(judge_results)

    if args.swebenchify_eval and args.swesmith_eval:
        sb_results = {}
        for path in args.swebenchify_eval:
            results = load_jsonl(path)
            if results:
                model = results[0].get("model", "unknown")
                sb_results[model] = results

        sw_results = {}
        for path in args.swesmith_eval:
            if not os.path.exists(path):
                continue
            results = load_jsonl(path)
            if results:
                model = results[0].get("model", "unknown")
                sw_results[model] = results

        if sb_results and sw_results:
            difficulty_metrics = analyze_difficulty(sb_results, sw_results)

    print_report(judge_metrics, difficulty_metrics)

    if args.latex:
        latex = generate_latex(judge_metrics, difficulty_metrics)
        with open(args.latex, "w") as f:
            f.write(latex)
        print(f"\nLaTeX tables saved to {args.latex}", file=sys.stderr)

    report = {}
    if judge_metrics:
        report["judge_evasion"] = judge_metrics
    if difficulty_metrics:
        report["difficulty"] = difficulty_metrics
    if report:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
