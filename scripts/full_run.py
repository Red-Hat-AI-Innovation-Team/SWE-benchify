"""Full pipeline run + three-model evaluation.

1. Run the SWE-benchify pipeline on Flask + Requests (stages 1-6)
2. Collect all validated TaskInstances
3. Run eval with haiku, sonnet, opus on every instance
4. Print comparison table and ranking
"""

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("full_run")

from swebenchify.config import load_config
from swebenchify.pipeline import run_pipeline
from swebenchify.models import TaskInstance, Repository
from swebenchify.eval_harness import eval_instance, save_eval_results
from swebenchify.discovery import discover_environment
from swebenchify.dispatcher import CostTracker
from swebenchify.workspace import WorkspaceManager
from swebenchify.emitter import load_dataset

CONFIG_PATH = "swebenchify.yaml"
OUTPUT_DIR = "output"
WORKSPACE_ROOT = "output/workspaces"
MODELS = ["haiku", "sonnet", "opus"]


def load_task_instances(output_dir: str) -> list[TaskInstance]:
    """Load all validated TaskInstances from pipeline output."""
    instances = []
    for f in Path(output_dir).glob("*-task-instances.jsonl"):
        if f.name == "all-task-instances.jsonl":
            continue
        for d in load_dataset(str(f)):
            instances.append(TaskInstance(**d))
    return instances


