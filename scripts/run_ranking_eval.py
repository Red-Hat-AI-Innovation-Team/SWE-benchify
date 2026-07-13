#!/usr/bin/env python
"""Run agent ranking sanity check (Phase 1.3c).

Evaluates haiku, sonnet, and opus on a shared set of instances to verify
the expected capability ordering (haiku < sonnet < opus resolve rates).

Uses agent-based evaluation (not Docker) for speed. Picks instances from
both Flask and Requests for diversity.

Usage:
    python scripts/run_ranking_eval.py --max-instances 50
    python scripts/run_ranking_eval.py --max-instances 50 --models haiku,sonnet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swebenchify.discovery import discover_environment
from swebenchify.dispatcher import CostTracker
from swebenchify.eval_harness import eval_instance
from swebenchify.models import EnvironmentSpec, Repository, TaskInstance
from swebenchify.workspace import WorkspaceManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WORKSPACE_ROOT = "output/workspaces"
DATASET = "output/swebenchify-dataset.jsonl"


def load_instances(path: str, max_instances: int) -> list[TaskInstance]:
    all_instances = []
    with open(path) as f:
        for line in f:
            d = json.loads(line.strip())
            f2p = d.get("FAIL_TO_PASS", "[]")
            p2p = d.get("PASS_TO_PASS", "[]")
            if isinstance(f2p, list):
                f2p = json.dumps(f2p)
            if isinstance(p2p, list):
                p2p = json.dumps(p2p)
            all_instances.append(TaskInstance(
                repo=d["repo"], instance_id=d["instance_id"],
                base_commit=d["base_commit"], patch=d["patch"],
                test_patch=d["test_patch"],
                problem_statement=d["problem_statement"],
                hints_text=d.get("hints_text", ""),
                created_at=d.get("created_at", ""),
                version=d.get("version", "unknown"),
                FAIL_TO_PASS=f2p, PASS_TO_PASS=p2p,
            ))

    by_repo: dict[str, list[TaskInstance]] = defaultdict(list)
    for inst in all_instances:
        by_repo[inst.repo].append(inst)

    selected: list[TaskInstance] = []
    repos = sorted(by_repo.keys())
    per_repo = max(1, max_instances // len(repos))

    for repo in repos:
        repo_instances = by_repo[repo][:per_repo]
        selected.extend(repo_instances)

    return selected[:max_instances]


async def eval_model(
    model: str,
    instances: list[TaskInstance],
    env_specs: dict[str, EnvironmentSpec],
    workspace_mgr: WorkspaceManager,
    budget_usd: float = 2.0,
    max_turns: int = 30,
) -> dict[str, dict]:
    """Evaluate a single model on all instances."""
    results = {}
    cost_tracker = CostTracker()

    for i, inst in enumerate(instances):
        repo = Repository(full_name=inst.repo)
        env_spec = env_specs.get(inst.repo)
        if not env_spec:
            logger.warning("No env spec for %s, skipping %s", inst.repo, inst.instance_id)
            continue

        logger.info("[%s] %d/%d %s", model, i + 1, len(instances), inst.instance_id)

        result = await eval_instance(
            inst, env_spec=env_spec, repo=repo,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            model=model, max_turns=max_turns, budget_usd=budget_usd,
        )

        results[inst.instance_id] = {
            "resolved": result.resolved,
            "cost_usd": result.cost_usd,
            "passed": result.tests_passed,
            "failed": result.tests_failed,
            "error": result.error_message,
        }

        status = "PASS" if result.resolved else "FAIL"
        cost = f"${result.cost_usd:.2f}" if result.cost_usd else "?"
        logger.info("  [%s] %s cost=%s", status, inst.instance_id, cost)

    return results


async def main():
    parser = argparse.ArgumentParser(description="Agent ranking eval (1.3c)")
    parser.add_argument("--max-instances", type=int, default=50)
    parser.add_argument("--models", default="haiku,sonnet,opus")
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("results/ranking_eval.json"))
    args = parser.parse_args()

    models = args.models.split(",")
    instances = load_instances(args.dataset, args.max_instances)
    logger.info("Loaded %d instances across %d repos",
                len(instances), len(set(i.repo for i in instances)))

    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    env_specs: dict[str, EnvironmentSpec] = {}
    for repo_name in set(i.repo for i in instances):
        repo = Repository(full_name=repo_name)
        sample = next(i for i in instances if i.repo == repo_name)
        logger.info("Discovering env for %s...", repo_name)
        spec, _ = await discover_environment(
            repo=repo, commit=sample.base_commit,
            version=sample.version,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            max_attempts=2, max_turns=50, budget_usd=5.0,
        )
        if spec:
            env_specs[repo_name] = spec
        else:
            logger.error("Env discovery failed for %s", repo_name)

    all_results = {}
    for model in models:
        logger.info("\n=== Evaluating %s ===", model)
        results = await eval_model(
            model, instances, env_specs, workspace_mgr,
            budget_usd=args.budget, max_turns=args.max_turns,
        )
        all_results[model] = results

        resolved = sum(1 for r in results.values() if r["resolved"])
        total = len(results)
        cost = sum(r.get("cost_usd", 0) or 0 for r in results.values())
        logger.info("%s: %d/%d resolved (%.0f%%), cost $%.2f",
                    model, resolved, total, 100 * resolved / total if total else 0, cost)

    # Summary
    print("\n" + "=" * 60)
    print("Agent Ranking Results")
    print("=" * 60)
    print(f"{'Model':<12} {'Resolved':>10} {'Total':>8} {'Rate':>8} {'Cost':>10}")
    print("-" * 60)

    rates = {}
    for model in models:
        results = all_results[model]
        resolved = sum(1 for r in results.values() if r["resolved"])
        total = len(results)
        rate = resolved / total if total else 0
        cost = sum(r.get("cost_usd", 0) or 0 for r in results.values())
        rates[model] = rate
        print(f"{model:<12} {resolved:>10} {total:>8} {rate:>7.0%} {cost:>9.2f}")

    print("-" * 60)
    ordering = all(rates.get(models[i], 0) <= rates.get(models[i + 1], 0)
                   for i in range(len(models) - 1))
    rate_str = " <= ".join(f"{m}({rates.get(m, 0):.0%})" for m in models)
    print(f"Ordering: {rate_str}")
    print(f"Target (monotonic): {'PASS' if ordering else 'FAIL'}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "instances": len(instances),
        "models": {
            model: {
                "resolved": sum(1 for r in all_results[model].values() if r["resolved"]),
                "total": len(all_results[model]),
                "rate": rates.get(model, 0),
                "cost": sum(r.get("cost_usd", 0) or 0 for r in all_results[model].values()),
            }
            for model in models
        },
        "ordering_correct": ordering,
        "per_instance": all_results,
    }
    args.output.write_text(json.dumps(output, indent=2))
    logger.info("Results saved to %s", args.output)


if __name__ == "__main__":
    asyncio.run(main())
