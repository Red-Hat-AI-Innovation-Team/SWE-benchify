"""Generate SWE-bench predictions using Claude Code agents.

Produces predictions.jsonl files compatible with swebench.harness.run_evaluation.
Each prediction has: instance_id, model_name_or_path, model_patch.

Usage:
    python scripts/generate_predictions.py --model haiku --max-instances 10
    python scripts/generate_predictions.py --model sonnet --max-instances 10
    python scripts/generate_predictions.py --model opus --max-instances 10
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("predictions")

from swebenchify.models import TaskInstance, Repository
from swebenchify.dispatcher import run_agent_task, CostTracker
from swebenchify.discovery import discover_environment
from swebenchify.workspace import WorkspaceManager

DATASET = "output/swebenchify-dataset.jsonl"
WORKSPACE_ROOT = "output/workspaces"


def load_instances(path: str, max_instances: int | None = None) -> list[TaskInstance]:
    instances = []
    with open(path) as f:
        for line in f:
            instances.append(TaskInstance(**json.loads(line.strip())))
    if max_instances:
        instances = instances[:max_instances]
    return instances


async def generate_patch(
    inst: TaskInstance,
    env_spec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    model: str,
) -> dict:
    """Generate a patch prediction for one instance."""
    eval_dir = (workspace_mgr.repo_dir(repo) / "predictions" / f"{model}_{inst.instance_id}").resolve()
    worktree = eval_dir / "repo"

    # Clean up previous run
    if eval_dir.exists():
        shutil.rmtree(eval_dir, ignore_errors=True)
    subprocess.run(
        ["git", "-C", str(workspace_mgr.bare_clone_path(repo)), "worktree", "prune"],
        capture_output=True,
    )

    eval_dir.mkdir(parents=True, exist_ok=True)
    workspace_mgr.create_worktree(repo, inst.base_commit, worktree)

    # Install dependencies
    subprocess.run(
        env_spec.install_cmd, shell=True, cwd=str(worktree),
        capture_output=True, text=True, timeout=300,
    )

    # Agent solves the problem (no test patch — just the problem statement)
    prompt = f"""You are a software engineer fixing a bug in {repo.full_name}.
The repository is checked out at the relevant commit.

## Problem
{inst.problem_statement}

## Instructions
1. Read and understand the problem described above.
2. Find the relevant source code (do NOT modify test files).
3. Fix the bug.
4. Verify your fix makes sense by reading the relevant code.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/).
Focus on making the minimal change needed to fix the described issue.
"""
    result = await run_agent_task(
        prompt=prompt, cwd=str(worktree),
        tools=["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
        max_turns=50, budget_usd=5.0, model=model,
    )

    # Capture the diff
    try:
        diff = subprocess.run(
            ["git", "diff"], cwd=str(worktree),
            capture_output=True, text=True, timeout=30,
        )
        patch = diff.stdout if diff.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        patch = ""

    return {
        "instance_id": inst.instance_id,
        "model_name_or_path": f"claude-{model}",
        "model_patch": patch,
        "cost_usd": result.cost_usd,
        "status": result.status,
        "num_turns": result.num_turns,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="haiku", choices=["haiku", "sonnet", "opus"])
    parser.add_argument("--max-instances", type=int, default=10)
    parser.add_argument("--dataset", default=DATASET)
    args = parser.parse_args()

    instances = load_instances(args.dataset, args.max_instances)
    logger.info(f"Generating predictions for {len(instances)} instances with {args.model}")

    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()
    predictions = []

    # Group by repo
    from collections import defaultdict
    by_repo = defaultdict(list)
    for inst in instances:
        by_repo[inst.repo].append(inst)

    for repo_name, repo_instances in by_repo.items():
        repo = Repository(full_name=repo_name)
        logger.info(f"\n{repo_name}: {len(repo_instances)} instances")

        env_spec, _ = await discover_environment(
            repo=repo, commit=repo_instances[0].base_commit,
            version=repo_instances[0].version,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
        )
        if not env_spec:
            logger.error(f"Env discovery failed for {repo_name}")
            continue

        for inst in repo_instances:
            logger.info(f"  [{args.model}] {inst.instance_id}...")
            pred = await generate_patch(inst, env_spec, repo, workspace_mgr, args.model)
            predictions.append(pred)

            patch_lines = len(pred["model_patch"].splitlines()) if pred["model_patch"] else 0
            cost = f"${pred['cost_usd']:.2f}" if pred["cost_usd"] else "N/A"
            logger.info(f"    patch={patch_lines}L cost={cost} status={pred['status']}")

    # Save predictions in SWE-bench format
    out_file = f"output/predictions_{args.model}.jsonl"
    with open(out_file, "w") as f:
        for pred in predictions:
            # SWE-bench only needs these 3 fields
            f.write(json.dumps({
                "instance_id": pred["instance_id"],
                "model_name_or_path": pred["model_name_or_path"],
                "model_patch": pred["model_patch"],
            }) + "\n")
    logger.info(f"\nSaved {len(predictions)} predictions to {out_file}")

    # Also save full results with cost info
    with open(f"output/predictions_{args.model}_full.json", "w") as f:
        json.dump(predictions, f, indent=2)

    total_cost = sum(p.get("cost_usd", 0) or 0 for p in predictions)
    with_patches = sum(1 for p in predictions if p["model_patch"])
    logger.info(f"Total cost: ${total_cost:.2f}")
    logger.info(f"Predictions with patches: {with_patches}/{len(predictions)}")
    logger.info(f"\nTo evaluate with SWE-bench:")
    logger.info(f"  python -m swebench.harness.run_evaluation \\")
    logger.info(f"    --predictions_path {out_file} \\")
    logger.info(f"    --swe_bench_tasks output/swebenchify-dataset.jsonl \\")
    logger.info(f"    --run_id {args.model}")


if __name__ == "__main__":
    asyncio.run(main())
