from __future__ import annotations

import json
import logging
import re
from typing import Callable

from swebenchify.ground_truth.models import GroundTruthChange
from swebenchify.taxonomy.models import (
    TAXONOMY_QUESTIONS,
    TaxonomyClassification,
    TaxonomyEvaluation,
)

logger = logging.getLogger(__name__)


def build_classification_prompt(
    change: GroundTruthChange,
    questions: list | None = None,
) -> str:
    qs = questions if questions is not None else TAXONOMY_QUESTIONS

    lines = [
        "You are a software change taxonomy classifier.",
        "",
        "Classify the following change by answering each binary question.",
        "",
        "## Change Metadata",
        f"- change_id: {change.change_id}",
        f"- change_kind: {change.change_kind}",
        f"- title: {change.title}",
        f"- body: {change.body[:500]}" if change.body else "- body: (empty)",
        f"- changed_files: {', '.join(change.changed_files[:30])}",
        "",
        "## Questions",
        "",
    ]

    for q in qs:
        lines.append(f"- {q.id} [{q.category}]: {q.text}")

    lines += [
        "",
        "## Instructions",
        "",
        "Answer each question with yes or no. For each answer, provide a confidence "
        "score between 0.0 and 1.0 and a brief evidence string.",
        "",
        "Determine the overall framework level (F0-F4) based on the highest category "
        "with at least one yes answer. F0 means no questions answered yes.",
        "",
        "Output your response as JSON with the following structure:",
        "```json",
        "{",
        '  "framework_level": "F0",',
        '  "evaluations": [',
        '    {"question_id": "q01", "answer": true, "confidence": 0.9, "evidence": "reason"}',
        "  ],",
        '  "reasoning": "explanation of classification"',
        "}",
        "```",
    ]

    return "\n".join(lines)


def parse_classification_response(
    response: str,
    change_id: str,
) -> TaxonomyClassification | None:
    json_str = _extract_json(response)
    if json_str is None:
        logger.warning("No JSON found in LLM response for %s", change_id)
        return None

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LLM response for %s", change_id)
        return None

    try:
        evaluations = [
            TaxonomyEvaluation(
                question_id=ev["question_id"],
                answer=bool(ev.get("answer", False)),
                confidence=float(ev.get("confidence", 0.5)),
                evidence=str(ev.get("evidence", "")),
            )
            for ev in data.get("evaluations", [])
        ]

        return TaxonomyClassification(
            change_id=change_id,
            framework_level=str(data.get("framework_level", "F0")),
            level_confidence=_compute_confidence(evaluations, str(data.get("framework_level", "F0"))),
            evaluations=evaluations,
            reasoning=str(data.get("reasoning", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed to build classification for %s: %s", change_id, exc)
        return None


def classify_change_llm(
    change: GroundTruthChange,
    prompt_fn: Callable[[str], str] | None = None,
) -> TaxonomyClassification | None:
    prompt = build_classification_prompt(change)
    if prompt_fn is None:
        return None
    response = prompt_fn(prompt)
    return parse_classification_response(response, change.change_id)


def _extract_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    for start, end in [("{", "}"), ("[", "]")]:
        idx = text.find(start)
        if idx >= 0:
            ridx = text.rfind(end)
            if ridx > idx:
                return text[idx : ridx + 1]
    return None


def _compute_confidence(evaluations: list[TaxonomyEvaluation], level: str) -> float:
    if level == "F0":
        return 1.0
    relevant = [
        ev for ev in evaluations
        if ev.answer and ev.question_id.startswith("q")
    ]
    if not relevant:
        return 0.0
    return sum(ev.confidence for ev in relevant) / len(relevant)
