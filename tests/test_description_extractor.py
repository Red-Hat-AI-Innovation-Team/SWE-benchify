from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from swebenchify.ground_truth.description_extractor import (
    classify_leakage_risk,
    extract_all_descriptions,
    extract_from_commit_message,
    extract_from_linked_issues,
    extract_from_pr_body,
    extract_from_review_comments,
    extract_trailers,
)
from swebenchify.ground_truth.models import GroundTruthChange


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class TestExtractFromCommitMessage:
    def test_subject_only(self):
        ds = extract_from_commit_message("Fix null pointer", "", "abc123")
        assert ds.source_kind == "commit_message"
        assert ds.source_id == "abc123"
        assert ds.text == "Fix null pointer"
        assert ds.leakage_risk == "low"
        assert ds.allowed_for_task_prompt is True

    def test_subject_and_body(self):
        ds = extract_from_commit_message(
            "Fix null pointer", "This was caused by missing guard.", "def456"
        )
        assert ds.text == "Fix null pointer\nThis was caused by missing guard."
        assert ds.source_id == "def456"


class TestExtractFromPrBody:
    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_successful_fetch(self, mock_get):
        mock_get.return_value = _mock_response(
            200,
            {
                "title": "Add caching layer",
                "body": "Improves response time by 50%.",
                "created_at": "2024-03-01T00:00:00Z",
            },
        )
        ds = extract_from_pr_body("owner/repo", 99, "tok")
        assert ds is not None
        assert ds.source_kind == "pr_body"
        assert ds.source_id == "https://github.com/owner/repo/pull/99"
        assert "Add caching layer" in ds.text
        assert "Improves response time" in ds.text
        assert ds.leakage_risk == "medium"

    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_api_failure_returns_none(self, mock_get):
        mock_get.return_value = _mock_response(404)
        ds = extract_from_pr_body("owner/repo", 99)
        assert ds is None

    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_exception_returns_none(self, mock_get):
        mock_get.side_effect = RuntimeError("network down")
        ds = extract_from_pr_body("owner/repo", 99)
        assert ds is None


