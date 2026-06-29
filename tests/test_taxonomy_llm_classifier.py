from __future__ import annotations

import json

from swebenchify.ground_truth.models import GroundTruthChange
from swebenchify.taxonomy.llm_classifier import (
    build_classification_prompt,
    classify_change_llm,
    parse_classification_response,
)
from swebenchify.taxonomy.models import TAXONOMY_QUESTIONS


def _make_change(**overrides) -> GroundTruthChange:
    defaults = dict(
        repo="owner/repo",
        change_id="pr:42",
        change_kind="pull_request",
        base_commit="aaa",
        head_commit="bbb",
        title="Fix widget rendering",
        body="Fixes off-by-one in the widget layout engine",
        changed_files=["src/widget.py", "tests/test_widget.py"],
    )
    defaults.update(overrides)
    return GroundTruthChange(**defaults)


class TestBuildClassificationPrompt:
    def test_contains_all_question_texts(self):
        change = _make_change()
        prompt = build_classification_prompt(change)
        for q in TAXONOMY_QUESTIONS:
            assert q.text in prompt, f"Missing question text: {q.id}"

    def test_contains_change_id_and_title(self):
        change = _make_change(change_id="pr:99", title="Add caching layer")
        prompt = build_classification_prompt(change)
        assert "pr:99" in prompt
        assert "Add caching layer" in prompt

    def test_custom_questions(self):
        change = _make_change()
        custom = TAXONOMY_QUESTIONS[:3]
        prompt = build_classification_prompt(change, questions=custom)
        assert custom[0].text in prompt
        assert TAXONOMY_QUESTIONS[-1].text not in prompt


class TestParseClassificationResponse:
    def test_valid_json(self):
        response_data = {
            "framework_level": "F2",
            "evaluations": [
                {"question_id": "q06", "answer": True, "confidence": 0.9, "evidence": "new pattern"},
                {"question_id": "q07", "answer": False, "confidence": 0.4, "evidence": ""},
            ],
            "reasoning": "Establishes a new coding pattern",
        }
        result = parse_classification_response(json.dumps(response_data), "pr:10")
        assert result is not None
        assert result.framework_level == "F2"
        assert result.change_id == "pr:10"
        assert len(result.evaluations) == 2
        assert result.evaluations[0].answer is True
        assert result.evaluations[1].answer is False

    def test_json_in_code_fences(self):
        response_data = {
            "framework_level": "F1",
            "evaluations": [
                {"question_id": "q01", "answer": True, "confidence": 0.8, "evidence": "constant added"},
            ],
            "reasoning": "New constant introduced",
        }
        text = f"Here is my analysis:\n```json\n{json.dumps(response_data, indent=2)}\n```\nDone."
        result = parse_classification_response(text, "pr:20")
        assert result is not None
        assert result.framework_level == "F1"
        assert len(result.evaluations) == 1

    def test_malformed_response_returns_none(self):
        result = parse_classification_response("This is not JSON at all.", "pr:30")
        assert result is None

    def test_invalid_json_returns_none(self):
        result = parse_classification_response("{broken json...", "pr:31")
        assert result is None


class TestClassifyChangeLlm:
    def test_with_mock_prompt_fn(self):
        change = _make_change()
        response_data = {
            "framework_level": "F3",
            "evaluations": [
                {"question_id": "q12", "answer": True, "confidence": 0.85, "evidence": "build change"},
            ],
            "reasoning": "Build system modified",
        }

        def mock_fn(prompt: str) -> str:
            assert "pr:42" in prompt
            return json.dumps(response_data)

        result = classify_change_llm(change, prompt_fn=mock_fn)
        assert result is not None
        assert result.framework_level == "F3"
        assert result.change_id == "pr:42"

    def test_without_prompt_fn_returns_none(self):
        change = _make_change()
        result = classify_change_llm(change, prompt_fn=None)
        assert result is None
