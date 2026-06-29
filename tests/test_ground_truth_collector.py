from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from swebenchify.config import GroundTruthConfig
from swebenchify.ground_truth.collector import (
    collect_pr_ground_truth,
    load_ground_truth_changes,
    pr_to_ground_truth_change,
    save_ground_truth_changes,
)
from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange
from swebenchify.models import CandidatePR, Repository


def _make_pr(**overrides) -> CandidatePR:
    defaults = dict(
        repo="owner/repo",
        pr_number=42,
        title="Fix login bug",
        body="Closes #10\n\nThis fixes the redirect issue.",
        base_commit="aaa111",
        merge_commit="bbb222",
        diff_url="https://api.github.com/repos/owner/repo/pulls/42",
        resolved_issues=[10],
        created_at="2024-01-15T10:00:00Z",
        merged_at="2024-01-16T12:00:00Z",
        link_confidence=1.0,
    )
    defaults.update(overrides)
    return CandidatePR(**defaults)


def _make_diff(files: dict[str, str]) -> str:
    parts = []
    for path, line in files.items():
        parts.append(
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -1,1 +1,2 @@\n"
            f" existing\n"
            f"+{line}\n"
        )
    return "".join(parts)


class TestPrToGroundTruthChange:
    def test_all_fields_populated(self) -> None:
        pr = _make_pr()
        diff = _make_diff({"src/main.py": "fix", "tests/test_main.py": "test"})
        change = pr_to_ground_truth_change(pr, diff)

        assert change.repo == "owner/repo"
        assert change.change_id == "pr:42"
        assert change.change_kind == "pull_request"
        assert change.base_commit == "aaa111"
        assert change.head_commit == "bbb222"
        assert change.merge_commit == "bbb222"
        assert change.landed_at == "2024-01-16T12:00:00Z"
        assert change.title == "Fix login bug"
        assert change.link_confidence == 1.0
        assert change.code_patch is not None
        assert change.test_patch is not None
        assert "src/main.py" in change.changed_files
        assert "tests/test_main.py" in change.changed_files

    def test_linked_issues_populated(self) -> None:
        pr = _make_pr(
            resolved_issues=[10, 20],
            resolved_jira_issues=["OCPBUGS-123"],
        )
        diff = _make_diff({"src/main.py": "fix"})
        change = pr_to_ground_truth_change(pr, diff)
        assert "10" in change.linked_issues
        assert "20" in change.linked_issues
        assert "OCPBUGS-123" in change.linked_issues

    def test_link_confidence_propagation(self) -> None:
        pr = _make_pr(link_confidence=0.7)
        diff = _make_diff({"src/main.py": "fix"})
        change = pr_to_ground_truth_change(pr, diff)
        assert change.link_confidence == 0.7

    def test_description_source_from_pr_body(self) -> None:
        pr = _make_pr(title="My title", body="My body")
        diff = _make_diff({"src/main.py": "fix"})
        change = pr_to_ground_truth_change(pr, diff)
        assert len(change.description_sources) == 1
        ds = change.description_sources[0]
        assert ds.source_kind == "pr_body"
        assert ds.source_id == "pr:42"
        assert ds.leakage_risk == "medium"
        assert "My title" in ds.text
        assert "My body" in ds.text

    def test_split_patch_5way_integration(self) -> None:
        pr = _make_pr()
        diff = _make_diff({
            "src/main.py": "code",
            "tests/test_main.py": "test",
            "README.md": "doc",
        })
        change = pr_to_ground_truth_change(pr, diff)
        assert change.code_patch is not None
        assert change.test_patch is not None
        assert change.doc_patch is not None
        assert change.tooling_patch is None
        assert change.agent_instruction_patch is None

    def test_empty_diff(self) -> None:
        pr = _make_pr()
        change = pr_to_ground_truth_change(pr, "")
        assert change.code_patch is None
        assert change.test_patch is None
        assert change.changed_files == []


class TestJsonlRoundTrip:
    def test_save_load_with_nested_description_source(self, tmp_path) -> None:
        ds = DescriptionSource(
            source_kind="pr_body",
            source_id="pr:42",
            created_at="2024-01-15T10:00:00Z",
            text="Fix login bug\nCloses #10",
            leakage_risk="medium",
        )
        changes = [
            GroundTruthChange(
                repo="owner/repo",
                change_id="pr:42",
                change_kind="pull_request",
                base_commit="aaa",
                head_commit="bbb",
                description_sources=[ds],
                link_confidence=1.0,
            ),
        ]
        path = str(tmp_path / "changes.jsonl")
        save_ground_truth_changes(changes, path)
        loaded = load_ground_truth_changes(path)
        assert len(loaded) == 1
        assert loaded[0] == changes[0]
        assert loaded[0].description_sources[0].leakage_risk == "medium"


class TestCollectPrGroundTruth:
    @patch("swebenchify.ground_truth.collector._fetch_pr_diff")
    @patch("swebenchify.ground_truth.collector.collect_prs")
    def test_resumption_skips_existing(self, mock_collect, mock_diff) -> None:
        mock_collect.return_value = [
            _make_pr(pr_number=1),
            _make_pr(pr_number=2),
            _make_pr(pr_number=3),
        ]
        mock_diff.return_value = _make_diff({"src/main.py": "fix"})

        repo = Repository(full_name="owner/repo", access_token="fake")
        config = GroundTruthConfig()
        changes = collect_pr_ground_truth(
            repo, config,
            existing_change_ids={"pr:1", "pr:3"},
        )
        assert len(changes) == 1
        assert changes[0].change_id == "pr:2"

    @patch("swebenchify.ground_truth.collector._fetch_pr_diff")
    @patch("swebenchify.ground_truth.collector.collect_prs")
    def test_empty_pr_list(self, mock_collect, mock_diff) -> None:
        mock_collect.return_value = []
        repo = Repository(full_name="owner/repo", access_token="fake")
        config = GroundTruthConfig()
        changes = collect_pr_ground_truth(repo, config)
        assert changes == []

    @patch("swebenchify.ground_truth.collector._fetch_pr_diff")
    @patch("swebenchify.ground_truth.collector.collect_prs")
    def test_min_link_confidence_filtering(self, mock_collect, mock_diff) -> None:
        mock_collect.return_value = [
            _make_pr(pr_number=1, link_confidence=0.3),
            _make_pr(pr_number=2, link_confidence=0.8),
            _make_pr(pr_number=3, link_confidence=1.0),
        ]
        mock_diff.return_value = _make_diff({"src/main.py": "fix"})

        repo = Repository(full_name="owner/repo", access_token="fake")
        config = GroundTruthConfig(min_link_confidence=0.5)
        changes = collect_pr_ground_truth(repo, config)
        assert len(changes) == 2
        assert all(c.link_confidence >= 0.5 for c in changes)

    @patch("swebenchify.ground_truth.collector._fetch_pr_diff")
    @patch("swebenchify.ground_truth.collector.collect_prs")
    def test_on_change_callback(self, mock_collect, mock_diff) -> None:
        mock_collect.return_value = [_make_pr(pr_number=1)]
        mock_diff.return_value = _make_diff({"src/main.py": "fix"})

        callback = MagicMock()
        repo = Repository(full_name="owner/repo", access_token="fake")
        config = GroundTruthConfig()
        collect_pr_ground_truth(repo, config, on_change=callback)
        assert callback.call_count == 1
