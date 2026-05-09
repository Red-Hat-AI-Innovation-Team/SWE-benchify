"""Tests for swebenchify.filters -- quality filtering (Stage 5)."""

from __future__ import annotations

import json

import pytest

from swebenchify.config import FilterConfig
from swebenchify.filters import apply_filters, get_filter_reasons
from swebenchify.models import TaskInstance


def _make_instance(**overrides) -> TaskInstance:
    """Build a TaskInstance with sensible defaults that pass all filters."""
    defaults = {
        "repo": "owner/repo",
        "instance_id": "owner__repo-1",
        "base_commit": "abc123",
        "patch": "\n".join(
            [
                "diff --git a/foo.py b/foo.py",
                "--- a/foo.py",
                "+++ b/foo.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            ]
        ),
        "test_patch": "diff --git a/test_foo.py b/test_foo.py",
        "problem_statement": (
            "This is a sufficiently long problem statement that contains "
            "enough words to pass the minimum word count filter applied by "
            "the quality filtering stage of the pipeline and it also needs "
            "to have a few more words added to ensure it reaches the forty "
            "word threshold required by the default filter configuration"
        ),
        "hints_text": "",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "FAIL_TO_PASS": json.dumps(["test_foo"]),
        "PASS_TO_PASS": json.dumps(["test_bar"]),
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


class TestGetFilterReasons:
    """Tests for individual filter rules via get_filter_reasons."""

    def test_passing_instance_has_no_reasons(self) -> None:
        inst = _make_instance()
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert reasons == []

    def test_short_problem_statement(self) -> None:
        inst = _make_instance(problem_statement="Too short")
        config = FilterConfig(min_problem_statement_words=40)
        reasons = get_filter_reasons(inst, config)
        assert any("too short" in r for r in reasons)

    def test_problem_statement_at_exact_threshold(self) -> None:
        words = " ".join(["word"] * 40)
        inst = _make_instance(problem_statement=words)
        config = FilterConfig(min_problem_statement_words=40)
        reasons = get_filter_reasons(inst, config)
        assert not any("too short" in r for r in reasons)

    def test_urls_in_problem_statement(self) -> None:
        inst = _make_instance(
            problem_statement="Check this https://example.com for details " * 5
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("URLs" in r for r in reasons)

    def test_urls_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="Check this https://example.com for details " * 5
        )
        config = FilterConfig(no_urls_in_problem=False)
        reasons = get_filter_reasons(inst, config)
        assert not any("URLs" in r for r in reasons)

    def test_shas_in_problem_statement(self) -> None:
        inst = _make_instance(
            problem_statement="After commit abcdef1 the test broke and now "
            "we need to fix this regression in the code base soon "
            "or users will be affected"
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("SHAs" in r for r in reasons)

    def test_shas_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="After commit abcdef1 the test broke and now "
            "we need to fix this regression in the code base soon "
            "or users will be affected"
        )
        config = FilterConfig(no_shas_in_problem=False)
        reasons = get_filter_reasons(inst, config)
        assert not any("SHAs" in r for r in reasons)

    def test_patch_too_large(self) -> None:
        large_patch = "\n".join([f"line {i}" for i in range(600)])
        inst = _make_instance(patch=large_patch)
        config = FilterConfig(max_patch_lines=500)
        reasons = get_filter_reasons(inst, config)
        assert any("too large" in r for r in reasons)

    def test_patch_at_exact_limit(self) -> None:
        patch = "\n".join([f"line {i}" for i in range(500)])
        inst = _make_instance(patch=patch)
        config = FilterConfig(max_patch_lines=500)
        reasons = get_filter_reasons(inst, config)
        assert not any("too large" in r for r in reasons)

    def test_empty_patch(self) -> None:
        inst = _make_instance(patch="")
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("empty" in r for r in reasons)

    def test_no_fail_to_pass(self) -> None:
        inst = _make_instance(FAIL_TO_PASS=json.dumps([]))
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("no FAIL_TO_PASS" in r for r in reasons)

    def test_invalid_fail_to_pass_json(self) -> None:
        inst = _make_instance(FAIL_TO_PASS="not valid json")
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("invalid FAIL_TO_PASS JSON" in r for r in reasons)

    def test_multiple_reasons(self) -> None:
        inst = _make_instance(
            problem_statement="short",
            patch="",
            FAIL_TO_PASS=json.dumps([]),
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert len(reasons) >= 3

    def test_min_patch_lines_configurable(self) -> None:
        """Patch with 3 lines should fail if min_patch_lines=5."""
        inst = _make_instance(patch="line1\nline2\nline3")
        config = FilterConfig(min_patch_lines=5)
        reasons = get_filter_reasons(inst, config)
        assert any("empty" in r for r in reasons)

    def test_min_patch_lines_passes_at_threshold(self) -> None:
        inst = _make_instance(patch="line1\nline2\nline3")
        config = FilterConfig(min_patch_lines=3)
        reasons = get_filter_reasons(inst, config)
        assert not any("empty" in r for r in reasons)

    def test_min_fail_to_pass_configurable(self) -> None:
        """With min_fail_to_pass=2 and only 1 test, should be filtered."""
        inst = _make_instance(FAIL_TO_PASS=json.dumps(["test_one"]))
        config = FilterConfig(min_fail_to_pass=2)
        reasons = get_filter_reasons(inst, config)
        assert any("no FAIL_TO_PASS" in r for r in reasons)

    def test_min_fail_to_pass_passes_at_threshold(self) -> None:
        inst = _make_instance(FAIL_TO_PASS=json.dumps(["t1", "t2"]))
        config = FilterConfig(min_fail_to_pass=2)
        reasons = get_filter_reasons(inst, config)
        assert not any("no FAIL_TO_PASS" in r for r in reasons)

    def test_image_only_problem_statement_filtered(self) -> None:
        """Problem statement with only image markdown should be filtered."""
        inst = _make_instance(
            problem_statement="![screenshot](https://example.com/img.png)",
        )
        config = FilterConfig(
            min_problem_statement_words=1,
            no_image_only_problem=True,
        )
        reasons = get_filter_reasons(inst, config)
        assert any("image markdown" in r for r in reasons)

    def test_image_only_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="![screenshot](https://example.com/img.png)",
        )
        config = FilterConfig(
            min_problem_statement_words=1,
            no_urls_in_problem=False,
            no_image_only_problem=False,
        )
        reasons = get_filter_reasons(inst, config)
        assert not any("image markdown" in r for r in reasons)

    def test_image_plus_text_not_filtered(self) -> None:
        """Problem statement with image AND text should not be filtered."""
        inst = _make_instance(
            problem_statement=(
                "![img](https://example.com/img.png) This is a real "
                "problem description with enough words to pass the "
                "minimum word count filter applied by quality filtering"
            ),
        )
        config = FilterConfig(
            no_urls_in_problem=False,
            no_image_only_problem=True,
        )
        reasons = get_filter_reasons(inst, config)
        assert not any("image markdown" in r for r in reasons)


class TestApplyFilters:
    """Tests for apply_filters with a mix of instances."""

    def test_all_pass(self) -> None:
        instances = [_make_instance(instance_id=f"owner__repo-{i}") for i in range(5)]
        config = FilterConfig()
        filtered = apply_filters(instances, config)
        assert len(filtered) == 5

    def test_some_filtered(self) -> None:
        good = _make_instance(instance_id="owner__repo-1")
        bad = _make_instance(
            instance_id="owner__repo-2",
            problem_statement="too short",
        )
        config = FilterConfig()
        filtered = apply_filters([good, bad], config)
        assert len(filtered) == 1
        assert filtered[0].instance_id == "owner__repo-1"

    def test_all_filtered(self) -> None:
        instances = [
            _make_instance(instance_id=f"owner__repo-{i}", patch="")
            for i in range(3)
        ]
        config = FilterConfig()
        filtered = apply_filters(instances, config)
        assert len(filtered) == 0

    def test_empty_input(self) -> None:
        config = FilterConfig()
        filtered = apply_filters([], config)
        assert filtered == []

    def test_custom_config_overrides(self) -> None:
        inst = _make_instance(
            problem_statement="short stmt",
        )
        # With low threshold, it should pass
        config = FilterConfig(min_problem_statement_words=2)
        filtered = apply_filters([inst], config)
        assert len(filtered) == 1

        # With default threshold, it should fail
        config = FilterConfig(min_problem_statement_words=40)
        filtered = apply_filters([inst], config)
        assert len(filtered) == 0
