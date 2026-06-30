"""Compare eval results between our generated instances and SWE-bench originals."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("compare_eval")

from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.dispatcher import CostTracker  # noqa: E402
from swebenchify.eval_harness import eval_instance  # noqa: E402
from swebenchify.models import Repository, TaskInstance  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402

WORKSPACE_ROOT = "output/workspaces"


def load_instances_from_jsonl(path: str) -> list[dict]:
    instances = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def dict_to_task_instance(d: dict) -> TaskInstance:
    """Convert a dict (from SWE-bench or our output) to TaskInstance."""
    f2p = d.get("FAIL_TO_PASS", "[]")
    p2p = d.get("PASS_TO_PASS", "[]")
    # SWE-bench stores these as JSON strings; ensure they are strings
    if isinstance(f2p, list):
        f2p = json.dumps(f2p)
    if isinstance(p2p, list):
        p2p = json.dumps(p2p)

    return TaskInstance(
        repo=d["repo"],
        instance_id=d["instance_id"],
        base_commit=d["base_commit"],
        patch=d["patch"],
        test_patch=d["test_patch"],
        problem_statement=d["problem_statement"],
        hints_text=d.get("hints_text", ""),
        created_at=d.get("created_at", ""),
        version=d.get("version", "unknown"),
        FAIL_TO_PASS=f2p,
        PASS_TO_PASS=p2p,
    )


async def compare_repo(
    repo_name: str,
    our_instances_path: str,
    swebench_fixture_path: str,
    max_instances: int = 3,
    model: str = "haiku",
) -> None:
    """Compare eval results for a repo between our data and SWE-bench data."""
    logger.info("\n%s", "=" * 60)
    logger.info("Comparing: %s", repo_name)
    logger.info("%s", "=" * 60)

    # Load both datasets
    our_data = (
        load_instances_from_jsonl(our_instances_path)
        if Path(our_instances_path).exists()
        else []
    )
    swebench_data = load_instances_from_jsonl(swebench_fixture_path)

    our_ids = {d["instance_id"] for d in our_data}
    swebench_ids = {d["instance_id"] for d in swebench_data}
    overlap_ids = sorted(our_ids & swebench_ids)

    logger.info("Our instances: %d", len(our_ids))
    logger.info("SWE-bench instances: %d", len(swebench_ids))
    logger.info("Overlapping: %d", len(overlap_ids))

    if not overlap_ids:
        logger.warning("No overlapping instances to compare")
        return

    # Sample instances
    test_ids = overlap_ids[:max_instances]
    logger.info("Testing %d instances: %s", len(test_ids), test_ids)

    our_map = {d["instance_id"]: d for d in our_data}
    swebench_map = {d["instance_id"]: d for d in swebench_data}

    repo = Repository(full_name=repo_name)
    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    # Use first instance for env discovery
    first = swebench_map[test_ids[0]]
    env_spec, _ = await discover_environment(
        repo=repo,
        commit=first["base_commit"],
        version=first.get("version", "unknown"),
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_attempts=2,
        max_turns=50,
        budget_usd=5.0,
    )

    if not env_spec:
        logger.error("Env discovery failed")
        return

    # Evaluate each overlapping instance with BOTH datasets
    results = []
    for instance_id in test_ids:
        logger.info("\n--- %s ---", instance_id)

        # Eval with our data
        our_inst = dict_to_task_instance(our_map[instance_id])
        our_result = await eval_instance(
            our_inst,
            env_spec=env_spec,
            repo=repo,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
            model=model,
        )

        # Eval with SWE-bench data
        sb_inst = dict_to_task_instance(swebench_map[instance_id])
        sb_result = await eval_instance(
            sb_inst,
            env_spec=env_spec,
            repo=repo,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
            model=model,
        )

        agree = our_result.resolved == sb_result.resolved
        results.append(
            {
                "instance_id": instance_id,
                "ours_resolved": our_result.resolved,
                "swebench_resolved": sb_result.resolved,
                "agree": agree,
                "ours_cost": our_result.cost_usd,
                "swebench_cost": sb_result.cost_usd,
            }
        )

        logger.info("  Ours:      %s", "PASS" if our_result.resolved else "FAIL")
        logger.info(
            "  SWE-bench: %s", "PASS" if sb_result.resolved else "FAIL"
        )
        logger.info("  Agreement: %s", "YES" if agree else "NO")

    # Summary
    logger.info("\n%s", "=" * 60)
    logger.info("COMPARISON SUMMARY")
    logger.info("%s", "=" * 60)
    agreements = sum(1 for r in results if r["agree"])
    logger.info(
        "Agreement: %d/%d (%d%%)",
        agreements,
        len(results),
        100 * agreements // len(results),
    )
    logger.info("Cost: %s", cost_tracker.summary())

    for r in results:
        status = "AGREE" if r["agree"] else "DISAGREE"
        ours = "PASS" if r["ours_resolved"] else "FAIL"
        theirs = "PASS" if r["swebench_resolved"] else "FAIL"
        logger.info(
            "  [%s] %s: ours=%s swebench=%s",
            status,
            r["instance_id"],
            ours,
            theirs,
        )


async def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else "pallets/flask"
    max_inst = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    model = sys.argv[3] if len(sys.argv) > 3 else "haiku"

    slug = repo.replace("/", "__")
    our_path = f"output/{slug}-candidates.jsonl"
    fixture_path = f"tests/fixtures/swebench_{repo.split('/')[1]}.jsonl"

    if not Path(fixture_path).exists():
        logger.error("Fixture not found: %s", fixture_path)
        sys.exit(1)

    await compare_repo(
        repo, our_path, fixture_path, max_instances=max_inst, model=model
    )


if __name__ == "__main__":
    asyncio.run(main())
