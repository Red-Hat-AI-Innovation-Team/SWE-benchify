from __future__ import annotations

import json
from dataclasses import asdict

from swebenchify.taxonomy.models import (
    TAXONOMY_QUESTIONS,
    TaxonomyClassification,
    TaxonomyEvaluation,
    TaxonomyQuestion,
)


class TestTaxonomyQuestions:
    def test_has_exactly_23_items(self) -> None:
        assert len(TAXONOMY_QUESTIONS) == 23

    def test_all_categories_present(self) -> None:
        categories = {q.category for q in TAXONOMY_QUESTIONS}
        assert categories == {"F1", "F2", "F3", "F4"}

    def test_ids_are_sequential(self) -> None:
        ids = [q.id for q in TAXONOMY_QUESTIONS]
        expected = [f"q{i:02d}" for i in range(1, 24)]
        assert ids == expected


class TestTaxonomyEvaluation:
    def test_construction(self) -> None:
        ev = TaxonomyEvaluation(
            question_id="q01",
            answer=True,
            confidence=0.9,
            evidence="Found new config key FOO_BAR",
        )
        assert ev.question_id == "q01"
        assert ev.answer is True
        assert ev.confidence == 0.9
        assert ev.evidence == "Found new config key FOO_BAR"

    def test_defaults(self) -> None:
        ev = TaxonomyEvaluation(question_id="q05", answer=False)
        assert ev.confidence == 1.0
        assert ev.evidence == ""


class TestTaxonomyClassification:
    def test_construction(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q01", answer=True),
            TaxonomyEvaluation(question_id="q06", answer=False),
        ]
        tc = TaxonomyClassification(
            change_id="pr:42",
            framework_level="F1",
            level_confidence=0.85,
            evaluations=evals,
            reasoning="Only F1 questions answered affirmatively",
        )
        assert tc.change_id == "pr:42"
        assert tc.framework_level == "F1"
        assert tc.level_confidence == 0.85
        assert len(tc.evaluations) == 2
        assert tc.reasoning == "Only F1 questions answered affirmatively"

    def test_framework_level_values(self) -> None:
        for level in ("F0", "F1", "F2", "F3", "F4"):
            tc = TaxonomyClassification(
                change_id="pr:1", framework_level=level,
            )
            assert tc.framework_level == level

    def test_asdict_round_trip(self) -> None:
        evals = [TaxonomyEvaluation(question_id="q12", answer=True, evidence="modified Makefile")]
        tc = TaxonomyClassification(
            change_id="commit:abc",
            framework_level="F3",
            level_confidence=0.7,
            evaluations=evals,
            reasoning="Build system changed",
        )
        d = asdict(tc)
        serialised = json.dumps(d)
        data = json.loads(serialised)
        data["evaluations"] = [TaxonomyEvaluation(**e) for e in data["evaluations"]]
        restored = TaxonomyClassification(**data)
        assert restored == tc
