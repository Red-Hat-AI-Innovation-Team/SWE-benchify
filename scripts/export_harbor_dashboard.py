#!/usr/bin/env python3
"""Export Harbor job results to swe-routing-eval dashboard data.json format."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Harbor job results to dashboard data.json"
    )
    parser.add_argument(
        "--jobs", required=True, help="Path to Harbor jobs directory"
    )
    parser.add_argument(
        "--instances",
        required=True,
        help="Path to task-instances JSONL file",
    )
    parser.add_argument(
        "--output", required=True, help="Path to write data.json"
    )
    return parser.parse_args()


def load_instances(path: str) -> dict[str, dict[str, Any]]:
    instances: dict[str, dict[str, Any]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            iid = record["instance_id"]
            f2p_raw = record.get("FAIL_TO_PASS", "[]")
            if isinstance(f2p_raw, str):
                f2p_raw = json.loads(f2p_raw)
            instances[iid] = {
                "repo": record["repo"],
                "language": record.get("repo_language", "unknown"),
                "patch_lines": record.get("patch_lines", 0),
                "files_touched": record.get("files_touched", 0),
                "cross_file": record.get("cross_file", False),
                "n_fail_to_pass": record.get("n_fail_to_pass", len(f2p_raw)),
                "issue_url": _build_issue_url(record),
                "fix_merge_date": record.get("fix_merge_date"),
                "human_patch": record.get("patch", ""),
            }
    return instances


def _build_issue_url(record: dict[str, Any]) -> str:
    repo = record.get("repo", "")
    iid = record.get("instance_id", "")
    m = re.search(r"-(\d+)$", iid)
    if m and repo:
        return f"https://github.com/{repo}/issues/{m.group(1)}"
    return ""


def parse_instance_id(task_name: str) -> tuple[str, str]:
    """Extract language and instance_id from task_name like 'swebenchify/go__etcd-io__etcd-19086'."""
    prefix = "swebenchify/"
    if task_name.startswith(prefix):
        rest = task_name[len(prefix) :]
    else:
        rest = task_name
    parts = rest.split("__", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "unknown", rest


def make_model_key(agent_name: str, model_name: str | None) -> str:
    if model_name:
        clean_model = model_name.replace("vertex_ai/", "").replace(
            "bedrock/", ""
        )
        return f"{agent_name}__{clean_model}"
    return f"{agent_name}__adhoc"


def load_test_config(task_path: str) -> dict[str, list[str]]:
    """Load FAIL_TO_PASS and PASS_TO_PASS from the task's tests/config.json."""
    config_path = os.path.join(task_path, "tests", "config.json")
    if not os.path.isfile(config_path):
        return {"f2p": [], "p2p": []}
    with open(config_path) as f:
        cfg = json.load(f)
    f2p = cfg.get("FAIL_TO_PASS", "[]")
    if isinstance(f2p, str):
        f2p = json.loads(f2p)
    p2p = cfg.get("PASS_TO_PASS", "[]")
    if isinstance(p2p, str):
        p2p = json.loads(p2p)
    return {"f2p": f2p, "p2p": p2p}


def build_per_test_results(
    test_names: list[str],
    report_results: dict[str, str],
) -> list[dict[str, Any]]:
    """Build per-test result entries [{n: name, p: passed}]."""
    entries = []
    for name in test_names:
        status = report_results.get(name, "")
        passed = status in ("pass", "passed")
        entries.append({"n": name, "p": passed})
    return entries


def read_candidate_patch(trial_dir: str) -> str | None:
    for candidate in [
        os.path.join(
            trial_dir, "artifacts", "logs", "artifacts", "candidate_patch.diff"
        ),
        os.path.join(trial_dir, "artifacts", "candidate_patch.diff"),
    ]:
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            with open(candidate) as f:
                return f.read()
    return None


def compute_wall_seconds(
    started_at: str | None, finished_at: str | None
) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        fmt_candidates = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
        ]
        t_start = t_end = None
        for fmt in fmt_candidates:
            try:
                t_start = datetime.strptime(started_at, fmt)
                break
            except ValueError:
                continue
        for fmt in fmt_candidates:
            try:
                t_end = datetime.strptime(finished_at, fmt)
                break
            except ValueError:
                continue
        if t_start and t_end:
            return round((t_end - t_start).total_seconds(), 1)
    except Exception:
        pass
    return None