class TestExtractFromLinkedIssues:
    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_single_numeric_issue(self, mock_get):
        mock_get.return_value = _mock_response(
            200,
            {
                "title": "Login broken",
                "body": "Cannot authenticate.",
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
        sources = extract_from_linked_issues("owner/repo", ["42"])
        assert len(sources) == 1
        assert sources[0].source_kind == "issue"
        assert sources[0].source_id == "https://github.com/owner/repo/issues/42"
        assert "Login broken" in sources[0].text

    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_multiple_issues(self, mock_get):
        mock_get.return_value = _mock_response(
            200, {"title": "Bug", "body": "Details", "created_at": ""}
        )
        sources = extract_from_linked_issues("owner/repo", ["10", "20"])
        assert len(sources) == 2

    def test_jira_issue_non_numeric(self):
        sources = extract_from_linked_issues("owner/repo", ["OCPBUGS-123"])
        assert len(sources) == 1
        assert sources[0].source_kind == "issue"
        assert sources[0].source_id == "OCPBUGS-123"
        assert sources[0].text == "OCPBUGS-123"
        assert sources[0].leakage_risk == "low"

    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_mixed_numeric_and_jira(self, mock_get):
        mock_get.return_value = _mock_response(
            200, {"title": "Issue", "body": "", "created_at": ""}
        )
        sources = extract_from_linked_issues(
            "owner/repo", ["10", "JIRA-99", "20"]
        )
        assert len(sources) == 3
        kinds = [s.source_id for s in sources]
        assert "JIRA-99" in kinds


class TestExtractFromReviewComments:
    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_reviews_parsed(self, mock_get):
        mock_get.return_value = _mock_response(
            200,
            [
                {
                    "body": "LGTM with minor nit",
                    "html_url": "https://github.com/owner/repo/pull/5#review-1",
                    "submitted_at": "2024-02-01T00:00:00Z",
                    "id": 1,
                },
                {"body": "", "html_url": "", "submitted_at": "", "id": 2},
                {
                    "body": "Please fix the edge case",
                    "html_url": "https://github.com/owner/repo/pull/5#review-3",
                    "submitted_at": "2024-02-02T00:00:00Z",
                    "id": 3,
                },
            ],
        )
        sources = extract_from_review_comments("owner/repo", 5)
        assert len(sources) == 2
        assert sources[0].source_kind == "review_comment"
        assert sources[0].leakage_risk == "high"
        assert sources[0].allowed_for_task_prompt is False
        assert "LGTM" in sources[0].text

    @patch("swebenchify.ground_truth.description_extractor.github_get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_get.return_value = _mock_response(500)
        sources = extract_from_review_comments("owner/repo", 5)
        assert sources == []


class TestExtractTrailers:
    def test_fixes_and_bug_url_trailers(self):
        body = (
            "Some commit description.\n"
            "\n"
            "Fixes: https://issues.redhat.com/browse/FOO-1\n"
            "Bug-Url: https://bugzilla.redhat.com/123"
        )
        trailers = extract_trailers(body)
        assert len(trailers) == 2
        assert trailers[0].source_id == "trailer:Fixes"
        assert trailers[0].text == "Fixes: https://issues.redhat.com/browse/FOO-1"
        assert trailers[1].source_id == "trailer:Bug-Url"
        assert trailers[1].leakage_risk == "none"

    def test_no_trailers_returns_empty(self):
        body = "Just a commit message with no trailers."
        trailers = extract_trailers(body)
        assert trailers == []

    def test_empty_body(self):
        assert extract_trailers("") == []

    def test_signed_off_by(self):
        body = "Fix the thing\n\nSigned-off-by: Dev <dev@example.com>"
        trailers = extract_trailers(body)
        assert len(trailers) == 1
        assert trailers[0].source_id == "trailer:Signed-off-by"


class TestClassifyLeakageRisk:
    def test_text_with_file_path(self):
        assert (
            classify_leakage_risk(
                "Changed logic in src/auth.py to fix redirect",
                ["src/auth.py", "tests/test_auth.py"],
            )
            == "high"
        )

    def test_text_with_backtick_code(self):
        assert (
            classify_leakage_risk(
                "Use `cache.get()` for lookups",
                ["src/cache.py"],
            )
            == "medium"
        )

    def test_text_with_import_statement(self):
        assert (
            classify_leakage_risk(
                "We need to import os module here",
                ["src/main.py"],
            )
            == "medium"
        )

    def test_plain_description(self):
        assert (
            classify_leakage_risk(
                "Improve error handling for login failures",
                ["src/auth.py"],
            )
            == "low"
        )

    def test_empty_text(self):
        assert classify_leakage_risk("", ["src/auth.py"]) == "none"

    def test_whitespace_only(self):
        assert classify_leakage_risk("   ", ["src/auth.py"]) == "none"


class TestExtractAllDescriptions:
    @patch("swebenchify.ground_truth.description_extractor.extract_from_review_comments")
    @patch("swebenchify.ground_truth.description_extractor.extract_from_linked_issues")
    @patch("swebenchify.ground_truth.description_extractor.extract_from_pr_body")
    def test_pr_backed_change_gets_all_sources(
        self, mock_pr, mock_issues, mock_reviews
    ):
        mock_pr.return_value = MagicMock(
            source_kind="pr_body",
            source_id="https://github.com/o/r/pull/10",
            text="PR title\nPR body",
            leakage_risk="medium",
            allowed_for_task_prompt=True,
            created_at="",
        )
        mock_issues.return_value = [
            MagicMock(
                source_kind="issue",
                source_id="https://github.com/o/r/issues/5",
                text="Issue title",
                leakage_risk="low",
                allowed_for_task_prompt=True,
                created_at="",
            )
        ]
        mock_reviews.return_value = [
            MagicMock(
                source_kind="review_comment",
                source_id="review:1",
                text="LGTM",
                leakage_risk="high",
                allowed_for_task_prompt=False,
                created_at="",
            )
        ]

        change = GroundTruthChange(
            repo="o/r",
            change_id="pr:10",
            change_kind="pull_request",
            base_commit="aaa",
            head_commit="bbb",
            title="Fix bug",
            body="Description\n\nFixes: #5",
            linked_issues=["5"],
            changed_files=[],
        )
        sources = extract_all_descriptions(change, "o/r", "tok")

        kinds = [s.source_kind for s in sources]
        assert "commit_message" in kinds
        assert "pr_body" in kinds
        assert "issue" in kinds
        assert "review_comment" in kinds

    def test_direct_commit_gets_only_commit_and_trailers(self):
        change = GroundTruthChange(
            repo="o/r",
            change_id="commit:abc123",
            change_kind="direct_commit",
            base_commit="aaa",
            head_commit="bbb",
            title="Quick fix",
            body="Small patch\n\nSigned-off-by: Dev <dev@example.com>",
            changed_files=[],
        )
        sources = extract_all_descriptions(change, "o/r")
        kinds = [s.source_kind for s in sources]
        assert all(k == "commit_message" for k in kinds)
        assert len(sources) == 2  # commit message + trailer

    @patch("swebenchify.ground_truth.description_extractor.extract_from_review_comments")
    @patch("swebenchify.ground_truth.description_extractor.extract_from_linked_issues")
    @patch("swebenchify.ground_truth.description_extractor.extract_from_pr_body")
    def test_leakage_risk_reclassified(self, mock_pr, mock_issues, mock_reviews):
        mock_pr.return_value = None
        mock_issues.return_value = []
        mock_reviews.return_value = []

        change = GroundTruthChange(
            repo="o/r",
            change_id="pr:10",
            change_kind="pull_request",
            base_commit="aaa",
            head_commit="bbb",
            title="Fix src/auth.py redirect bug",
            body="",
            changed_files=["src/auth.py"],
        )
        sources = extract_all_descriptions(change, "o/r", "tok")
        assert any(s.leakage_risk == "high" for s in sources)
