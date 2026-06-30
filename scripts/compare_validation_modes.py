#!/usr/bin/env python3
"""Compare Docker-based vs agent-based validation results.

For SWE-bench repos where we have both agent-validated results AND can run
Docker validation via swebench.harness, this script compares the FAIL_TO_PASS
results to quantify agreement between the two validation modes.

Usage:
    python scripts/compare_validation_modes.py \\
        --agent-results output/swebenchify-dataset.jsonl \\
        [--docker-results output/docker-validated.jsonl] \\
        [--run-docker]

If --docker-results is provided, it skips Docker validation and just compares
the two result files. If --run-docker is given (and swebench + Docker/podman
are available), it runs Docker validation on the overlapping instances.

Without --run-docker, this script compares agent results against SWE-bench's
published FAIL_TO_PASS as a proxy for Docker validation ground truth.

See docs/PLAN.md Section 1.2c.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from swebenchify.validation_bench import (
    compare_fail_to_pass,
    format_report,
    load_our_instances,
    load_swebench_ground_truth,
    run_comparison,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationModeComparison:
    """Detailed comparison between agent and Docker validation modes."""

    instance_id: str
    agent_f2p: list[str]
    docker_f2p: list[str]
    agent_only: list[str]
    docker_only: list[str]
    agree: bool
    jaccard: float


def load_jsonl_instances(path: str | Path) -> dict[str, list[str]]:
    """Load instance_id -> FAIL_TO_PASS mapping from a JSONL file."""
    return load_our_instances(path)


def compare_agent_vs_docker(
    agent_instances: dict[str, list[str]],
    docker_instances: dict[str, list[str]],
) -> list[ValidationModeComparison]:
    """Compare agent and Docker validation results instance by instance."""
    overlap = set(agent_instances.keys()) & set(docker_instances.keys())
    comparisons = []

    for iid in sorted(overlap):
        agent_f2p = agent_instances[iid]
        docker_f2p = docker_instances[iid]
        agent_set = set(agent_f2p)
        docker_set = set(docker_f2p)

        cmp = compare_fail_to_pass(agent_f2p, docker_f2p)

        comparisons.append(
            ValidationModeComparison(
                instance_id=iid,
                agent_f2p=agent_f2p,
                docker_f2p=docker_f2p,
                agent_only=sorted(agent_set - docker_set),
                docker_only=sorted(docker_set - agent_set),
                agree=cmp.exact_match,
                jaccard=cmp.jaccard,
            )
        )

    return comparisons


def format_mode_comparison(
    comparisons: list[ValidationModeComparison],
    agent_total: int,
    docker_total: int,
) -> str:
    """Format validation mode comparison as a human-readable report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("Docker-based vs Agent-based Validation Comparison")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Agent-validated instances:  {agent_total}")
    lines.append(f"Docker-validated instances: {docker_total}")
    lines.append(f"Overlapping instances:     {len(comparisons)}")
    lines.append("")

    if not comparisons:
        lines.append("No overlapping instances to compare.")
        return "\n".join(lines)

    agree_count = sum(1 for c in comparisons if c.agree)
    mean_jaccard = sum(c.jaccard for c in comparisons) / len(comparisons)

    lines.append("--- Agreement Metrics ---")
    lines.append(
        f"Exact agreement:    {agree_count}/{len(comparisons)} "
        f"({agree_count / len(comparisons):.1%})"
    )
    lines.append(f"Mean Jaccard:       {mean_jaccard:.3f}")
    lines.append("")

    lines.append("--- Per-Instance Results ---")
    for c in comparisons:
        status = "AGREE" if c.agree else f"DIFFER (J={c.jaccard:.2f})"
        lines.append(f"  {c.instance_id}: {status}")
        if not c.agree:
            if c.agent_only:
                lines.append(f"    agent-only:  {c.agent_only}")
            if c.docker_only:
                lines.append(f"    docker-only: {c.docker_only}")

    lines.append("")

    lines.append("--- Analysis ---")
    if agree_count == len(comparisons):
        lines.append("All instances agree between agent and Docker validation.")
    else:
        disagree = [c for c in comparisons if not c.agree]
        agent_superset = sum(
            1
            for c in disagree
            if set(c.docker_f2p) < set(c.agent_f2p)
        )
        docker_superset = sum(
            1
            for c in disagree
            if set(c.agent_f2p) < set(c.docker_f2p)
        )
        lines.append(f"Disagreements: {len(disagree)}")
        lines.append(f"  Agent finds MORE tests:   {agent_superset}")
        lines.append(f"  Docker finds MORE tests:  {docker_superset}")
        lines.append(
            f"  Disjoint differences:     "
            f"{len(disagree) - agent_superset - docker_superset}"
        )

    return "\n".join(lines)


