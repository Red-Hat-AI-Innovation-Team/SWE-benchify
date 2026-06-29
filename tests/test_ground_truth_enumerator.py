from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from swebenchify.ground_truth.enumerator import (
    build_change_from_commit,
    classify_change_kind,
    collect_all_ground_truth,
    enumerate_landed_changes,
    link_to_pr,
    parse_trailers,
)


class TestLinkToPrMergeCommit:
    def test_merge_commit_pattern(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Merge pull request #42 from user/branch",
            body="",
        )
        assert pr == 42
        assert confidence == 1.0


class TestLinkToPrSquash:
    def test_squash_commit_pattern(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Fix login redirect bug (#123)",
            body="",
        )
        assert pr == 123
        assert confidence == 0.95


class TestLinkToPrTrailer:
    def test_trailer_fixes_pattern(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Fix something",
            body="Some description\n\nFixes: #456",
        )
        assert pr == 456
        assert confidence == 0.8

    def test_trailer_closes_pattern(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Update thing",
            body="Details here\n\nCloses: #789",
        )
        assert pr == 789
        assert confidence == 0.8

    def test_trailer_resolves_pattern(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Resolve issue",
            body="Resolves: #100",
        )
        assert pr == 100
        assert confidence == 0.8


class TestLinkToPrNoMatch:
    def test_no_match_returns_none(self) -> None:
        pr, confidence = link_to_pr(
            sha="abc123",
            subject="Just a regular commit message",
            body="No PR references here",
        )
        assert pr is None
        assert confidence == 0.0


class TestClassifyChangeKind:
    def test_pull_request(self) -> None:
        assert classify_change_kind(["p1", "p2"], 42) == "pull_request"

    def test_merge_commit(self) -> None:
        assert classify_change_kind(["p1", "p2"], None) == "merge_commit"

    def test_squash_commit(self) -> None:
        assert classify_change_kind(["p1"], 42) == "squash_commit"

    def test_direct_commit(self) -> None:
        assert classify_change_kind(["p1"], None) == "direct_commit"

    def test_unknown(self) -> None:
        assert classify_change_kind([], None) == "unknown"


class TestParseTrailers:
    def test_multiple_trailers(self) -> None:
        body = (
            "Some commit body\n"
            "\n"
            "Signed-off-by: Alice <alice@example.com>\n"
            "Reviewed-by: Bob <bob@example.com>\n"
            "Fixes: #42"
        )
        trailers = parse_trailers(body)
        assert trailers["Signed-off-by"] == "Alice <alice@example.com>"
        assert trailers["Reviewed-by"] == "Bob <bob@example.com>"
        assert trailers["Fixes"] == "#42"

    def test_no_trailers(self) -> None:
        body = "Just a plain commit message\nwith no trailers"
        trailers = parse_trailers(body)
        assert trailers == {}

    def test_empty_body(self) -> None:
        assert parse_trailers("") == {}


class TestBuildChangeFromCommit:
    @patch("swebenchify.ground_truth.enumerator.subprocess.run")
    @patch("swebenchify.ground_truth.enumerator.split_patch_5way")
    def test_correct_fields(self, mock_split: MagicMock, mock_run: MagicMock) -> None:
        diff_output = "diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1 +1,2 @@\n old\n+new\n"
        mock_run.side_effect = [
            MagicMock(stdout=diff_output),
            MagicMock(stdout="file.py\n"),
        ]
        mock_split.return_value = {
            "code_patch": diff_output,
            "test_patch": None,
            "doc_patch": None,
            "tooling_patch": None,
            "agent_instruction_patch": None,
        }

        commit_data = {
            "sha": "abcdef123456789",
            "parents": ["parent1"],
            "subject": "Fix something (#10)",
            "author_date": "2024-06-15T10:00:00+00:00",
            "body": "",
        }

        change = build_change_from_commit(
            commit_data,
            repo_path="/tmp/repo",
            repo_name="owner/repo",
            pr_number=10,
            change_kind="squash_commit",
            link_confidence=0.95,
        )

        assert change.repo == "owner/repo"
        assert change.change_id == "pr:10"
        assert change.change_kind == "squash_commit"
        assert change.base_commit == "parent1"
        assert change.head_commit == "abcdef123456789"
        assert change.merge_commit == ""
        assert change.landed_at == "2024-06-15T10:00:00+00:00"
        assert change.title == "Fix something (#10)"
        assert change.code_patch == diff_output
        assert change.test_patch is None
        assert change.changed_files == ["file.py"]
        assert change.link_confidence == 0.95
        assert len(change.description_sources) == 1
        assert change.description_sources[0].source_kind == "commit_message"

    @patch("swebenchify.ground_truth.enumerator.subprocess.run")
    @patch("swebenchify.ground_truth.enumerator.split_patch_5way")
    def test_merge_commit_fields(self, mock_split: MagicMock, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(stdout=""),
            MagicMock(stdout=""),
        ]
        mock_split.return_value = {
            "code_patch": None,
            "test_patch": None,
            "doc_patch": None,
            "tooling_patch": None,
            "agent_instruction_patch": None,
        }

        commit_data = {
            "sha": "merge_sha_12345",
            "parents": ["p1", "p2"],
            "subject": "Merge pull request #99 from user/branch",
            "author_date": "2024-07-01T00:00:00Z",
            "body": "",
        }

        change = build_change_from_commit(
            commit_data,
            repo_path="/tmp/repo",
            repo_name="owner/repo",
            pr_number=99,
            change_kind="pull_request",
            link_confidence=1.0,
        )

        assert change.change_id == "pr:99"
        assert change.merge_commit == "merge_sha_12345"


class TestCollectAllGroundTruth:
    @patch("swebenchify.ground_truth.enumerator.build_change_from_commit")
    @patch("swebenchify.ground_truth.enumerator.enumerate_landed_changes")
    def test_skip_existing_change_ids(
        self, mock_enumerate: MagicMock, mock_build: MagicMock
    ) -> None:
        mock_enumerate.return_value = [
            {
                "sha": "sha1_full_hash",
                "parents": ["p1"],
                "subject": "Fix bug (#10)",
                "author_date": "2024-01-01T00:00:00Z",
                "body": "",
            },
            {
                "sha": "sha2_full_hash",
                "parents": ["p1"],
                "subject": "Add feature",
                "author_date": "2024-01-02T00:00:00Z",
                "body": "",
            },
        ]

        mock_change = MagicMock()
        mock_change.landed_at = "2024-01-02T00:00:00Z"
        mock_build.return_value = mock_change

        changes = collect_all_ground_truth(
            repo_path="/tmp/repo",
            repo_name="owner/repo",
            existing_change_ids={"pr:10"},
        )

        assert mock_build.call_count == 1
        call_args = mock_build.call_args
        assert call_args[0][0]["sha"] == "sha2_full_hash"


class TestEnumerateLandedChanges:
    @patch("swebenchify.ground_truth.enumerator.subprocess.run")
    def test_date_filtering_passes_args(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")

        enumerate_landed_changes(
            repo_path="/tmp/repo",
            target_branch="main",
            after="2024-01-01",
            before="2024-12-31",
        )

        cmd = mock_run.call_args[0][0]
        assert "--after=2024-01-01" in cmd
        assert "--before=2024-12-31" in cmd

    @patch("swebenchify.ground_truth.enumerator.subprocess.run")
    def test_parse_records(self, mock_run: MagicMock) -> None:
        sep = chr(30)
        stdout = (
            f"abc123|parent1|Fix bug|2024-06-01T10:00:00+00:00|Some body{sep}\n"
            f"def456|p1 p2|Merge PR #5|2024-06-02T10:00:00+00:00|Merge body{sep}\n"
        )
        mock_run.return_value = MagicMock(stdout=stdout)

        commits = enumerate_landed_changes("/tmp/repo")

        assert len(commits) == 2
        assert commits[0]["sha"] == "abc123"
        assert commits[0]["parents"] == ["parent1"]
        assert commits[0]["subject"] == "Fix bug"
        assert commits[0]["author_date"] == "2024-06-01T10:00:00+00:00"
        assert commits[0]["body"] == "Some body"

        assert commits[1]["sha"] == "def456"
        assert commits[1]["parents"] == ["p1", "p2"]
        assert commits[1]["subject"] == "Merge PR #5"
