"""Quality evaluation stage -- LLM judge scores benchmark instances."""

import json
import logging
import tempfile
from pathlib import Path

from swebenchify.models import TaskInstance, QualityScore
from swebenchify.dispatcher import run_agent_with_retry, CostTracker

logger = logging.getLogger(__name__)

QUALITY_EVAL_PROMPT = '''You are evaluating the quality of a benchmark instance for testing coding agents.

A benchmark instance consists of:
1. A problem statement (from a GitHub issue)
2. A gold patch (the actual code fix)
3. A test patch (tests that verify the fix)

A good benchmark instance has:
- A clear problem statement that describes a specific bug or feature request
- A gold patch that directly addresses what the problem statement describes
- Tests that specifically verify the fix, not unrelated behavior
- No data leakage (the problem statement should NOT contain the solution)

## Problem Statement
{problem_statement}

## Gold Patch
```diff
{patch}
```

## Test Patch
```diff
{test_patch}
```

## Your Task
Evaluate this instance and write `quality_score.json` with this exact schema:
{{
  "coherence": <1-5 integer>,
  "specificity": <1-5 integer>,
  "leakage_risk": "<none|low|high>",
  "difficulty": "<easy|medium|hard>",
  "recommendation": "<include|review|exclude>",
  "reasoning": "<one sentence explanation>"
}}

Scoring guide:
- coherence (1-5): Does the problem statement describe what the patch actually fixes? 5 = perfect match, 1 = completely unrelated
- specificity (1-5): Is the problem statement specific enough for a developer to understand what needs fixing? 5 = very specific, 1 = too vague
- leakage_risk: Does the problem statement contain the actual code fix or exact file/line changes? "high" = contains the fix, "low" = hints at approach, "none" = no leakage
- difficulty: Based on patch size and complexity. "easy" = 1-10 lines single file, "medium" = 10-50 lines or multi-file, "hard" = 50+ lines or complex refactor
- recommendation: "include" = good benchmark instance, "review" = borderline (low coherence or leakage), "exclude" = bad instance (incoherent or high leakage)

Do NOT include any text outside the JSON in quality_score.json.
'''

EVAL_TOOLS = ["Read", "Write"]


async def evaluate_quality(
    instance: TaskInstance,
    cost_tracker: CostTracker | None = None,
    max_turns: int = 20,
    budget_usd: float = 0.50,
) -> QualityScore | None:
    """Evaluate the quality of a single benchmark instance using an LLM judge.

    Returns a QualityScore or None on failure.
    """
    # Create a temporary workspace for the agent
    with tempfile.TemporaryDirectory(prefix="swebenchify_eval_") as tmpdir:
        prompt = QUALITY_EVAL_PROMPT.format(
            problem_statement=instance.problem_statement,
            patch=instance.patch,
            test_patch=instance.test_patch,
        )

        result = await run_agent_with_retry(
            prompt=prompt,
            cwd=tmpdir,
            output_files=["quality_score.json"],
            tools=EVAL_TOOLS,
            max_turns=max_turns,
            budget_usd=budget_usd,
            max_attempts=2,
        )

        if cost_tracker:
            cost_tracker.record(
                "quality-eval", instance.repo, result,
                instance_id=instance.instance_id,
            )

        score_path = Path(tmpdir) / "quality_score.json"
        if not result.is_error and score_path.exists():
            try:
                data = json.loads(score_path.read_text())
                return QualityScore(
                    coherence=int(data.get("coherence", 0)),
                    specificity=int(data.get("specificity", 0)),
                    leakage_risk=data.get("leakage_risk", "unknown"),
                    difficulty=data.get("difficulty", "unknown"),
                    recommendation=data.get("recommendation", "review"),
                    reasoning=data.get("reasoning", ""),
                )
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.error(
                    "Failed to parse quality score for %s: %s",
                    instance.instance_id, e,
                )
                return None

        logger.error(
            "Quality evaluation failed for %s: %s",
            instance.instance_id, result.status,
        )
        return None


async def evaluate_quality_batch(
    instances: list[TaskInstance],
    cost_tracker: CostTracker | None = None,
    max_concurrent: int = 4,
    max_turns: int = 20,
    budget_usd: float = 0.50,
) -> dict[str, QualityScore]:
    """Evaluate quality for multiple instances with bounded concurrency.

    Returns a dict mapping instance_id to QualityScore.
    """
    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, QualityScore] = {}

    async def eval_one(inst: TaskInstance) -> tuple[str, QualityScore | None]:
        async with semaphore:
            score = await evaluate_quality(
                inst, cost_tracker=cost_tracker,
                max_turns=max_turns, budget_usd=budget_usd,
            )
            return inst.instance_id, score

    tasks = [eval_one(inst) for inst in instances]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in raw_results:
        if isinstance(r, Exception):
            logger.error("Quality evaluation task failed: %s", r)
            continue
        instance_id, score = r
        if score is not None:
            results[instance_id] = score

    return results
