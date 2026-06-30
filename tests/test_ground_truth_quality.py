from __future__ import annotations

from unittest.mock import patch

import pytest

from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange
from swebenchify.ground_truth.quality_checks import (
    check_change_id_format,
    check_commits_exist,
    check_description_provenance,
    check_diff_not_empty,
    check_patch_reconstruction,
    run_all_checks,
)

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

SAMPLE_TEST_DIFF = (
    "diff --git a/tests/test_main.py b/tests/test_main.py\n"
    "--- a/tests/test_main.py\n"
    "+++ b/tests/test_main.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def test_main():\n"
    "+    assert True\n"
    "     pass\n"
)


def _make_change(**overrides) -> GroundTruthChange:
    defaults = dict(
        repo="owner/repo",
        change_id="pr:123",
        change_kind="pull_request",
        base_commit="aaa111",
        head_commit="bbb222",
        full_diff=SAMPLE_DIFF,
        code_patch=SAMPLE_DIFF,
        description_sources=[
            DescriptionSource(
                source_kind="commit_message",
                source_id="bbb222",
                created_at="2024-01-01T00:00:00Z",
                text="Fix bug",
                allowed_for_task_prompt=True,
                leakage_risk="none",
            ),
        ],
    )
    defaults.update(overrides)
    return GroundTruthChange(**defaults)


class TestCheckCommitsExist:
    def test_pass(self, tmp_path) -> None:
        change = _make_change()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            warnings = check_commits_exist(change, str(tmp_path))
        assert warnings == []
        assert mock_run.call_count == 2

    def test_fail_missing_commit(self, tmp_path) -> None:
        change = _make_change()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            warnings = check_commits_exist(change, str(tmp_path))
        assert len(warnings) == 2
        assert "base_commit" in warnings[0]
        assert "head_commit" in warnings[1]

    def test_empty_sha(self, tmp_path) -> None:
        change = _make_change(base_commit="", head_commit="")
        warnings = check_commits_exist(change, str(tmp_path))
        assert len(warnings) == 2
        assert "empty" in warnings[0]


class TestCheckDiffNotEmpty:
    def test_pass(self) -> None:
        change = _make_change(full_diff=SAMPLE_DIFF)
        assert check_diff_not_empty(change) == []

    def test_fail_empty(self) -> None:
        change = _make_change(full_diff="")
        warnings = check_diff_not_empty(change)
        assert len(warnings) == 1
        assert "empty" in warnings[0]

    def test_fail_whitespace_only(self) -> None:
        change = _make_change(full_diff="   \n  ")
        warnings = check_diff_not_empty(change)
        assert len(warnings) == 1


class TestCheckPatchReconstruction:
    def test_pass_all_accounted(self) -> None:
        combined = SAMPLE_DIFF + SAMPLE_TEST_DIFF
        change = _make_change(
            full_diff=combined,
            code_patch=SAMPLE_DIFF,
            test_patch=SAMPLE_TEST_DIFF,
        )
        warnings = check_patch_reconstruction(change)
        assert warnings == []

    def test_empty_diff_no_warnings(self) -> None:
        change = _make_change(full_diff="")
        assert check_patch_reconstruction(change) == []

    def test_missing_file_warns(self) -> None:
        combined = SAMPLE_DIFF + SAMPLE_TEST_DIFF
        change = _make_change(
            full_diff=combined,
            code_patch=SAMPLE_DIFF,
            test_patch=None,
        )
        warnings = check_patch_reconstruction(change)
        assert len(warnings) == 1
        assert "tests/test_main.py" in warnings[0]


class TestCheckDescriptionProvenance:
    def test_pass_has_safe_source(self) -> None:
        change = _make_change()
        assert check_description_provenance(change) == []

    def test_fail_no_sources(self) -> None:
        change = _make_change(description_sources=[])
        warnings = check_description_provenance(change)
        assert len(warnings) == 1
        assert "No description sources" in warnings[0]

    def test_fail_no_safe_source(self) -> None:
        change = _make_change(
            description_sources=[
                DescriptionSource(
                    source_kind="review_comment",
                    source_id="review:1",
                    created_at="",
                    text="Code looks good",
                    allowed_for_task_prompt=False,
                    leakage_risk="high",
                ),
            ],
        )
        warnings = check_description_provenance(change)
        assert len(warnings) == 1
        assert "allowed_for_task_prompt" in warnings[0]


class TestCheckChangeIdFormat:
    @pytest.mark.parametrize(
        "change_id",
        ["pr:123", "pr:1", "commit:abc123def", "merge:abc123def", "batch:abc12345..def67890"],
    )
    def test_valid_formats(self, change_id: str) -> None:
        change = _make_change(change_id=change_id)
        assert check_change_id_format(change) == []

    @pytest.mark.parametrize(
        "change_id",
        ["invalid", "PR:123", "pr:", "commit:", "pr:abc", "foo:123"],
    )
    def test_invalid_formats(self, change_id: str) -> None:
        change = _make_change(change_id=change_id)
        warnings = check_change_id_format(change)
        assert len(warnings) == 1
        assert "does not match" in warnings[0]


class TestRunAllChecks:
    def test_all_pass(self) -> None:
        change = _make_change()
        passed, warnings = run_all_checks(change, repo_path=None)
        assert passed is True
        assert warnings == []
        assert change.extraction_warnings == []

    def test_some_fail(self) -> None:
        change = _make_change(
            full_diff="",
            change_id="invalid_id",
            description_sources=[],
        )
        passed, warnings = run_all_checks(change, repo_path=None)
        assert passed is False
        assert len(warnings) >= 2
        assert change.extraction_warnings == warnings

    def test_skip_commit_check_without_repo_path(self) -> None:
        change = _make_change()
        passed, warnings = run_all_checks(change, repo_path=None)
        assert passed is True
