"""Tests for swebenchify.validation_bench -- FAIL_TO_PASS comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebenchify.validation_bench import (
    BenchmarkReport,
    InstanceComparison,
    compare_fail_to_pass,
    format_report,
    jaccard_similarity,
    load_our_instances,
    run_comparison,
)


class TestJaccardSimilarity:
    def test_identical_lists(self) -> None:
        assert jaccard_similarity(["a", "b"], ["a", "b"]) == 1.0

    def test_disjoint_lists(self) -> None:
        assert jaccard_similarity(["a"], ["b"]) == 0.0

    def test_partial_overlap(self) -> None:
        assert jaccard_similarity(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)

    def test_empty_lists(self) -> None:
        assert jaccard_similarity([], []) == 1.0

    def test_one_empty(self) -> None:
        assert jaccard_similarity(["a"], []) == 0.0

    def test_duplicates_ignored(self) -> None:
        assert jaccard_similarity(["a", "a", "b"], ["a", "b"]) == 1.0


class TestCompareFailToPass:
    def test_exact_match(self) -> None:
        result = compare_fail_to_pass(["test_a", "test_b"], ["test_b", "test_a"])
        assert result.exact_match is True
        assert result.jaccard == 1.0
        assert result.our_subset_of_theirs is True
        assert result.their_subset_of_ours is True

    def test_our_subset(self) -> None:
        result = compare_fail_to_pass(["test_a"], ["test_a", "test_b"])
        assert result.exact_match is False
        assert result.our_subset_of_theirs is True
        assert result.their_subset_of_ours is False

    def test_their_subset(self) -> None:
        result = compare_fail_to_pass(["test_a", "test_b"], ["test_a"])
        assert result.exact_match is False
        assert result.our_subset_of_theirs is False
        assert result.their_subset_of_ours is True

    def test_no_overlap(self) -> None:
        result = compare_fail_to_pass(["test_a"], ["test_b"])
        assert result.exact_match is False
        assert result.jaccard == 0.0


class TestLoadOurInstances:
    def test_loads_jsonl(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "instance_id": "owner__repo-1",
                    "FAIL_TO_PASS": json.dumps(["test_a"]),
                }
            )
            + "\n"
        )
        result = load_our_instances(jsonl)
        assert result == {"owner__repo-1": ["test_a"]}

    def test_handles_list_fail_to_pass(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "instance_id": "owner__repo-2",
                    "FAIL_TO_PASS": ["test_b"],
                }
            )
            + "\n"
        )
        result = load_our_instances(jsonl)
        assert result == {"owner__repo-2": ["test_b"]}

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            json.dumps({"instance_id": "a", "FAIL_TO_PASS": "[]"})
            + "\n\n"
            + json.dumps({"instance_id": "b", "FAIL_TO_PASS": '["t"]'})
            + "\n"
        )
        result = load_our_instances(jsonl)
        assert len(result) == 2

    def test_missing_fail_to_pass_key(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            json.dumps({"instance_id": "owner__repo-3"}) + "\n"
        )
        result = load_our_instances(jsonl)
        assert result == {"owner__repo-3": []}

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_our_instances("/nonexistent/path.jsonl")


class TestRunComparison:
    def test_full_overlap(self) -> None:
        ours = {"a": ["t1"], "b": ["t2"]}
        theirs = {"a": ["t1"], "b": ["t2"]}
        report = run_comparison(ours, theirs)
        assert report.total_compared == 2
        assert report.exact_match_rate == 1.0
        assert report.our_only == []
        assert report.swebench_only == []

    def test_partial_overlap(self) -> None:
        ours = {"a": ["t1"], "c": ["t3"]}
        theirs = {"a": ["t1"], "b": ["t2"]}
        report = run_comparison(ours, theirs)
        assert report.total_compared == 1
        assert report.our_only == ["c"]
        assert report.swebench_only == ["b"]

    def test_no_overlap(self) -> None:
        ours = {"a": ["t1"]}
        theirs = {"b": ["t2"]}
        report = run_comparison(ours, theirs)
        assert report.total_compared == 0
        assert report.exact_match_rate == 0.0

    def test_empty_inputs(self) -> None:
        report = run_comparison({}, {})
        assert report.total_compared == 0
        assert report.mean_jaccard == 0.0


class TestBenchmarkReport:
    def test_metrics_with_mixed_results(self) -> None:
        report = BenchmarkReport(
            comparisons=[
                InstanceComparison(
                    instance_id="a",
                    ours=["t1"],
                    theirs=["t1"],
                    exact_match=True,
                    our_subset_of_theirs=True,
                    their_subset_of_ours=True,
                    jaccard=1.0,
                ),
                InstanceComparison(
                    instance_id="b",
                    ours=["t1"],
                    theirs=["t2"],
                    exact_match=False,
                    our_subset_of_theirs=False,
                    their_subset_of_ours=False,
                    jaccard=0.0,
                ),
            ]
        )
        assert report.exact_match_rate == 0.5
        assert report.mean_jaccard == 0.5


class TestFormatReport:
    def test_format_includes_key_sections(self) -> None:
        report = BenchmarkReport(
            comparisons=[
                InstanceComparison(
                    instance_id="owner__repo-1",
                    ours=["t1"],
                    theirs=["t1"],
                    exact_match=True,
                    our_subset_of_theirs=True,
                    their_subset_of_ours=True,
                    jaccard=1.0,
                ),
            ],
            our_only=["owner__repo-2"],
        )
        text = format_report(report)
        assert "Exact match rate" in text
        assert "owner__repo-1" in text
        assert "EXACT" in text
        assert "owner__repo-2" in text
        assert "Our-only instances" in text

    def test_format_shows_diff_for_mismatches(self) -> None:
        report = BenchmarkReport(
            comparisons=[
                InstanceComparison(
                    instance_id="x",
                    ours=["t1", "t3"],
                    theirs=["t1", "t2"],
                    exact_match=False,
                    our_subset_of_theirs=False,
                    their_subset_of_ours=False,
                    jaccard=1 / 3,
                ),
            ],
        )
        text = format_report(report)
        assert "+ours:" in text
        assert "+theirs:" in text
