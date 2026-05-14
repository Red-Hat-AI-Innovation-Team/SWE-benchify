"""Compare our FAIL_TO_PASS against SWE-bench ground truth.

Downloads the SWE-bench dataset from HuggingFace and compares our
validated instances' FAIL_TO_PASS lists against theirs. Reports
per-instance and aggregate agreement rates.

See PLAN.md Section 1.2a and SPEC.md Section 9.2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class InstanceComparison:
    """Comparison result for a single instance."""

    instance_id: str
    ours: list[str]
    theirs: list[str]
    exact_match: bool
    our_subset_of_theirs: bool
    their_subset_of_ours: bool
    jaccard: float


@dataclass
class BenchmarkReport:
    """Aggregate comparison report."""

    comparisons: list[InstanceComparison] = field(default_factory=list)
    our_only: list[str] = field(default_factory=list)
    swebench_only: list[str] = field(default_factory=list)

    @property
    def total_compared(self) -> int:
        return len(self.comparisons)

    @property
    def exact_match_count(self) -> int:
        return sum(1 for c in self.comparisons if c.exact_match)

    @property
    def exact_match_rate(self) -> float:
        if not self.comparisons:
            return 0.0
        return self.exact_match_count / self.total_compared

    @property
    def subset_match_count(self) -> int:
        return sum(
            1
            for c in self.comparisons
            if c.our_subset_of_theirs or c.their_subset_of_ours
        )

    @property
    def subset_match_rate(self) -> float:
        if not self.comparisons:
            return 0.0
        return self.subset_match_count / self.total_compared

    @property
    def mean_jaccard(self) -> float:
        if not self.comparisons:
            return 0.0
        return sum(c.jaccard for c in self.comparisons) / self.total_compared


def jaccard_similarity(a: list[str], b: list[str]) -> float:
    """Compute Jaccard similarity between two lists of test names."""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def compare_fail_to_pass(
    ours: list[str],
    theirs: list[str],
    instance_id: str = "",
) -> InstanceComparison:
    """Compare two FAIL_TO_PASS lists and return detailed metrics."""
    set_ours = set(ours)
    set_theirs = set(theirs)
    return InstanceComparison(
        instance_id=instance_id,
        ours=ours,
        theirs=theirs,
        exact_match=set_ours == set_theirs,
        our_subset_of_theirs=set_ours <= set_theirs,
        their_subset_of_ours=set_theirs <= set_ours,
        jaccard=jaccard_similarity(ours, theirs),
    )


def load_swebench_ground_truth(
    dataset_name: str = "princeton-nlp/SWE-bench",
    split: str = "test",
) -> dict[str, list[str]]:
    """Load FAIL_TO_PASS from the SWE-bench HuggingFace dataset.

    Returns a dict mapping instance_id -> FAIL_TO_PASS list.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError(
            "The 'datasets' package is required. "
            "Install with: pip install datasets"
        )

    ds = load_dataset(dataset_name, split=split)
    ground_truth: dict[str, list[str]] = {}
    for row in ds:
        instance_id = row["instance_id"]
        f2p_raw = row["FAIL_TO_PASS"]
        if isinstance(f2p_raw, str):
            f2p = json.loads(f2p_raw)
        else:
            f2p = list(f2p_raw)
        ground_truth[instance_id] = f2p
    logger.info(
        "Loaded %d instances from %s/%s", len(ground_truth), dataset_name, split
    )
    return ground_truth


