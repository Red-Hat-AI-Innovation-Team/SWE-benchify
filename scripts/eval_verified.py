"""Run haiku on SWE-bench Verified instances for Flask + Requests.

This gives us a baseline: how does haiku perform on the curated,
human-verified benchmark data? We then compare against our generated data.
"""

import asyncio
import json
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eval_verified")

from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.dispatcher import CostTracker  # noqa: E402
from swebenchify.eval_harness import eval_instance  # noqa: E402
from swebenchify.models import Repository, TaskInstance  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402

WORKSPACE_ROOT = "output/workspaces"
MODEL = "haiku"
FIXTURE = "tests/fixtures/swebench_verified_targets.jsonl"


def load_instances(path):
    instances = []
    with open(path) as f:
        for line in f:
            instances.append(json.loads(line.strip()))
    return instances


def dict_to_task(d):
    f2p = d.get("FAIL_TO_PASS", "[]")
    p2p = d.get("PASS_TO_PASS", "[]")
    if isinstance(f2p, list):
        f2p = json.dumps(f2p)
    if isinstance(p2p, list):
        p2p = json.dumps(p2p)
    return TaskInstance(
        repo=d["repo"], instance_id=d["instance_id"],
        base_commit=d["base_commit"], patch=d["patch"],
        test_patch=d["test_patch"], problem_statement=d["problem_statement"],
        hints_text=d.get("hints_text", ""), created_at=d.get("created_at", ""),
        version=d.get("version", "unknown"), FAIL_TO_PASS=f2p, PASS_TO_PASS=p2p,
    )


async def main():
    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    all_data = load_instances(FIXTURE)
    logger.info(f"Loaded {len(all_data)} SWE-bench Verified instances")

    results = []
    current_repo = None
    env_spec = None
    repo = None

    for d in all_data:
        repo_name = d["repo"]

        if repo_name != current_repo:
            current_repo = repo_name
            repo = Repository(full_name=repo_name)
            logger.info(f"\n{'='*60}")
            logger.info(f"  {repo_name}")
            logger.info(f"{'='*60}")
            env_spec, _ = await discover_environment(
                repo=repo, commit=d["base_commit"],
                version=d.get("version", "unknown"),
                workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
                max_attempts=2, max_turns=50, budget_usd=5.0,
            )
            if not env_spec:
                logger.error(f"Env discovery failed for {repo_name}")
                continue
            logger.info(f"  Install: {env_spec.install_cmd}")
            logger.info(f"  Test: {env_spec.test_cmd}")

        inst = dict_to_task(d)
        instance_id = d["instance_id"]
        f2p = json.loads(inst.FAIL_TO_PASS)

        logger.info(f"\n--- {instance_id} ---")
        logger.info(f"  F2P: {f2p}")

        result = await eval_instance(
            inst, env_spec=env_spec, repo=repo,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            model=MODEL, max_turns=50, budget_usd=2.0,
        )

        status = "PASS" if result.resolved else "FAIL"
        cost = f"${result.cost_usd:.2f}" if result.cost_usd else "N/A"
        patch_lines = len(result.agent_patch.splitlines()) if result.agent_patch else 0
        logger.info(f"  [{status}] cost={cost} patch={patch_lines}L")
        logger.info(f"  passed={result.tests_passed}")
        logger.info(f"  failed={result.tests_failed}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

        results.append({
            "instance_id": instance_id,
            "repo": repo_name,
            "source": "swebench_verified",
            "resolved": result.resolved,
            "cost_usd": result.cost_usd,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
            "error": result.error_message,
        })

    # Summary
    _ = [r for r in results if not r.get("error") or "SDK" not in str(r.get("error", ""))]
    resolved = sum(1 for r in results if r["resolved"])
    errors = sum(1 for r in results if r.get("error"))
    total = len(results)

    logger.info(f"\n{'='*60}")
    logger.info("SWE-bench Verified — Haiku Results")
    logger.info(f"{'='*60}")
    logger.info(f"Total: {total} | Resolved: {resolved} | Errors: {errors}")
    logger.info(f"Resolve rate: {resolved}/{total} ({100*resolved/total:.0f}%)")
    logger.info(f"Resolve rate (excl errors): {resolved}/{total-errors} ({100*resolved/max(total-errors,1):.0f}%)")

    for r in results:
        s = "PASS" if r["resolved"] else "FAIL"
        if r.get("error"):
            s = "ERR "
        c = f"${r['cost_usd']:.2f}" if r["cost_usd"] else "  - "
        logger.info(f"  [{s}] {r['instance_id']} ({c})")

    logger.info(f"\n{cost_tracker.summary()}")

    os.makedirs("output", exist_ok=True)
    with open("output/eval_verified_results.json", "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Saved to output/eval_verified_results.json")


if __name__ == "__main__":
    asyncio.run(main())
