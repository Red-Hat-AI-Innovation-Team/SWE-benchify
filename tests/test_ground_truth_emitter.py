from __future__ import annotations

import json

import pytest

from swebenchify.ground_truth.emitter import (
    emit_changes_jsonl,
    emit_descriptions_jsonl,
    emit_files_jsonl,
    emit_ground_truth,
    generate_report,
)
from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange

SAMPLE_DIFF = (
    "diff --git a/src/main.py b/src/main.py\n"
    "--- a/src/main.py\n"
    "+++ b/src/main.py\n"
    "@@ -1,3 +1,4 @@\n"
    " import os\n"
    "+import sys\n"
    " \n"
    " def main():\n"
)


def _make_change(change_id: str = "pr:123", **overrides) -> GroundTruthChange:
    defaults = dict(
        repo="owner/repo",
        change_id=change_id,
        change_kind="pull_request",
        base_commit="aaa111",
        head_commit="bbb222",
        full_diff=SAMPLE_DIFF,
        code_patch=SAMPLE_DIFF,
        changed_files=["src/main.py"],
        description_sources=[
            DescriptionSource(
                source_kind="commit_message",
                source_id="bbb222",
                created_at="2024-01-01T00:00:00Z",
                text="Fix bug",
            ),
        ],
        link_confidence=0.9,
    )
    defaults.update(overrides)
    return GroundTruthChange(**defaults)


class TestEmitChangesJsonl:
    def test_correct_format(self, tmp_path) -> None:
        changes = [_make_change("pr:1"), _make_change("pr:2")]
        path = emit_changes_jsonl(changes, str(tmp_path), "owner__repo")
        assert path.endswith("owner__repo-ground-truth-changes.jsonl")

        with open(path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2
        data = json.loads(lines[0])
        assert data["change_id"] == "pr:1"
        assert "description_sources" in data

    def test_empty_list(self, tmp_path) -> None:
        path = emit_changes_jsonl([], str(tmp_path), "owner__repo")
        with open(path) as f:
            assert f.read().strip() == ""


class TestEmitDescriptionsJsonl:
    def test_one_line_per_source(self, tmp_path) -> None:
        ds1 = DescriptionSource(
            source_kind="commit_message", source_id="sha1",
            created_at="", text="msg1",
        )
        ds2 = DescriptionSource(
            source_kind="issue", source_id="42",
            created_at="", text="issue body",
        )
        change = _make_change(description_sources=[ds1, ds2])
        path = emit_descriptions_jsonl([change], str(tmp_path), "owner__repo")

        with open(path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert record["change_id"] == "pr:123"
        assert record["source_kind"] == "commit_message"

    def test_no_descriptions(self, tmp_path) -> None:
        change = _make_change(description_sources=[])
        path = emit_descriptions_jsonl([change], str(tmp_path), "owner__repo")
        with open(path) as f:
            assert f.read().strip() == ""


class TestEmitFilesJsonl:
    def test_correct_fields(self, tmp_path) -> None:
        change = _make_change(changed_files=["src/main.py"])
        path = emit_files_jsonl([change], str(tmp_path), "owner__repo")

        with open(path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "change_id" in record
        assert "file_path" in record
        assert "patch_category" in record

    def test_empty_changes(self, tmp_path) -> None:
        path = emit_files_jsonl([], str(tmp_path), "owner__repo")
        with open(path) as f:
            assert f.read().strip() == ""


class TestGenerateReport:
    def test_contains_expected_sections(self, tmp_path) -> None:
        changes = [_make_change("pr:1"), _make_change("pr:2", change_kind="direct_commit")]
        check_results = {
            "pr:1": (True, []),
            "pr:2": (False, ["empty diff"]),
        }
        path = generate_report(changes, check_results, str(tmp_path), "owner__repo")

        with open(path) as f:
            content = f.read()
        assert "# Ground Truth Report" in content
        assert "Total changes" in content
        assert "Change Kind Breakdown" in content
        assert "Link Confidence" in content
        assert "Quality Check Results" in content
        assert "Patch Category Distribution" in content
        assert "Description Source Statistics" in content
        assert "1/2" in content


class TestEmitGroundTruth:
    def test_returns_all_file_paths(self, tmp_path) -> None:
        changes = [_make_change()]
        check_results = {"pr:123": (True, [])}
        result = emit_ground_truth(changes, str(tmp_path), "owner__repo", check_results)

        assert "changes" in result
        assert "descriptions" in result
        assert "files" in result
        assert "report" in result
        for path in result.values():
            assert path.startswith(str(tmp_path))

    def test_without_check_results(self, tmp_path) -> None:
        changes = [_make_change()]
        result = emit_ground_truth(changes, str(tmp_path), "owner__repo")
        assert "changes" in result
        assert "descriptions" in result
        assert "files" in result
        assert "report" not in result
