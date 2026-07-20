#!/usr/bin/env python3
"""Compare Harbor evaluation results across multiple agent/model runs.

Scans the Harbor jobs directory for completed runs and produces a
comparison table showing resolve rates, cost, and timing per model.

Usage:
    python scripts/compare_harbor_runs.py --jobs-dir jobs
    python scripts/compare_harbor_runs.py --jobs-dir jobs --csv results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Harbor evaluation runs")
    parser.add_argument("--jobs-dir", default="jobs", help="Path to Harbor jobs directory")
    parser.add_argument("--csv", default=None, help="Optional CSV output path")
    parser.add_argument("--include", nargs="*", help="Only include these job names")
    parser.add_argument("--exclude", nargs="*", help="Exclude these job names")
    return parser.parse_args()


def _parse_trial(trial_dir: Path) -> dict | None:
    result_file = trial_dir / "result.json"
    if not result_file.exists():
        return None

    result = json.loads(result_file.read_text())

    reward = (
        result.get("verifier_result", {})
        .get("rewards", {})
        .get("reward", 0.0)
    )

    agent_result = result.get("agent_result", {})
    cost = agent_result.get("cost_usd", 0.0)
    input_tokens = agent_result.get("n_input_tokens", 0)
    output_tokens = agent_result.get("n_output_tokens", 0)

    start = result.get("started_at", "")
    end = result.get("finished_at", "")
    duration = 0
    if start and end:
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration = int((e - s).total_seconds())
        except (ValueError, TypeError):
            pass

    config_file = trial_dir / "config.json"
    agent_name = "unknown"
    model_name = "unknown"
    if config_file.exists():
        config = json.loads(config_file.read_text())
        agent_name = config.get("agent", {}).get("name", "unknown")
        model_name = config.get("agent", {}).get("model_name", "unknown")

    task_name = result.get("task_name", trial_dir.name)
    instance_id = trial_dir.name.rsplit("__", 1)[0] if "__" in trial_dir.name else trial_dir.name

    exception_file = trial_dir / "exception.txt"
    has_exception = exception_file.exists()

    trajectory_file = trial_dir / "agent" / "trajectory.json"
    if trajectory_file.exists() and cost == 0:
        try:
            traj = json.loads(trajectory_file.read_text())
            metrics = traj.get("final_metrics", {})
            cost = metrics.get("total_cost_usd", cost)
            input_tokens = metrics.get("total_prompt_tokens", input_tokens)
            output_tokens = metrics.get("total_completion_tokens", output_tokens)
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "instance_id": instance_id,
        "task_name": task_name,
        "agent": agent_name,
        "model": model_name,
        "reward": reward,
        "resolved": reward >= 1.0,
        "cost_usd": cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_s": duration,
        "has_exception": has_exception,
    }


def load_all_trials(jobs_dir: Path, include: list[str] | None, exclude: list[str] | None) -> list[dict]:
    trials = []
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        job_name = job_dir.name
        if include and job_name not in include:
            continue
        if exclude and job_name in exclude:
            continue
        if job_name.startswith("oracle") or job_name.startswith("nop"):
            continue

        for trial_dir in sorted(job_dir.iterdir()):
            if not trial_dir.is_dir():
                continue
            if trial_dir.name == "result.json":
                continue
            trial = _parse_trial(trial_dir)
            if trial:
                trial["job_name"] = job_name
                trials.append(trial)
    return trials


def _clean_model(model: str) -> str:
    for prefix in ("vertex_ai/", "bedrock/", "anthropic/", "openai/"):
        model = model.replace(prefix, "")
    return model


def print_comparison(trials: list[dict], csv_path: str | None = None) -> None:
    by_model: dict[str, list[dict]] = {}
    for t in trials:
        key = f"{t['agent']}/{_clean_model(t['model'])}"
        by_model.setdefault(key, []).append(t)

    all_instances = sorted({t["instance_id"] for t in trials})
    models = sorted(by_model.keys())

    if not models:
        print("No trial results found.")
        return

    instance_results: dict[str, dict[str, dict]] = {}
    for instance in all_instances:
        instance_results[instance] = {}
        for model in models:
            matching = [t for t in by_model[model] if t["instance_id"] == instance]
            if matching:
                instance_results[instance][model] = matching[0]

    max_inst_len = max(len(i) for i in all_instances)
    model_col_width = max(max(len(m) for m in models), 10)

    header = f"{'Instance':<{max_inst_len}}"
    for m in models:
        header += f"  {m:>{model_col_width}}"
    print(header)
    print("-" * len(header))

    for instance in all_instances:
        row = f"{instance:<{max_inst_len}}"
        for model in models:
            trial = instance_results[instance].get(model)
            if trial:
                mark = "PASS" if trial["resolved"] else "FAIL"
                row += f"  {mark:>{model_col_width}}"
            else:
                row += f"  {'—':>{model_col_width}}"
        print(row)

    print("-" * len(header))

    resolve_row = f"{'Resolve rate':<{max_inst_len}}"
    cost_row = f"{'Avg cost ($)':<{max_inst_len}}"
    time_row = f"{'Avg time (s)':<{max_inst_len}}"
    exc_row = f"{'Exceptions':<{max_inst_len}}"

    for model in models:
        model_trials = by_model[model]
        resolved = sum(1 for t in model_trials if t["resolved"])
        total = len(model_trials)
        rate = f"{resolved}/{total} ({resolved/total*100:.0f}%)" if total else "n/a"
        resolve_row += f"  {rate:>{model_col_width}}"

        costs = [t["cost_usd"] for t in model_trials if t["cost_usd"] > 0]
        avg_cost = f"${sum(costs)/len(costs):.2f}" if costs else "n/a"
        cost_row += f"  {avg_cost:>{model_col_width}}"

        times = [t["duration_s"] for t in model_trials if t["duration_s"] > 0]
        avg_time = f"{sum(times)/len(times):.0f}" if times else "n/a"
        time_row += f"  {avg_time:>{model_col_width}}"

        exceptions = sum(1 for t in model_trials if t["has_exception"])
        exc_row += f"  {str(exceptions):>{model_col_width}}"

    print(resolve_row)
    print(cost_row)
    print(time_row)
    print(exc_row)

    print()
    n_models = len(models)
    easy = [i for i in all_instances if all(
        instance_results[i].get(m, {}).get("resolved", False) for m in models
    )]
    hard = [i for i in all_instances if not any(
        instance_results[i].get(m, {}).get("resolved", False) for m in models
    )]
    separating = [i for i in all_instances if i not in easy and i not in hard]

    if easy:
        print(f"Easy (solved by all {n_models} models): {', '.join(easy)}")
    if hard:
        print(f"Hard (solved by none): {', '.join(hard)}")
    if separating:
        print(f"Separating ({len(separating)} instances create model differentiation)")

    if csv_path:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "job_name", "instance_id", "agent", "model",
                "resolved", "reward", "cost_usd", "duration_s",
                "input_tokens", "output_tokens", "has_exception",
            ])
            writer.writeheader()
            for t in trials:
                writer.writerow(t)
        print(f"\nCSV written to {csv_path}")


def main() -> None:
    args = parse_args()
    jobs_dir = Path(args.jobs_dir)
    if not jobs_dir.is_dir():
        print(f"Jobs directory not found: {jobs_dir}", file=sys.stderr)
        sys.exit(1)

    trials = load_all_trials(jobs_dir, args.include, args.exclude)
    if not trials:
        print("No trials found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(trials)} trials across {len({t['job_name'] for t in trials})} jobs\n")
    print_comparison(trials, args.csv)


if __name__ == "__main__":
    main()
