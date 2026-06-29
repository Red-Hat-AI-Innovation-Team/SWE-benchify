from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from swebenchify.ground_truth.models import (
    DescriptionSource,
    GroundTruthChange,
    load_ground_truth_changes,
    save_ground_truth_changes,
)


class TestDescriptionSource:
    def test_construction(self) -> None:
        ds = DescriptionSource(
            source_kind="issue",
            source_id="https://github.com/owner/repo/issues/42",
            created_at="2024-01-15T10:30:00Z",
            text="Fix the login redirect bug",
        )
        assert ds.source_kind == "issue"
        assert ds.source_id == "https://github.com/owner/repo/issues/42"
        assert ds.created_at == "2024-01-15T10:30:00Z"
        assert ds.text == "Fix the login redirect bug"
        assert ds.allowed_for_task_prompt is True
        assert ds.leakage_risk == "none"
        assert ds.notes == ""

    def test_asdict_round_trip(self) -> None:
        ds = DescriptionSource(
            source_kind="pr_body",
            source_id="pr:99",
            created_at="2024-06-01T00:00:00Z",
            text="Refactor auth module",
            allowed_for_task_prompt=False,
            leakage_risk="high",
            notes="Contains fix details",
        )
        d = asdict(ds)
        serialised = json.dumps(d)
        restored = DescriptionSource(**json.loads(serialised))
        assert restored == ds


class TestGroundTruthChange:
    def test_construction_all_fields(self) -> None:
        ds = DescriptionSource(
            source_kind="commit_message",
            source_id="abc123",
            created_at="2024-01-01T00:00:00Z",
            text="Fix bug",
        )
        change = GroundTruthChange(
            repo="owner/repo",
            change_id="pr:123",
            change_kind="pull_request",
            base_commit="aaa111",
            head_commit="bbb222",
            merge_commit="ccc333",
            landed_at="2024-02-01T12:00:00Z",
            title="Fix login bug",
            body="Closes #42",
            description_sources=[ds],
            linked_issues=["42"],
            review_sources=["https://github.com/owner/repo/pull/123#review-1"],
            full_diff="diff --git a/file.py ...",
            code_patch="--- a/file.py\n+++ b/file.py\n",
            test_patch="--- a/test_file.py\n+++ b/test_file.py\n",
            doc_patch=None,
            tooling_patch=None,
            agent_instruction_patch=None,
            changed_files=["file.py", "test_file.py"],
            link_confidence=0.95,
            extraction_warnings=[],
        )
        assert change.repo == "owner/repo"
        assert change.change_id == "pr:123"
        assert change.merge_commit == "ccc333"
        assert len(change.description_sources) == 1
        assert change.link_confidence == 0.95

    def test_construction_with_defaults(self) -> None:
        change = GroundTruthChange(
            repo="owner/repo",
            change_id="commit:abc123",
            change_kind="direct_commit",
            base_commit="aaa111",
            head_commit="bbb222",
        )
        assert change.merge_commit == ""
        assert change.landed_at == ""
        assert change.title == ""
        assert change.body == ""
        assert change.description_sources == []
        assert change.linked_issues == []
        assert change.review_sources == []
        assert change.full_diff == ""
        assert change.code_patch is None
        assert change.test_patch is None
        assert change.doc_patch is None
        assert change.tooling_patch is None
        assert change.agent_instruction_patch is None
        assert change.changed_files == []
        assert change.link_confidence == 0.0
        assert change.extraction_warnings == []

    def test_asdict_round_trip(self) -> None:
        ds = DescriptionSource(
            source_kind="issue",
            source_id="42",
            created_at="2024-01-01T00:00:00Z",
            text="Bug report",
        )
        change = GroundTruthChange(
            repo="owner/repo",
            change_id="pr:123",
            change_kind="pull_request",
            base_commit="aaa",
            head_commit="bbb",
            description_sources=[ds],
            changed_files=["a.py"],
        )
        d = asdict(change)
        serialised = json.dumps(d)
        data = json.loads(serialised)
        data["description_sources"] = [
            DescriptionSource(**s) for s in data["description_sources"]
        ]
        restored = GroundTruthChange(**data)
        assert restored == change

    def test_change_id_pr_format(self) -> None:
        change = GroundTruthChange(
            repo="r", change_id="pr:123", change_kind="pull_request",
            base_commit="a", head_commit="b",
        )
        assert change.change_id.startswith("pr:")

    def test_change_id_commit_format(self) -> None:
        change = GroundTruthChange(
            repo="r", change_id="commit:abc123", change_kind="direct_commit",
            base_commit="a", head_commit="b",
        )
        assert change.change_id.startswith("commit:")

    def test_change_id_merge_format(self) -> None:
        change = GroundTruthChange(
            repo="r", change_id="merge:def456", change_kind="merge_commit",
            base_commit="a", head_commit="b",
        )
        assert change.change_id.startswith("merge:")

    def test_leakage_risk_values(self) -> None:
        valid_risks = ["none", "low", "medium", "high"]
        for risk in valid_risks:
            ds = DescriptionSource(
                source_kind="issue",
                source_id="1",
                created_at="2024-01-01T00:00:00Z",
                text="text",
                leakage_risk=risk,
            )
            assert ds.leakage_risk == risk


class TestJsonlRoundTrip:
    def test_save_and_load(self, tmp_path) -> None:
        ds = DescriptionSource(
            source_kind="pr_body",
            source_id="pr:10",
            created_at="2024-03-01T00:00:00Z",
            text="PR description",
            leakage_risk="low",
        )
        changes = [
            GroundTruthChange(
                repo="owner/repo",
                change_id="pr:10",
                change_kind="pull_request",
                base_commit="aaa",
                head_commit="bbb",
                description_sources=[ds],
                changed_files=["x.py"],
                link_confidence=0.8,
            ),
            GroundTruthChange(
                repo="owner/repo",
                change_id="commit:ccc",
                change_kind="direct_commit",
                base_commit="ddd",
                head_commit="eee",
            ),
        ]
        path = str(tmp_path / "changes.jsonl")
        save_ground_truth_changes(changes, path)
        loaded = load_ground_truth_changes(path)
        assert len(loaded) == 2
        assert loaded[0] == changes[0]
        assert loaded[1] == changes[1]
        assert loaded[0].description_sources[0].leakage_risk == "low"