async def run_eval_model(
    instances: list[TaskInstance],
    model: str,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker,
) -> dict[str, dict]:
    """Run eval for one model across all instances. Returns {instance_id: result}."""
    results = {}

    # Group by repo for env discovery
    by_repo: dict[str, list[TaskInstance]] = defaultdict(list)
    for inst in instances:
        by_repo[inst.repo].append(inst)

    for repo_name, repo_instances in by_repo.items():
        repo = Repository(full_name=repo_name)
        logger.info(f"[{model}] {repo_name}: {len(repo_instances)} instances")

        # Env discovery (cached)
        first = repo_instances[0]
        env_spec, _ = await discover_environment(
            repo=repo, commit=first.base_commit,
            version=first.version,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            max_attempts=2, max_turns=50, budget_usd=5.0,
        )
        if not env_spec:
            logger.error(f"[{model}] Env discovery failed for {repo_name}, skipping")
            for inst in repo_instances:
                results[inst.instance_id] = {
                    "resolved": False, "error": "env_discovery_failed",
                    "cost_usd": None,
                }
            continue

        for inst in repo_instances:
            logger.info(f"[{model}] Evaluating {inst.instance_id}...")

            # Clean up previous eval worktree for this model+instance
            eval_dir = workspace_mgr.repo_dir(repo) / "eval_instances" / f"{model}_{inst.instance_id}"
            if eval_dir.exists():
                import shutil
                shutil.rmtree(eval_dir, ignore_errors=True)
            import subprocess
            subprocess.run(
                ["git", "-C", str(workspace_mgr.bare_clone_path(repo)), "worktree", "prune"],
                capture_output=True,
            )

            # Monkey-patch instance_id to include model prefix for separate worktrees
            from copy import deepcopy
            eval_inst = deepcopy(inst)
            object.__setattr__(eval_inst, '_eval_id', f"{model}_{inst.instance_id}")

            # We need to create the worktree with the right name
            inst_dir = (workspace_mgr.repo_dir(repo) / "eval_instances" / f"{model}_{inst.instance_id}").resolve()
            worktree = inst_dir / "repo"
            inst_dir.mkdir(parents=True, exist_ok=True)
            workspace_mgr.create_worktree(repo, inst.base_commit, worktree)

            # Set up env
            for pre_cmd in env_spec.pre_install:
                subprocess.run(pre_cmd, shell=True, cwd=str(worktree),
                               capture_output=True, text=True, timeout=120)
            subprocess.run(env_spec.install_cmd, shell=True, cwd=str(worktree),
                           capture_output=True, text=True, timeout=300)

            # Apply test patch
            test_patch_file = inst_dir / "test.patch"
            test_patch_file.write_text(inst.test_patch)
            try:
                subprocess.run(
                    ["git", "apply", str(test_patch_file)],
                    cwd=str(worktree), check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                logger.warning(f"[{model}] test patch failed for {inst.instance_id}: {e.stderr[:100]}")
                results[inst.instance_id] = {
                    "resolved": False, "error": "test_patch_failed", "cost_usd": None,
                }
                continue

            # Dispatch agent to solve
            from swebenchify.dispatcher import run_agent_task
            solve_prompt = f"""You are a software engineer fixing a bug in {repo_name}.

The repository is checked out at the relevant commit. There are failing tests that demonstrate the bug.

## Problem
{inst.problem_statement}

## Instructions
1. Read and understand the problem described above.
2. Find the relevant source code (do NOT modify test files).
3. Fix the bug so the failing tests pass.
4. Verify your fix by running: {env_spec.test_cmd}

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/).
Focus on making the minimal change needed to fix the described issue.
"""
            solve_result = await run_agent_task(
                prompt=solve_prompt,
                cwd=str(worktree),
                tools=["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
                max_turns=50,
                budget_usd=2.0,
                model=model,
            )

            cost = solve_result.cost_usd or 0.0

            if solve_result.is_error and solve_result.status != "error_max_turns":
                results[inst.instance_id] = {
                    "resolved": False, "error": solve_result.status, "cost_usd": cost,
                }
                cost_tracker.record("eval", repo_name, solve_result, instance_id=inst.instance_id)
                continue

            cost_tracker.record("eval", repo_name, solve_result, instance_id=inst.instance_id)

            # Re-install after agent changes
            subprocess.run(env_spec.install_cmd, shell=True, cwd=str(worktree),
                           capture_output=True, text=True, timeout=300)

            # Verify: run each F2P test
            f2p_tests = json.loads(inst.FAIL_TO_PASS)
            tests_passed = []
            tests_failed = []
            for test_id in f2p_tests:
                try:
                    test_cmd = f"python -m pytest {test_id} -x -q" if "::" in test_id else env_spec.test_cmd
                    proc = subprocess.run(
                        test_cmd, shell=True, cwd=str(worktree),
                        capture_output=True, text=True, timeout=120,
                    )
                    if proc.returncode == 0:
                        tests_passed.append(test_id)
                    else:
                        tests_failed.append(test_id)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    tests_failed.append(test_id)

            resolved = len(tests_passed) == len(f2p_tests) and len(tests_failed) == 0
            status = "PASS" if resolved else "FAIL"
            logger.info(f"  [{status}] {len(tests_passed)}/{len(f2p_tests)} F2P tests, ${cost:.2f}")

            results[inst.instance_id] = {
                "resolved": resolved,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "cost_usd": cost,
                "error": None,
            }

    return results


async def main():
    # === Step 1: Run the full pipeline ===
    logger.info("=" * 70)
    logger.info("STEP 1: Running full SWE-benchify pipeline")
    logger.info("=" * 70)

    config = load_config(CONFIG_PATH)
    await run_pipeline(config, resume=True)

    # === Step 2: Load validated instances ===
    instances = load_task_instances(OUTPUT_DIR)
    logger.info(f"\nPipeline produced {len(instances)} validated instances")

    if not instances:
        logger.error("No instances produced. Cannot proceed with evaluation.")
        return

    by_repo = defaultdict(int)
    for inst in instances:
        by_repo[inst.repo] += 1
    for repo, count in by_repo.items():
        logger.info(f"  {repo}: {count}")

    # === Step 3: Run eval with all three models ===
    all_results: dict[str, dict[str, dict]] = {}  # model -> {instance_id -> result}

    for model in MODELS:
        logger.info(f"\n{'=' * 70}")
        logger.info(f"STEP 3: Evaluating with {model}")
        logger.info(f"{'=' * 70}")

        workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
        cost_tracker = CostTracker()

        results = await run_eval_model(instances, model, workspace_mgr, cost_tracker)
        all_results[model] = results

        resolved = sum(1 for r in results.values() if r.get("resolved"))
        total = len(results)
        logger.info(f"\n[{model}] Resolved: {resolved}/{total} ({100*resolved/total:.0f}%)")
        logger.info(f"[{model}] {cost_tracker.summary()}")

        # Save per-model results
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(f"{OUTPUT_DIR}/eval_{model}_results.json", "w") as f:
            json.dump(results, f, indent=2)

    # === Step 4: Comparison table ===
    logger.info(f"\n{'=' * 70}")
    logger.info("FINAL COMPARISON")
    logger.info(f"{'=' * 70}")

    # Per-model resolve rates
    logger.info(f"\n{'Model':<10} {'Resolved':>10} {'Total':>8} {'Rate':>8} {'Cost':>10}")
    logger.info("-" * 50)
    for model in MODELS:
        results = all_results[model]
        resolved = sum(1 for r in results.values() if r.get("resolved"))
        total = len(results)
        cost = sum(r.get("cost_usd", 0) or 0 for r in results.values())
        logger.info(f"{model:<10} {resolved:>10} {total:>8} {100*resolved/total:>7.0f}% ${cost:>8.2f}")

    # Per-instance detail
    logger.info(f"\n{'Instance':<35} {'haiku':>7} {'sonnet':>7} {'opus':>7}")
    logger.info("-" * 60)
    for inst in sorted(instances, key=lambda i: i.instance_id):
        row = f"{inst.instance_id:<35}"
        for model in MODELS:
            r = all_results[model].get(inst.instance_id, {})
            if r.get("resolved"):
                row += f" {'PASS':>7}"
            elif r.get("error"):
                row += f" {'ERR':>7}"
            else:
                row += f" {'FAIL':>7}"
        logger.info(row)

    # Sanity check: ranking
    rates = {}
    for model in MODELS:
        results = all_results[model]
        rates[model] = sum(1 for r in results.values() if r.get("resolved")) / max(len(results), 1)

    logger.info(f"\n{'=' * 70}")
    logger.info("RANKING SANITY CHECK")
    logger.info(f"{'=' * 70}")
    ranking = sorted(MODELS, key=lambda m: rates[m], reverse=True)
    for i, model in enumerate(ranking):
        logger.info(f"  #{i+1} {model}: {100*rates[model]:.0f}%")

    expected = ["opus", "sonnet", "haiku"]
    if ranking == expected:
        logger.info("\nSANITY CHECK PASSED: opus > sonnet > haiku")
    else:
        logger.info(f"\nSANITY CHECK: ranking is {ranking}, expected {expected}")
        if rates[ranking[0]] == rates[ranking[1]]:
            logger.info("(tie at the top — may need more instances to differentiate)")

    # Save combined results
    with open(f"{OUTPUT_DIR}/eval_comparison.json", "w") as f:
        json.dump({
            "instances": len(instances),
            "models": {m: {"resolved": sum(1 for r in all_results[m].values() if r.get("resolved")),
                           "total": len(all_results[m]),
                           "rate": rates[m]}
                       for m in MODELS},
            "ranking": ranking,
            "per_instance": {inst.instance_id: {m: all_results[m].get(inst.instance_id, {}).get("resolved", False) for m in MODELS} for inst in instances},
        }, f, indent=2)
    logger.info(f"\nResults saved to {OUTPUT_DIR}/eval_comparison.json")


if __name__ == "__main__":
    asyncio.run(main())
