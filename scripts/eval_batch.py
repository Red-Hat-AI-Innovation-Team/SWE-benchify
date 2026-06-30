"""Run haiku on SWE-bench instances: test the eval harness with proper verification."""

import asyncio
import json
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eval_batch")

from swebenchify.models import TaskInstance, Repository  # noqa: E402
from swebenchify.eval_harness import eval_instance  # noqa: E402
from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.dispatcher import CostTracker  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402

WORKSPACE_ROOT = "output/workspaces"
MODEL = "haiku"


def load_fixture(path):
    instances = {}
    with open(path) as f:
        for line in f:
            d = json.loads(line.strip())
            instances[d["instance_id"]] = d
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

    # Pick 5 Flask + 5 Requests instances
    flask_fixture = load_fixture("tests/fixtures/swebench_flask.jsonl")
    requests_fixture = load_fixture("tests/fixtures/swebench_requests.jsonl")

    test_cases = (
        list(sorted(flask_fixture.keys()))[:5]
        + list(sorted(requests_fixture.keys()))[:5]
    )
    all_fixtures = {**flask_fixture, **requests_fixture}

    results = []
    current_repo = None
    env_spec = None

    for instance_id in test_cases:
        d = all_fixtures[instance_id]
        repo_name = d["repo"]

        # Discover env once per repo
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
        logger.info(f"\n--- {instance_id} ---")
        f2p = json.loads(inst.FAIL_TO_PASS)
        logger.info(f"  F2P tests: {f2p}")

        result = await eval_instance(
            inst, env_spec=env_spec, repo=repo,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            model=MODEL, max_turns=50, budget_usd=2.0,
        )

        status = "PASS" if result.resolved else "FAIL"
        cost = f"${result.cost_usd:.2f}" if result.cost_usd else "N/A"
        patch_lines = len(result.agent_patch.splitlines()) if result.agent_patch else 0
        logger.info(f"  [{status}] cost={cost} patch={patch_lines}L passed={result.tests_passed} failed={result.tests_failed}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

        results.append({
            "instance_id": instance_id,
            "repo": repo_name,
            "resolved": result.resolved,
            "cost_usd": result.cost_usd,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
        })

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("RESULTS")
    logger.info(f"{'='*60}")

    resolved = sum(1 for r in results if r["resolved"])
    total = len(results)
    logger.info(f"Resolved: {resolved}/{total} ({100*resolved/total:.0f}%)")

    for r in results:
        s = "PASS" if r["resolved"] else "FAIL"
        logger.info(f"  [{s}] {r['instance_id']}")

    logger.info(f"\n{cost_tracker.summary()}")

    os.makedirs("output", exist_ok=True)
    with open("output/eval_batch_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
