"""Build TaskInstances from on-disk validation results, then run three-model eval."""

import asyncio
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("build_and_eval")

from swebenchify.models import TaskInstance, Repository  # noqa: E402
from swebenchify.extractor import load_candidates  # noqa: E402
from swebenchify.dispatcher import CostTracker, run_agent_task  # noqa: E402
from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402
from swebenchify.versioning import detect_version  # noqa: E402

OUTPUT_DIR = "output"
WORKSPACE_ROOT = "output/workspaces"
MODELS = ["haiku", "sonnet", "opus"]


def build_task_instances() -> list[TaskInstance]:
    """Scan validation_result.json files and build TaskInstances."""
    instances = []
    for repo_slug in ["pallets__flask", "psf__requests"]:
        repo_name = repo_slug.replace("__", "/")
        candidates_file = f"{OUTPUT_DIR}/{repo_slug}-candidates.jsonl"
        if not Path(candidates_file).exists():
            continue
        candidates = {c.instance_id: c for c in load_candidates(candidates_file)}

        instances_dir = Path(WORKSPACE_ROOT) / repo_slug / "instances"
        if not instances_dir.exists():
            continue

        for inst_dir in sorted(instances_dir.iterdir()):
            result_file = inst_dir / "repo" / "validation_result.json"
            if not result_file.exists():
                continue
            try:
                vr = json.loads(result_file.read_text())
            except json.JSONDecodeError:
                continue
            if vr.get("status") != "valid":
                continue

            instance_id = inst_dir.name
            candidate = candidates.get(instance_id)
            if not candidate:
                continue

            # Detect version
            bare_clone = Path(WORKSPACE_ROOT) / repo_slug / "repo.git"
            version = detect_version(str(bare_clone), candidate.base_commit) or "unknown"

            instances.append(TaskInstance(
                repo=repo_name,
                instance_id=instance_id,
                base_commit=candidate.base_commit,
                patch=candidate.patch or "",
                test_patch=candidate.test_patch or "",
                problem_statement=candidate.problem_statement or "",
                hints_text=candidate.hints_text or "",
                created_at=candidate.created_at,
                version=version,
                FAIL_TO_PASS=json.dumps(vr.get("FAIL_TO_PASS", [])),
                PASS_TO_PASS=json.dumps(vr.get("PASS_TO_PASS", [])),
            ))

    return instances