def process_trial(
    trial_dir: str,
    task_path: str,
) -> dict[str, Any] | None:
    """Process a single trial directory into a run entry."""
    trial_config_path = os.path.join(trial_dir, "config.json")
    trial_result_path = os.path.join(trial_dir, "result.json")

    if not os.path.isfile(trial_result_path):
        return None

    with open(trial_result_path) as f:
        trial_result = json.load(f)

    task_name = trial_result.get("task_name", "")
    _, instance_id = parse_instance_id(task_name)

    agent_name = "unknown"
    model_name = None
    if os.path.isfile(trial_config_path):
        with open(trial_config_path) as f:
            trial_config = json.load(f)
        agent_cfg = trial_config.get("agent", {})
        agent_name = agent_cfg.get("name", "unknown")
        model_name = agent_cfg.get("model_name")

    model_key = make_model_key(agent_name, model_name)

    report_results: dict[str, str] = {}
    report_path = os.path.join(trial_dir, "verifier", "report.json")
    if os.path.isfile(report_path):
        with open(report_path) as f:
            report = json.load(f)
        report_results = report.get("test_results", {})

    test_config = load_test_config(task_path)

    reward_val = 0.0
    verifier_result = trial_result.get("verifier_result", {})
    if verifier_result:
        rewards = verifier_result.get("rewards", {})
        reward_val = rewards.get("reward", 0.0)
    resolved = reward_val >= 1.0

    f2p_results = build_per_test_results(test_config["f2p"], report_results)
    p2p_results = build_per_test_results(test_config["p2p"], report_results)

    all_f2p_pass = all(e["p"] for e in f2p_results) if f2p_results else False

    total_input = 0
    total_output = 0
    total_cost: float | None = None
    n_steps = 0
    tool_calls = 0

    trajectory_path = os.path.join(trial_dir, "agent", "trajectory.json")
    if os.path.isfile(trajectory_path):
        with open(trajectory_path) as f:
            traj = json.load(f)
        fm = traj.get("final_metrics", {})
        total_input = fm.get("total_prompt_tokens", 0)
        total_output = fm.get("total_completion_tokens", 0)
        total_cost = fm.get("total_cost_usd")
        steps = traj.get("steps", [])
        n_steps = len(steps)
        tool_calls = sum(
            1 for s in steps if s.get("source") == "agent"
        )

    agent_result = trial_result.get("agent_result", {})
    if agent_result:
        if not total_input and agent_result.get("n_input_tokens"):
            total_input = agent_result["n_input_tokens"]
        if not total_output and agent_result.get("n_output_tokens"):
            total_output = agent_result["n_output_tokens"]
        if total_cost is None and agent_result.get("cost_usd") is not None:
            total_cost = agent_result["cost_usd"]

    wall = compute_wall_seconds(
        trial_result.get("started_at"), trial_result.get("finished_at")
    )

    patch = read_candidate_patch(trial_dir)

    cli = agent_name not in ("terminus-2", "oracle")

    entry: dict[str, Any] = {
        "a": 0,
        "r": resolved,
        "c": all_f2p_pass,
        "f2p": f2p_results,
        "p2p": p2p_results,
        "patch": patch,
        "ti": total_input,
        "to": total_output,
        "turns": n_steps,
        "tc": tool_calls,
        "wall": wall,
        "cost": round(total_cost, 4) if total_cost is not None else None,
        "cli": cli,
    }

    return {
        "instance_id": instance_id,
        "model_key": model_key,
        "entry": entry,
    }


def main() -> None:
    args = parse_args()

    jobs_dir = Path(args.jobs)
    if not jobs_dir.is_dir():
        print(f"Error: jobs directory not found: {args.jobs}", file=sys.stderr)
        sys.exit(1)

    instances = load_instances(args.instances)

    models: set[str] = set()
    runs: dict[str, dict[str, list[dict[str, Any]]]] = {}
    seen_instances: set[str] = set()
    attempt_counters: dict[tuple[str, str], int] = {}

    job_dirs = sorted(
        [d for d in jobs_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )

    for job_dir in job_dirs:
        job_config_path = job_dir / "config.json"
        if not job_config_path.is_file():
            continue

        with open(job_config_path) as f:
            job_config = json.load(f)

        tasks_list = job_config.get("tasks", [])
        task_path_map: dict[str, str] = {}
        for t in tasks_list:
            p = t.get("path", "")
            basename = os.path.basename(p)
            task_path_map[basename] = p

        trial_dirs = [
            d for d in job_dir.iterdir() if d.is_dir() and d.name != ".cache"
        ]

        for trial_dir in sorted(trial_dirs, key=lambda d: d.name):
            trial_name = trial_dir.name
            parts = trial_name.rsplit("__", 1)
            if len(parts) < 2:
                continue
            instance_key = parts[0]

            task_path = task_path_map.get(
                instance_key, tasks_list[0]["path"] if tasks_list else ""
            )

            result = process_trial(str(trial_dir), task_path)
            if result is None:
                continue

            model_key = result["model_key"]
            instance_id = result["instance_id"]
            entry = result["entry"]

            counter_key = (model_key, instance_id)
            attempt_idx = attempt_counters.get(counter_key, 0)
            entry["a"] = attempt_idx
            attempt_counters[counter_key] = attempt_idx + 1

            models.add(model_key)
            seen_instances.add(instance_id)

            if model_key not in runs:
                runs[model_key] = {}
            if instance_id not in runs[model_key]:
                runs[model_key][instance_id] = []
            runs[model_key][instance_id].append(entry)

    instances_out: dict[str, dict[str, Any]] = {}
    for iid in sorted(seen_instances):
        if iid in instances:
            instances_out[iid] = instances[iid]
        else:
            instances_out[iid] = {
                "repo": iid.rsplit("-", 1)[0].replace("__", "/"),
                "language": "unknown",
                "patch_lines": None,
                "files_touched": None,
                "cross_file": None,
                "n_fail_to_pass": None,
                "issue_url": "",
                "fix_merge_date": None,
                "human_patch": None,
            }

    data: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": sorted(models),
        "instances": instances_out,
        "runs": runs,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    n_trials = sum(
        len(trials)
        for model_runs in runs.values()
        for trials in model_runs.values()
    )
    print(f"Exported {len(models)} model(s), "
          f"{len(instances_out)} instance(s), "
          f"{n_trials} trial(s) -> {args.output}")


if __name__ == "__main__":
    main()