def load_our_instances(jsonl_path: str | Path) -> dict[str, list[str]]:
    """Load FAIL_TO_PASS from our validated JSONL output.

    Returns a dict mapping instance_id -> FAIL_TO_PASS list.
    """
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    instances: dict[str, list[str]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            instance_id = data["instance_id"]
            f2p_raw = data.get("FAIL_TO_PASS", "[]")
            if isinstance(f2p_raw, str):
                f2p = json.loads(f2p_raw)
            else:
                f2p = list(f2p_raw)
            instances[instance_id] = f2p
    logger.info("Loaded %d instances from %s", len(instances), path)
    return instances


def run_comparison(
    our_instances: dict[str, list[str]],
    swebench_instances: dict[str, list[str]],
) -> BenchmarkReport:
    """Compare our FAIL_TO_PASS against SWE-bench ground truth.

    Args:
        our_instances: mapping of instance_id -> FAIL_TO_PASS from our output
        swebench_instances: mapping of instance_id -> FAIL_TO_PASS from SWE-bench

    Returns:
        BenchmarkReport with per-instance comparisons and aggregate metrics.
    """
    our_ids = set(our_instances.keys())
    swebench_ids = set(swebench_instances.keys())
    overlap = our_ids & swebench_ids

    report = BenchmarkReport(
        our_only=sorted(our_ids - swebench_ids),
        swebench_only=sorted(swebench_ids - our_ids),
    )

    for instance_id in sorted(overlap):
        comparison = compare_fail_to_pass(
            our_instances[instance_id],
            swebench_instances[instance_id],
            instance_id=instance_id,
        )
        report.comparisons.append(comparison)

    return report


def format_report(report: BenchmarkReport) -> str:
    """Format a BenchmarkReport as a human-readable string."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("FAIL_TO_PASS Comparison: SWE-benchify vs SWE-bench Ground Truth")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Instances compared:      {report.total_compared}")
    lines.append(f"Our-only instances:      {len(report.our_only)}")
    lines.append(f"SWE-bench-only:          {len(report.swebench_only)}")
    lines.append("")
    lines.append("--- Aggregate Metrics ---")
    lines.append(
        f"Exact match rate:        {report.exact_match_rate:.1%} "
        f"({report.exact_match_count}/{report.total_compared})"
    )
    lines.append(
        f"Subset match rate:       {report.subset_match_rate:.1%} "
        f"({report.subset_match_count}/{report.total_compared})"
    )
    lines.append(f"Mean Jaccard similarity: {report.mean_jaccard:.3f}")
    lines.append(
        f"Target (>=85%):          {'PASS' if report.exact_match_rate >= 0.85 else 'FAIL'}"
    )
    lines.append("")

    if report.comparisons:
        lines.append("--- Per-Instance Results ---")
        for c in report.comparisons:
            status = "EXACT" if c.exact_match else f"J={c.jaccard:.2f}"
            lines.append(f"  {c.instance_id}: {status}")
            if not c.exact_match:
                only_ours = set(c.ours) - set(c.theirs)
                only_theirs = set(c.theirs) - set(c.ours)
                if only_ours:
                    lines.append(f"    +ours:   {sorted(only_ours)}")
                if only_theirs:
                    lines.append(f"    +theirs: {sorted(only_theirs)}")
        lines.append("")

    if report.our_only:
        lines.append(f"--- Our-only instances ({len(report.our_only)}) ---")
        for iid in report.our_only:
            lines.append(f"  {iid}")
        lines.append("")

    if report.swebench_only:
        lines.append(
            f"--- SWE-bench-only instances ({len(report.swebench_only)}) ---"
        )
        for iid in report.swebench_only[:20]:
            lines.append(f"  {iid}")
        if len(report.swebench_only) > 20:
            lines.append(f"  ... and {len(report.swebench_only) - 20} more")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point: compare our output against SWE-bench ground truth."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare FAIL_TO_PASS against SWE-bench ground truth"
    )
    parser.add_argument(
        "jsonl",
        help="Path to our validated JSONL output file",
    )
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench",
        help="HuggingFace dataset name (default: princeton-nlp/SWE-bench)",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Dataset split (default: test)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    swebench = load_swebench_ground_truth(args.dataset, args.split)
    ours = load_our_instances(args.jsonl)
    report = run_comparison(ours, swebench)
    print(format_report(report))


if __name__ == "__main__":
    main()