async def run_eval_model(instances, model, workspace_mgr, cost_tracker):
    """Run eval for one model. Returns {instance_id: {resolved, cost_usd, ...}}."""
    results = {}
    by_repo = defaultdict(list)
    for inst in instances:
        by_repo[inst.repo].append(inst)

    for repo_name, repo_instances in by_repo.items():
        repo = Repository(full_name=repo_name)
        logger.info(f"[{model}] {repo_name}: {len(repo_instances)} instances")

        env_spec, _ = await discover_environment(
            repo=repo, commit=repo_instances[0].base_commit,
            version=repo_instances[0].version,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
        )
        if not env_spec:
            logger.error(f"[{model}] Env discovery failed for {repo_name}")
            continue

        for inst in repo_instances:
            import shutil
            import subprocess
            eval_dir = (workspace_mgr.repo_dir(repo) / "eval_instances" / f"{model}_{inst.instance_id}").resolve()
            if eval_dir.exists():
                shutil.rmtree(eval_dir, ignore_errors=True)
            subprocess.run(["git", "-C", str(workspace_mgr.bare_clone_path(repo)), "worktree", "prune"], capture_output=True)

            worktree = eval_dir / "repo"
            eval_dir.mkdir(parents=True, exist_ok=True)
            try:
                workspace_mgr.create_worktree(repo, inst.base_commit, worktree)
            except Exception as e:
                logger.warning(f"[{model}] Worktree failed for {inst.instance_id}: {e}")
                results[inst.instance_id] = {"resolved": False, "error": str(e), "cost_usd": None}
                continue

            # Install (no test patch yet — agent works on the original code)
            subprocess.run(env_spec.install_cmd, shell=True, cwd=str(worktree), capture_output=True, text=True, timeout=300)
            test_patch_file = eval_dir / "test.patch"
            test_patch_file.write_text(inst.test_patch)

            # Solve — agent gets the problem statement and fixes the code
            solve_prompt = f"""You are a software engineer fixing a bug in {repo_name}.
The repository is checked out at the relevant commit.

## Problem
{inst.problem_statement}

## Instructions
1. Find and fix the bug. Do NOT modify test files.
2. Verify your fix makes sense by reading the relevant code.
"""
            solve_result = await run_agent_task(
                prompt=solve_prompt, cwd=str(worktree),
                tools=["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
                max_turns=50, budget_usd=2.0, model=model,
            )
            cost = solve_result.cost_usd or 0.0
            cost_tracker.record("eval", repo_name, solve_result, instance_id=inst.instance_id)

            # After agent finishes: apply test_patch, then verify
            # This matches SWE-bench's flow: agent patch first, then test patch, then run tests
            try:
                subprocess.run(["git", "apply", str(test_patch_file)], cwd=str(worktree), check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                # Try with --3way for fuzzy matching
                try:
                    subprocess.run(["git", "apply", "--3way", str(test_patch_file)], cwd=str(worktree), check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    logger.warning(f"[{model}] test patch failed for {inst.instance_id}: {e.stderr[:100]}")
                    results[inst.instance_id] = {"resolved": False, "error": "test_patch_failed", "cost_usd": cost}
                    continue

            subprocess.run(env_spec.install_cmd, shell=True, cwd=str(worktree), capture_output=True, text=True, timeout=300)
            f2p_tests = json.loads(inst.FAIL_TO_PASS)
            passed, failed = [], []
            for test_id in f2p_tests:
                try:
                    cmd = f"python -m pytest {test_id} -x -q" if "::" in test_id else env_spec.test_cmd
                    proc = subprocess.run(cmd, shell=True, cwd=str(worktree), capture_output=True, text=True, timeout=120)
                    (passed if proc.returncode == 0 else failed).append(test_id)
                except Exception:
                    failed.append(test_id)

            resolved = len(passed) == len(f2p_tests) and not failed
            status = "PASS" if resolved else "FAIL"
            logger.info(f"  [{status}] {inst.instance_id} ({model}) ${cost:.2f} {len(passed)}/{len(f2p_tests)} F2P")
            results[inst.instance_id] = {"resolved": resolved, "cost_usd": cost, "passed": passed, "failed": failed}

    return results


async def main():
    # Step 1: Build instances from disk
    logger.info("Building TaskInstances from validation results...")
    instances = build_task_instances()
    logger.info(f"Built {len(instances)} validated instances")

    by_repo = defaultdict(int)
    for inst in instances:
        by_repo[inst.repo] += 1
    for repo, count in by_repo.items():
        logger.info(f"  {repo}: {count}")

    # Save them
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/all-task-instances.jsonl", "w") as f:
        from dataclasses import asdict
        for inst in instances:
            f.write(json.dumps(asdict(inst)) + "\n")
    logger.info(f"Saved to {OUTPUT_DIR}/all-task-instances.jsonl")

    # Sample 10 per repo for eval
    MAX_PER_REPO = 10
    sampled = []
    for repo_name in ["pallets/flask", "psf/requests"]:
        repo_instances = [i for i in instances if i.repo == repo_name]
        sampled.extend(repo_instances[:MAX_PER_REPO])
    instances = sampled
    logger.info(f"Sampled {len(instances)} instances for eval (max {MAX_PER_REPO} per repo)")

    # Step 2: Run eval with all three models
    all_results = {}
    for model in MODELS:
        logger.info(f"\n{'='*60}")
        logger.info(f"Evaluating with {model} ({len(instances)} instances)")
        logger.info(f"{'='*60}")
        workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
        cost_tracker = CostTracker()
        results = await run_eval_model(instances, model, workspace_mgr, cost_tracker)
        all_results[model] = results

        resolved = sum(1 for r in results.values() if r.get("resolved"))
        logger.info(f"[{model}] {resolved}/{len(results)} resolved ({100*resolved/max(len(results),1):.0f}%)")
        logger.info(cost_tracker.summary())
        with open(f"{OUTPUT_DIR}/eval_{model}_results.json", "w") as f:
            json.dump(results, f, indent=2)

    # Step 3: Comparison
    logger.info(f"\n{'='*60}")
    logger.info("FINAL COMPARISON")
    logger.info(f"{'='*60}")

    logger.info(f"\n{'Model':<10} {'Resolved':>10} {'Total':>8} {'Rate':>8} {'Cost':>10}")
    logger.info("-" * 50)
    rates = {}
    for model in MODELS:
        r = all_results[model]
        resolved = sum(1 for v in r.values() if v.get("resolved"))
        total = len(r)
        cost = sum(v.get("cost_usd", 0) or 0 for v in r.values())
        rate = resolved / max(total, 1)
        rates[model] = rate
        logger.info(f"{model:<10} {resolved:>10} {total:>8} {100*rate:>7.0f}% ${cost:>8.2f}")

    ranking = sorted(MODELS, key=lambda m: rates[m], reverse=True)
    logger.info(f"\nRanking: {' > '.join(ranking)}")
    if ranking == ["opus", "sonnet", "haiku"]:
        logger.info("SANITY CHECK PASSED")
    else:
        logger.info("Expected opus > sonnet > haiku")

    with open(f"{OUTPUT_DIR}/eval_comparison.json", "w") as f:
        json.dump({"instances": len(instances), "models": {m: {"rate": rates[m]} for m in MODELS}, "ranking": ranking}, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
