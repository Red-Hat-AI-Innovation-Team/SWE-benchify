"""Tests for swebenchify.evaluator -- quality evaluation stage."""

from __future__ import annotations

import inspect

from swebenchify.evaluator import (
    EVAL_TOOLS,
    QUALITY_EVAL_PROMPT,
    evaluate_quality,
    evaluate_quality_batch,
)
from swebenchify.models import QualityScore


class TestQualityEvalPrompt:
    """Verify the prompt template renders without errors."""

    def test_prompt_formatting_no_keyerror(self) -> None:
        """Formatting with the three expected keys should not raise."""
        result = QUALITY_EVAL_PROMPT.format(
            problem_statement="Some bug description",
            patch="--- a/foo.py\n+++ b/foo.py",
            test_patch="--- a/test_foo.py\n+++ b/test_foo.py",
        )
        assert "Some bug description" in result
        assert "--- a/foo.py" in result
        assert "--- a/test_foo.py" in result

    def test_prompt_literal_braces_render(self) -> None:
        """Escaped braces {{ and }} in the JSON schema example should render
        as literal { and } after formatting."""
        result = QUALITY_EVAL_PROMPT.format(
            problem_statement="x",
            patch="y",
            test_patch="z",
        )
        # The JSON schema example in the prompt should have literal braces
        assert '"coherence"' in result
        assert '"specificity"' in result
        assert '"leakage_risk"' in result
        assert '"difficulty"' in result
        assert '"recommendation"' in result
        assert '"reasoning"' in result

    def test_prompt_contains_scoring_guide(self) -> None:
        """Prompt should contain the scoring rubric."""
        assert "coherence (1-5)" in QUALITY_EVAL_PROMPT
        assert "specificity (1-5)" in QUALITY_EVAL_PROMPT
        assert "leakage_risk" in QUALITY_EVAL_PROMPT


class TestEvalTools:
    """Verify the EVAL_TOOLS constant."""

    def test_eval_tools_is_list(self) -> None:
        assert isinstance(EVAL_TOOLS, list)

    def test_eval_tools_contains_read_and_write(self) -> None:
        assert "Read" in EVAL_TOOLS
        assert "Write" in EVAL_TOOLS

    def test_eval_tools_length(self) -> None:
        assert len(EVAL_TOOLS) == 2


class TestEvaluateQualitySignature:
    """Verify evaluate_quality is importable and has the right signature."""

    def test_is_async(self) -> None:
        assert inspect.iscoroutinefunction(evaluate_quality)

    def test_accepts_instance_param(self) -> None:
        sig = inspect.signature(evaluate_quality)
        assert "instance" in sig.parameters

    def test_accepts_cost_tracker_param(self) -> None:
        sig = inspect.signature(evaluate_quality)
        assert "cost_tracker" in sig.parameters

    def test_accepts_max_turns_param(self) -> None:
        sig = inspect.signature(evaluate_quality)
        assert "max_turns" in sig.parameters

    def test_accepts_budget_usd_param(self) -> None:
        sig = inspect.signature(evaluate_quality)
        assert "budget_usd" in sig.parameters


class TestEvaluateQualityBatchSignature:
    """Verify evaluate_quality_batch is importable and has the right signature."""

    def test_is_async(self) -> None:
        assert inspect.iscoroutinefunction(evaluate_quality_batch)

    def test_accepts_instances_param(self) -> None:
        sig = inspect.signature(evaluate_quality_batch)
        assert "instances" in sig.parameters

    def test_accepts_max_concurrent_param(self) -> None:
        sig = inspect.signature(evaluate_quality_batch)
        assert "max_concurrent" in sig.parameters


class TestQualityScoreConstruction:
    """Verify QualityScore can be constructed with all fields."""

    def test_all_fields(self) -> None:
        score = QualityScore(
            coherence=5,
            specificity=4,
            leakage_risk="none",
            difficulty="medium",
            recommendation="include",
            reasoning="Good benchmark instance",
        )
        assert score.coherence == 5
        assert score.specificity == 4
        assert score.leakage_risk == "none"
        assert score.difficulty == "medium"
        assert score.recommendation == "include"
        assert score.reasoning == "Good benchmark instance"

    def test_exclude_recommendation(self) -> None:
        score = QualityScore(
            coherence=1,
            specificity=1,
            leakage_risk="high",
            difficulty="easy",
            recommendation="exclude",
            reasoning="Problem statement contains the fix",
        )
        assert score.recommendation == "exclude"
        assert score.leakage_risk == "high"

    def test_review_recommendation(self) -> None:
        score = QualityScore(
            coherence=3,
            specificity=3,
            leakage_risk="low",
            difficulty="hard",
            recommendation="review",
            reasoning="Borderline quality",
        )
        assert score.recommendation == "review"
