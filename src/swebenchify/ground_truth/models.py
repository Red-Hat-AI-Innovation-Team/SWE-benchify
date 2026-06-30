from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class DescriptionSource:
    source_kind: str  # issue, pr_body, commit_message, review_comment, issue_comment, adr, doc, release_note, derived_summary
    source_id: str    # URL, issue number, commit SHA, or file path
    created_at: str   # ISO 8601 timestamp
    text: str
    allowed_for_task_prompt: bool = True
    leakage_risk: str = 'none'  # none, low, medium, high
    notes: str = ''


@dataclass
class GroundTruthChange:
    repo: str
    change_id: str          # pr:123, commit:<sha>, merge:<sha>, batch:<sha>..<sha>
    change_kind: str        # pull_request, direct_commit, merge_commit, squash_commit, commit_batch, patch_series, unknown
    base_commit: str
    head_commit: str
    merge_commit: str = ''
    landed_at: str = ''     # ISO 8601 timestamp
    title: str = ''
    body: str = ''
    description_sources: list[DescriptionSource] = field(default_factory=list)
    linked_issues: list[str] = field(default_factory=list)
    review_sources: list[str] = field(default_factory=list)
    full_diff: str = ''
    code_patch: str | None = None
    test_patch: str | None = None
    doc_patch: str | None = None
    tooling_patch: str | None = None
    agent_instruction_patch: str | None = None
    changed_files: list[str] = field(default_factory=list)
    link_confidence: float = 0.0
    extraction_warnings: list[str] = field(default_factory=list)


def save_ground_truth_changes(changes: list[GroundTruthChange], path: str) -> None:
    with open(path, "w") as f:
        for change in changes:
            f.write(json.dumps(asdict(change)) + "\n")


def load_ground_truth_changes(path: str) -> list[GroundTruthChange]:
    changes: list[GroundTruthChange] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "description_sources" in data:
                data["description_sources"] = [
                    DescriptionSource(**ds) for ds in data["description_sources"]
                ]
            changes.append(GroundTruthChange(**data))
    return changes
