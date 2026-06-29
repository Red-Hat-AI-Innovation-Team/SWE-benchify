"""Integration tests for Stages 1 and 2.

These tests require a valid GITHUB_TOKEN environment variable and make
real API calls to GitHub.  They are skipped when the token is not set.
"""

from __future__ import annotations

import os

import pytest

from swebenchify.collector import collect_prs
from swebenchify.models import Repository

_HAS_TOKEN = bool(os.environ.get("GITHUB_TOKEN"))


@pytest.mark.skipif(not _HAS_TOKEN, reason="GITHUB_TOKEN not set")
class TestLiveCollection:
    """Live integration tests against the GitHub API."""

    def test_collect_flask_prs(self) -> None:
        """Collect a small number of PRs from pallets/flask."""
        token = os.environ["GITHUB_TOKEN"]
        repo = Repository(full_name="pallets/flask", access_token=token)
        prs = collect_prs(repo, max_prs=5)

        assert len(prs) <= 5
        for pr in prs:
            assert pr.repo == "pallets/flask"
            assert pr.pr_number > 0
            assert pr.title
            assert pr.merged_at
            assert len(pr.resolved_issues) >= 1
            assert pr.base_commit
            assert pr.diff_url
