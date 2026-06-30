from __future__ import annotations

import re
import subprocess
from io import StringIO

from unidiff import PatchSet

from swebenchify.ground_truth.models import GroundTruthChange

_CHANGE_ID_RE = re.compile(r"^(pr:\d+|commit:[0-9a-f]+|merge:[0-9a-f]+|batch:[0-9a-f]+\.\.[0-9a-f]+)$")


def check_commits_exist(change: GroundTruthChange, repo_path: str) -> list[str]:
    warnings: list[str] = []
    for label, sha in [("base_commit", change.base_commit), ("head_commit", change.head_commit)]:
        if not sha:
            warnings.append(f"{label} is empty")
            continue
        result = subprocess.run(
            ["git", "cat-file", "-e", sha],
            capture_output=True,
            cwd=repo_path,
        )
        if result.returncode != 0:
            warnings.append(f"{label} {sha} not found in repository")
    return warnings


def check_diff_not_empty(change: GroundTruthChange) -> list[str]:
    if not change.full_diff or not change.full_diff.strip():
        return [f"full_diff is empty for {change.change_id}"]
    return []


def check_patch_reconstruction(change: GroundTruthChange) -> list[str]:
    if not change.full_diff or not change.full_diff.strip():
        return []

    try:
        original_files = {pf.path for pf in PatchSet(StringIO(change.full_diff))}
    except Exception:
        return [f"Could not parse full_diff for {change.change_id}"]

    reconstructed_files: set[str] = set()
    for patch_text in [
        change.code_patch,
        change.test_patch,
        change.doc_patch,
        change.tooling_patch,
        change.agent_instruction_patch,
    ]:
        if patch_text is None:
            continue
        try:
            for pf in PatchSet(StringIO(patch_text)):
                reconstructed_files.add(pf.path)
        except Exception:
            return [f"Could not parse a patch category for {change.change_id}"]

    missing = original_files - reconstructed_files
    extra = reconstructed_files - original_files
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"{len(missing)} file(s) from full_diff not in any patch category: "
            + ", ".join(sorted(missing))
        )
    if extra:
        warnings.append(
            f"{len(extra)} file(s) in patch categories but not in full_diff: "
            + ", ".join(sorted(extra))
        )
    return warnings


def check_description_provenance(change: GroundTruthChange) -> list[str]:
    if not change.description_sources:
        return [f"No description sources for {change.change_id}"]

    has_safe_source = any(
        ds.allowed_for_task_prompt and ds.leakage_risk in ("none", "low")
        for ds in change.description_sources
    )
    if not has_safe_source:
        return [
            f"No description source with allowed_for_task_prompt=True and "
            f"leakage_risk in ('none', 'low') for {change.change_id}"
        ]
    return []


def check_change_id_format(change: GroundTruthChange) -> list[str]:
    if not _CHANGE_ID_RE.match(change.change_id):
        return [
            f"change_id '{change.change_id}' does not match expected format "
            f"(pr:N, commit:HEX, merge:HEX)"
        ]
    return []


def run_all_checks(
    change: GroundTruthChange,
    repo_path: str | None = None,
) -> tuple[bool, list[str]]:
    all_warnings: list[str] = []

    if repo_path is not None:
        all_warnings.extend(check_commits_exist(change, repo_path))

    all_warnings.extend(check_diff_not_empty(change))
    all_warnings.extend(check_patch_reconstruction(change))
    all_warnings.extend(check_description_provenance(change))
    all_warnings.extend(check_change_id_format(change))

    change.extraction_warnings = all_warnings
    return (len(all_warnings) == 0, all_warnings)