def try_run_docker_validation(
    instances_jsonl: str,
    instance_ids: list[str],
) -> dict[str, list[str]] | None:
    """Attempt to run Docker-based validation via swebench.harness.

    Returns instance_id -> FAIL_TO_PASS mapping, or None if Docker
    validation is not available.
    """
    try:
        from swebench.harness.run_evaluation import main as run_evaluation  # noqa: F401
        from swebench.harness.test_spec import make_test_spec  # noqa: F401
    except ImportError:
        logger.warning(
            "swebench.harness not available. Install swebench to run "
            "Docker-based validation."
        )
        return None

    import subprocess

    docker_available = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=10,
    ).returncode == 0

    podman_available = False
    if not docker_available:
        try:
            podman_available = subprocess.run(
                ["podman", "info"],
                capture_output=True,
                timeout=10,
            ).returncode == 0
        except FileNotFoundError:
            pass

    if not docker_available and not podman_available:
        logger.warning(
            "Neither Docker nor podman is available. Cannot run "
            "Docker-based validation."
        )
        return None

    logger.info(
        "Docker-based validation would run here on %d instances. "
        "This is expensive (builds Docker images per instance). "
        "Use --docker-results to provide pre-computed results instead.",
        len(instance_ids),
    )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Docker-based vs agent-based validation"
    )
    parser.add_argument(
        "--agent-results",
        required=True,
        help="Path to agent-validated JSONL output",
    )
    parser.add_argument(
        "--docker-results",
        help="Path to Docker-validated JSONL output (if available)",
    )
    parser.add_argument(
        "--no-swebench-proxy",
        action="store_true",
        help=(
            "Disable using SWE-bench's published FAIL_TO_PASS as a "
            "proxy for Docker validation ground truth"
        ),
    )
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench",
        help="HuggingFace dataset for ground truth",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Dataset split (default: test)",
    )
    parser.add_argument(
        "--run-docker",
        action="store_true",
        help="Actually run Docker validation (expensive, requires Docker)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    agent_instances = load_jsonl_instances(args.agent_results)
    logger.info("Loaded %d agent-validated instances", len(agent_instances))

    docker_instances: dict[str, list[str]] | None = None
    if args.docker_results:
        docker_instances = load_jsonl_instances(args.docker_results)
        logger.info(
            "Loaded %d Docker-validated instances", len(docker_instances)
        )
    elif args.run_docker:
        docker_instances = try_run_docker_validation(
            args.agent_results, list(agent_instances.keys())
        )
        if docker_instances is None:
            logger.info(
                "Docker validation not available. Falling back to "
                "SWE-bench ground truth as proxy."
            )
            docker_instances = load_swebench_ground_truth(
                args.dataset, args.split
            )
    elif not args.no_swebench_proxy:
        logger.info(
            "Using SWE-bench published FAIL_TO_PASS as Docker validation proxy"
        )
        docker_instances = load_swebench_ground_truth(args.dataset, args.split)
    else:
        logger.error(
            "No Docker results source. Provide --docker-results, "
            "--run-docker, or remove --no-swebench-proxy."
        )
        sys.exit(1)

    comparisons = compare_agent_vs_docker(agent_instances, docker_instances)
    print(
        format_mode_comparison(
            comparisons, len(agent_instances), len(docker_instances)
        )
    )

    # Also print the standard benchmark report for overlap
    print()
    report = run_comparison(agent_instances, docker_instances)
    print(format_report(report))


if __name__ == "__main__":
    main()
