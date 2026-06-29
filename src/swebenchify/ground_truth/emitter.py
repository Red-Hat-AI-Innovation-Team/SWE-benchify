from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict
from io import StringIO

from unidiff import PatchSet

from swebenchify.ground_truth.models import GroundTruthChange
from swebenchify.ground_truth.patch_categorizer import categorize_file


def emit_changes_jsonl(
    changes: list[GroundTruthChange],
    output_dir: str,
    repo_slug: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{repo_slug}-ground-truth-changes.jsonl")
    with open(path, "w") as f:
        for change in changes:
            f.write(json.dumps(asdict(change)) + "\n")
    return path


def emit_descriptions_jsonl(
    changes: list[GroundTruthChange],
    output_dir: str,
    repo_slug: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{repo_slug}-ground-truth-descriptions.jsonl")
    with open(path, "w") as f:
        for change in changes:
            for ds in change.description_sources:
                record = {
                    "change_id": change.change_id,
                    "source_kind": ds.source_kind,
                    "source_id": ds.source_id,
                    "created_at": ds.created_at,
                    "text": ds.text,
                    "allowed_for_task_prompt": ds.allowed_for_task_prompt,
                    "leakage_risk": ds.leakage_risk,
                    "notes": ds.notes,
                }
                f.write(json.dumps(record) + "\n")
    return path


def emit_files_jsonl(
    changes: list[GroundTruthChange],
    output_dir: str,
    repo_slug: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{repo_slug}-ground-truth-files.jsonl")
    with open(path, "w") as f:
        for change in changes:
            file_categories = _get_file_categories(change)
            for file_path, category in file_categories.items():
                record = {
                    "change_id": change.change_id,
                    "file_path": file_path,
                    "patch_category": category,
                }
                f.write(json.dumps(record) + "\n")
    return path


def _get_file_categories(change: GroundTruthChange) -> dict[str, str]:
    categories: dict[str, str] = {}
    patch_map = {
        "code": change.code_patch,
        "test": change.test_patch,
        "doc": change.doc_patch,
        "tooling": change.tooling_patch,
        "agent_instruction": change.agent_instruction_patch,
    }
    for category, patch_text in patch_map.items():
        if patch_text is None:
            continue
        try:
            for pf in PatchSet(StringIO(patch_text)):
                categories[pf.path] = category
        except Exception:
            pass

    for fp in change.changed_files:
        if fp not in categories:
            categories[fp] = categorize_file(fp)
    return categories


def generate_report(
    changes: list[GroundTruthChange],
    check_results: dict[str, tuple[bool, list[str]]],
    output_dir: str,
    repo_slug: str,
    taxonomy_classifications: dict[str, object] | None = None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{repo_slug}-ground-truth-report.md")

    kind_counts = Counter(c.change_kind for c in changes)

    confidence_ranges = {"high (>=0.8)": 0, "medium (0.5-0.8)": 0, "low (<0.5)": 0}
    for c in changes:
        if c.link_confidence >= 0.8:
            confidence_ranges["high (>=0.8)"] += 1
        elif c.link_confidence >= 0.5:
            confidence_ranges["medium (0.5-0.8)"] += 1
        else:
            confidence_ranges["low (<0.5)"] += 1

    total_checks = len(check_results)
    passed_checks = sum(1 for passed, _ in check_results.values() if passed)

    patch_categories = Counter()
    for c in changes:
        if c.code_patch:
            patch_categories["code"] += 1
        if c.test_patch:
            patch_categories["test"] += 1
        if c.doc_patch:
            patch_categories["doc"] += 1
        if c.tooling_patch:
            patch_categories["tooling"] += 1
        if c.agent_instruction_patch:
            patch_categories["agent_instruction"] += 1

    desc_counts = Counter()
    for c in changes:
        for ds in c.description_sources:
            desc_counts[ds.source_kind] += 1

    lines = [
        f"# Ground Truth Report: {repo_slug}",
        "",
        "## Summary",
        "",
        f"- **Total changes**: {len(changes)}",
        "",
        "## Change Kind Breakdown",
        "",
    ]
    for kind, count in sorted(kind_counts.items()):
        lines.append(f"- {kind}: {count}")

    lines += [
        "",
        "## Link Confidence",
        "",
    ]
    for label, count in confidence_ranges.items():
        lines.append(f"- {label}: {count}")

    lines += [
        "",
        "## Quality Check Results",
        "",
        f"- Pass rate: {passed_checks}/{total_checks}"
        + (f" ({100 * passed_checks // total_checks}%)" if total_checks else ""),
        "",
    ]

    lines += [
        "## Patch Category Distribution",
        "",
    ]
    for cat, count in sorted(patch_categories.items()):
        lines.append(f"- {cat}: {count}")

    lines += [
        "",
        "## Description Source Statistics",
        "",
    ]
    for kind, count in sorted(desc_counts.items()):
        lines.append(f"- {kind}: {count}")

    if taxonomy_classifications:
        level_counts: dict[str, int] = {"F0": 0, "F1": 0, "F2": 0, "F3": 0, "F4": 0}
        question_true_counts: Counter = Counter()
        for tc in taxonomy_classifications.values():
            level = getattr(tc, "framework_level", "F0")
            level_counts[level] = level_counts.get(level, 0) + 1
            for ev in getattr(tc, "evaluations", []):
                if getattr(ev, "answer", False):
                    question_true_counts[ev.question_id] += 1

        total_classified = sum(level_counts.values())
        lines += [
            "",
            "## Taxonomy Distribution",
            "",
        ]
        for level in ("F0", "F1", "F2", "F3", "F4"):
            count = level_counts[level]
            pct = (100 * count // total_classified) if total_classified else 0
            lines.append(f"- {level}: {count} ({pct}%)")

        if question_true_counts:
            lines += [
                "",
                "### Top Questions (most common True)",
                "",
            ]
            for qid, qcount in question_true_counts.most_common(3):
                lines.append(f"- {qid}: {qcount}")

    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def emit_ground_truth(
    changes: list[GroundTruthChange],
    output_dir: str,
    repo_slug: str,
    check_results: dict[str, tuple[bool, list[str]]] | None = None,
) -> dict[str, str]:
    results: dict[str, str] = {}
    results["changes"] = emit_changes_jsonl(changes, output_dir, repo_slug)
    results["descriptions"] = emit_descriptions_jsonl(changes, output_dir, repo_slug)
    results["files"] = emit_files_jsonl(changes, output_dir, repo_slug)
    if check_results is not None:
        results["report"] = generate_report(changes, check_results, output_dir, repo_slug)
    return results
