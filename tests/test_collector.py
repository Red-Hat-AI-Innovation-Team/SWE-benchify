"""Tests for swebenchify.collector -- PR collection and issue extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebenchify.collector import (
    compute_link_confidence,
    extract_jira_issues,
    extract_resolved_issues,
    load_prs,
    save_prs,
)
from swebenchify.models import CandidatePR


class TestExtractResolvedIssues:
    """Test the regex-based issue extraction from PR text."""

    def test_fixes_single_issue(self) -> None:
        assert extract_resolved_issues("Fixes #123") == [123]

    def test_fix_and_closes_multiple(self) -> None:
        result = extract_resolved_issues("Fix #123, closes #456")
        assert result == [123, 456]

    def test_resolve_single(self) -> None:
        assert extract_resolved_issues("Resolve #789") == [789]

    def test_mention_without_keyword(self) -> None:
        """A bare '#100' without a close/fix/resolve keyword should not match."""
        assert extract_resolved_issues("Mentions #100 but doesn't fix it") == []

    def test_fixed_in_commit(self) -> None:
        assert extract_resolved_issues("fixed #42 in commit abc") == [42]

    def test_case_insensitive(self) -> None:
        assert extract_resolved_issues("CLOSES #10") == [10]

    def test_resolved_keyword(self) -> None:
        assert extract_resolved_issues("Resolved #55") == [55]

    def test_empty_string(self) -> None:
        assert extract_resolved_issues("") == []

    def test_none_input(self) -> None:
        assert extract_resolved_issues(None) == []

    def test_no_issues(self) -> None:
        assert extract_resolved_issues("Updated the README") == []

    def test_deduplication(self) -> None:
        """Same issue referenced multiple times should appear once."""
        result = extract_resolved_issues("Fixes #123 and also closes #123")
        assert result == [123]

    def test_multiple_keywords_multiple_issues(self) -> None:
        text = "Fixes #1, resolves #2, closes #3"
        assert extract_resolved_issues(text) == [1, 2, 3]

    def test_closed_keyword(self) -> None:
        assert extract_resolved_issues("closed #99") == [99]

    def test_resolves_keyword(self) -> None:
        assert extract_resolved_issues("resolves #7") == [7]

    def test_non_keyword_word_before_hash(self) -> None:
        """Words that are not keywords should not produce matches."""
        assert extract_resolved_issues("see #50 for details") == []
        assert extract_resolved_issues("addresses #50") == []

    def test_fixes_without_hash(self) -> None:
        """'fixes 123' (without #) should match per SPEC."""
        assert extract_resolved_issues("fixes 123") == [123]

    def test_closes_without_hash(self) -> None:
        """'closes 456' (without #) should match per SPEC."""
        assert extract_resolved_issues("closes 456") == [456]

    def test_mixed_hash_and_no_hash(self) -> None:
        """Mix of 'fixes #1' and 'closes 2' should match both."""
        result = extract_resolved_issues("fixes #1 and closes 2")
        assert result == [1, 2]

    def test_commit_message_multiline(self) -> None:
        """Issue references in multi-line commit messages should be found."""
        msg = "Refactor auth module\n\nFixes #301\nAlso resolves #302"
        assert extract_resolved_issues(msg) == [301, 302]

    def test_commit_message_single_line(self) -> None:
        """A single-line commit message with a keyword should match."""
        assert extract_resolved_issues("closes #88 -- quick patch") == [88]


class TestExtractJiraIssues:
    """Test Jira issue key extraction from PR text."""

    def test_ocpbugs_single(self) -> None:
        assert extract_jira_issues("OCPBUGS-1234 fix") == ["OCPBUGS-1234"]

    def test_ocpbugs_multiple(self) -> None:
        result = extract_jira_issues("OCPBUGS-100 and OCPBUGS-200")
        assert result == ["OCPBUGS-100", "OCPBUGS-200"]

    def test_configured_project(self) -> None:
        result = extract_jira_issues("STOR-567 fix", rh_jira_projects=["STOR"])
        assert result == ["STOR-567"]

    def test_unknown_project_ignored(self) -> None:
        result = extract_jira_issues("ZZZZ-1234", rh_jira_projects=["STOR"])
        assert result == []

    def test_ocpbugs_always_recognized(self) -> None:
        result = extract_jira_issues("OCPBUGS-99", rh_jira_projects=["STOR"])
        assert result == ["OCPBUGS-99"]

    def test_mixed_ocpbugs_and_project(self) -> None:
        result = extract_jira_issues("OCPBUGS-1 MGMT-2")
        assert result == ["MGMT-2", "OCPBUGS-1"]

    def test_empty_string(self) -> None:
        assert extract_jira_issues("") == []

    def test_none_input(self) -> None:
        assert extract_jira_issues(None) == []

    def test_deduplication(self) -> None:
        result = extract_jira_issues("OCPBUGS-1234 again OCPBUGS-1234")
        assert result == ["OCPBUGS-1234"]

    def test_default_projects_recognized(self) -> None:
        assert extract_jira_issues("MGMT-100") == ["MGMT-100"]
        assert extract_jira_issues("STOR-200") == ["STOR-200"]

    def test_no_github_issues_extracted(self) -> None:
        result = extract_jira_issues("fixes #123 OCPBUGS-1")
        assert result == ["OCPBUGS-1"]
        assert 123 not in result


class TestComputeLinkConfidence:
    """Test RH issue-linking pattern confidence scoring."""

    def test_github_closes_gives_1_0(self) -> None:
        assert compute_link_confidence("Closes #123", None) == 1.0

    def test_github_fixes_gives_1_0(self) -> None:
        assert compute_link_confidence("fix #42", "some body") == 1.0

    def test_github_resolves_in_body_gives_1_0(self) -> None:
        assert compute_link_confidence("Update stuff", "Resolves #99") == 1.0

    def test_resolves_trailer_gives_1_0(self) -> None:
        msg = "fix thing\n\nResolves: https://issues.redhat.com/browse/OCPBUGS-1"
        assert compute_link_confidence(None, None, [msg]) == 1.0

    def test_fixes_trailer_gives_1_0(self) -> None:
        msg = "patch\n\nFixes: rhbz#2123456"
        assert compute_link_confidence(None, None, [msg]) == 1.0

    def test_bug_url_trailer_gives_0_95(self) -> None:
        msg = "fix\n\nBug-Url: https://bugzilla.redhat.com/show_bug.cgi?id=2123456"
        assert compute_link_confidence(None, None, [msg]) == 0.95

    def test_rhbz_gives_0_9(self) -> None:
        assert compute_link_confidence("rhbz#2000001 crash fix", None) == 0.9

    def test_ocpbugs_gives_0_9(self) -> None:
        assert compute_link_confidence("OCPBUGS-1234 fix", None) == 0.9

    def test_configured_jira_project_gives_0_7(self) -> None:
        # STOR is in the default project list
        assert compute_link_confidence("STOR-567 improve storage", None) == 0.7

    def test_unknown_jira_project_gives_0_0(self) -> None:
        # ZZZZ is not in the project list
        result = compute_link_confidence("ZZZZ-1234 something", None, rh_jira_projects=["STOR"])
        assert result == 0.0

    def test_change_id_only_gives_0_5(self) -> None:
        msg = "update thing\n\nChange-Id: Iabc1234567890abcdef"
        assert compute_link_confidence(None, None, [msg]) == 0.5

    def test_no_patterns_gives_0_0(self) -> None:
        assert compute_link_confidence("Update the README", "No refs here") == 0.0

    def test_none_inputs_gives_0_0(self) -> None:
        assert compute_link_confidence(None, None) == 0.0

    def test_takes_max_across_matches(self) -> None:
        # rhbz (0.9) and Change-Id (0.5) together → 0.9
        msg = "fix\nrhbz#1234\nChange-Id: Iabc123"
        assert compute_link_confidence(None, None, [msg]) == 0.9

    def test_github_keyword_beats_all(self) -> None:
        # GitHub keyword is 1.0 even with Change-Id present
        text = "Closes #10\nChange-Id: Iabc123"
        assert compute_link_confidence(text, None) == 1.0

    def test_custom_jira_project_list(self) -> None:
        result = compute_link_confidence("CUSTOM-99 fix", None, rh_jira_projects=["CUSTOM"])
        assert result == 0.7

    def test_link_confidence_default_on_candidate_pr(self) -> None:
        pr = CandidatePR(
            repo="o/r", pr_number=1, title="t", body=None,
            base_commit="a", merge_commit="b", diff_url="u",
            resolved_issues=[], created_at="2024-01-01T00:00:00Z",
            merged_at="2024-01-01T01:00:00Z",
        )
        assert pr.link_confidence == 0.0

    def test_link_confidence_set_on_candidate_pr(self) -> None:
        pr = CandidatePR(
            repo="o/r", pr_number=1, title="t", body=None,
            base_commit="a", merge_commit="b", diff_url="u",
            resolved_issues=[1], created_at="2024-01-01T00:00:00Z",
            merged_at="2024-01-01T01:00:00Z",
            link_confidence=0.9,
        )
        assert pr.link_confidence == 0.9


class TestPRJsonlRoundTrip:
    """Test JSONL serialization and deserialization of CandidatePR."""

    @pytest.fixture
    def sample_prs(self) -> list[CandidatePR]:
        return [
            CandidatePR(
                repo="pallets/flask",
                pr_number=4045,
                title="Fix blueprint dot notation",
                body="Fixes #4044",
                base_commit="abc123",
                merge_commit="def456",
                diff_url="https://github.com/pallets/flask/pull/4045.diff",
                resolved_issues=[4044],
                created_at="2021-05-13T21:32:41Z",
                merged_at="2021-05-14T10:00:00Z",
            ),
            CandidatePR(
                repo="pallets/flask",
                pr_number=5000,
                title="Resolve session issue",
                body="Resolves #4999, fixes #4998",
                base_commit="aaa111",
                merge_commit="bbb222",
                diff_url="https://github.com/pallets/flask/pull/5000.diff",
                resolved_issues=[4998, 4999],
                created_at="2022-01-01T00:00:00Z",
                merged_at="2022-01-02T00:00:00Z",
            ),
        ]

    def test_round_trip(self, sample_prs: list[CandidatePR], tmp_path: Path) -> None:
        path = str(tmp_path / "prs.jsonl")
        save_prs(sample_prs, path)
        loaded = load_prs(path)

        assert len(loaded) == len(sample_prs)
        for original, restored in zip(sample_prs, loaded):
            assert restored.repo == original.repo
            assert restored.pr_number == original.pr_number
            assert restored.title == original.title
            assert restored.body == original.body
            assert restored.base_commit == original.base_commit
            assert restored.merge_commit == original.merge_commit
            assert restored.diff_url == original.diff_url
            assert restored.resolved_issues == original.resolved_issues
            assert restored.created_at == original.created_at
            assert restored.merged_at == original.merged_at

    def test_jsonl_format(self, sample_prs: list[CandidatePR], tmp_path: Path) -> None:
        """Each line should be valid JSON."""
        path = str(tmp_path / "prs.jsonl")
        save_prs(sample_prs, path)

        with open(path) as f:
            lines = [raw.strip() for raw in f if raw.strip()]

        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "pr_number" in data
            assert "resolved_issues" in data

    def test_empty_list(self, tmp_path: Path) -> None:
        """Saving an empty list should produce an empty file."""
        path = str(tmp_path / "empty.jsonl")
        save_prs([], path)
        loaded = load_prs(path)
        assert loaded == []

    def test_round_trip_merge_base_commit(self, tmp_path: Path) -> None:
        """base_commit derived from merge commit parent survives round-trip."""
        pr = CandidatePR(
            repo="owner/repo",
            pr_number=42,
            title="Fix bug",
            body="Fixes #10",
            base_commit="parent_sha_of_merge",
            merge_commit="merge_sha_abc",
            diff_url="https://github.com/owner/repo/pull/42.diff",
            resolved_issues=[10],
            created_at="2025-03-01T00:00:00Z",
            merged_at="2025-03-02T00:00:00Z",
        )
        path = str(tmp_path / "merge_base.jsonl")
        save_prs([pr], path)
        loaded = load_prs(path)
        assert len(loaded) == 1
        assert loaded[0].base_commit == "parent_sha_of_merge"
        assert loaded[0].merge_commit == "merge_sha_abc"

    def test_round_trip_jira_issues(self, tmp_path: Path) -> None:
        """resolved_jira_issues survives JSONL round-trip."""
        pr = CandidatePR(
            repo="openshift/origin",
            pr_number=99,
            title="OCPBUGS-1234 fix crash",
            body="Resolves OCPBUGS-1234",
            base_commit="aaa",
            merge_commit="bbb",
            diff_url="https://github.com/openshift/origin/pull/99.diff",
            resolved_issues=[],
            created_at="2025-06-01T00:00:00Z",
            merged_at="2025-06-02T00:00:00Z",
            resolved_jira_issues=["OCPBUGS-1234"],
            link_confidence=0.9,
        )
        path = str(tmp_path / "jira.jsonl")
        save_prs([pr], path)
        loaded = load_prs(path)
        assert len(loaded) == 1
        assert loaded[0].resolved_jira_issues == ["OCPBUGS-1234"]
        assert loaded[0].resolved_issues == []

    def test_backward_compat_missing_jira_field(self, tmp_path: Path) -> None:
        """Old JSONL without resolved_jira_issues loads with empty default."""
        line = json.dumps({
            "repo": "o/r", "pr_number": 1, "title": "t", "body": None,
            "base_commit": "a", "merge_commit": "b", "diff_url": "u",
            "resolved_issues": [1], "created_at": "2024-01-01T00:00:00Z",
            "merged_at": "2024-01-02T00:00:00Z",
        })
        path = str(tmp_path / "old.jsonl")
        with open(path, "w") as f:
            f.write(line + "\n")
        loaded = load_prs(path)
        assert loaded[0].resolved_jira_issues == []
