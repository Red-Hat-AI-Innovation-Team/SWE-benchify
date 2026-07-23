"""Difficulty optimization workflow — iterate on the synthesizer to produce harder instances.

Pipeline: study → builder → gate_eval → archive (PROCEED) | builder (RELOOP)

The generator agent mutates src/swebenchify/synthesizer.py to make synthetic
bug instances harder for Haiku to solve. Evaluation runs synthesis and enrichment
locally, then launches validation and eval jobs on OpenShift via `oc`.

Score = 0.7 × haiku_failure + 0.15 × judge_evasion + 0.15 × diversity
Target: haiku_failure > 0.5 (more than half the instances unsolved by Haiku)
"""

from typing import Any

from factory.models import ProjectState
from factory.workflow.primitives import (
    AgentNode,
    AgentRole,
    Edge,
    FnNode,
    GateNode,
    VerdictType,
    Workflow,
)

meta = {
    "name": "difficulty",
    "description": (
        "Difficulty optimization — iterate on the SWE-benchify synthesizer to "
        "produce harder instances that Haiku cannot solve. "
        "study → builder → gate_eval with RELOOP until haiku_failure > 50%."
    ),
}


def workflow() -> Workflow:
    """Build the difficulty optimization workflow."""
    nodes: dict[str, Any] = {}
    edges: list[Edge] = []

    # ── Node 1: Study ──────────────────────────────────────────────
    nodes["study"] = FnNode(
        id="study",
        command=(
            "mkdir -p {project_path}/.factory/reviews && "
            "cd {project_path} && "
            "("
            "echo '=== Data Files ===' && "
            "echo 'Haiku eval results (453 instances): data/eval-results-haiku.jsonl' && "
            "echo '  Fields: instance_id, resolved, reward, agent_patch, test_results, f2p_expected' && "
            "echo 'Full instances with pipeline metadata: data/opus-eval-ready.jsonl' && "
            "echo '  Fields: instance_id, repo, patch, problem_statement, _pipeline.bug_spec.{bug_category,bug_description,file,function_name}' && "
            "echo 'Validated instances: data/opus-final-valid.jsonl' && "
            "echo '' && "
            "echo '=== Quick Stats ===' && "
            "wc -l data/eval-results-haiku.jsonl data/opus-eval-ready.jsonl data/opus-final-valid.jsonl 2>/dev/null && "
            "echo '' && "
            "echo '=== Synthesizer Source ===' && "
            "echo 'Main file: src/swebenchify/synthesizer.py' && "
            "wc -l src/swebenchify/synthesizer.py && "
            "echo '' && "
            "echo '=== Previous Difficulty Eval ===' && "
            "cat .factory/reviews/difficulty-eval-latest.json 2>/dev/null || "
            "echo 'No previous difficulty eval results'"
            ") > .factory/reviews/study-output.md 2>&1"
        ),
        writes={".factory/reviews/study-output.md"},
    )

    # ── Node 2: Builder ────────────────────────────────────────────
    nodes["builder"] = AgentNode(
        id="builder",
        role=AgentRole.BUILDER,
        model="opus",
        timeout=3600,
        max_iterations=5,
        prompt_template=(
            "You are optimizing the SWE-benchify synthesizer to produce HARDER bug instances "
            "that Claude Haiku CANNOT solve.\n\n"
            "## Data Available\n\n"
            "You have raw data from 453 evaluated instances. START by exploring these files "
            "to understand what makes bugs easy vs hard for Haiku:\n\n"
            "- `data/eval-results-haiku.jsonl` — Haiku's eval results. Each line has: "
            "instance_id, resolved (bool), agent_patch (what Haiku submitted), test_results. "
            "Analyze: which instances did Haiku solve? Which did it fail? What do the failed "
            "agent_patches look like — did it try and get close, or was it completely lost?\n"
            "- `data/opus-eval-ready.jsonl` — Full instance data including `_pipeline.bug_spec` "
            "with bug_category, bug_description, file, function_name, original_code, buggy_code. "
            "Cross-reference with eval results to find patterns.\n"
            "- `.factory/reviews/study-output.md` — Quick stats and file locations.\n"
            "- `.factory/reviews/difficulty-eval-latest.json` — Previous round results if any.\n\n"
            "## Your Goal\n\n"
            "Modify `src/swebenchify/synthesizer.py` to make synthesized bugs HARDER to solve. "
            "The target is haiku_failure > 50% (Haiku should fail on more than half).\n\n"
            "Base your changes on what you learn from the data — don't guess. Find the "
            "specific patterns that correlate with Haiku success/failure and exploit them.\n\n"
            "## Rules\n\n"
            "- ONLY modify `src/swebenchify/synthesizer.py`\n"
            "- Bugs must still be VALID — they must cause test failures that are fixable\n"
            "- Do NOT break the synthesizer — ensure it still produces compilable mutations\n"
            "- Focus on making bugs that require REASONING, not just grep\n"
            "- Commit your changes with a descriptive message\n"
            "- Do NOT run factory commands\n"
        ),
        reads={".factory/reviews/study-output.md"},
        writes={".factory/reviews/builder-latest.md"},
    )

    # ── Node 3: Gate Eval ──────────────────────────────────────────
    nodes["gate_eval"] = GateNode(
        id="gate_eval",
        evaluator_type="fn",
        evaluator_command=(
            "cd {project_path} && "
            "CHANGES=$(git diff HEAD~1 --stat 2>/dev/null || echo 'NO_COMMITS') && "
            "if [ \"$CHANGES\" = 'NO_COMMITS' ] || [ -z \"$CHANGES\" ]; then "
            "echo 'reloop: builder did not commit any changes'; "
            "exit 0; fi && "
            "echo 'Running synthesis + enrichment + cluster validation + eval...' && "
            "RESULT=$(python3 scripts/eval_difficulty.py --n-instances 10 2>/dev/null) && "
            "if [ -z \"$RESULT\" ]; then "
            "echo 'reloop: eval script produced no output'; "
            "exit 0; fi && "
            "echo \"$RESULT\" && "
            "FAILURE=$(echo \"$RESULT\" | python3 -c \"import json,sys; "
            "d=json.loads(sys.stdin.read()); print(d.get('haiku_failure', 0))\") && "
            "N_VALID=$(echo \"$RESULT\" | python3 -c \"import json,sys; "
            "d=json.loads(sys.stdin.read()); print(d.get('n_valid', 0))\") && "
            "if [ \"$N_VALID\" -lt 3 ]; then "
            "echo 'reloop: too few valid instances produced (need >= 3)'; "
            "exit 0; fi && "
            "PASS=$(python3 -c \"print('yes' if float('$FAILURE') > 0.5 else 'no')\") && "
            "if [ \"$PASS\" = 'yes' ]; then "
            "echo 'pass: haiku_failure='$FAILURE' exceeds 0.5 target'; "
            "else "
            "echo 'reloop: haiku_failure='$FAILURE' below 0.5 target — need harder bugs'; "
            "fi"
        ),
        reads={".factory/reviews/builder-latest.md"},
    )

    # ── Node 4: Archive ────────────────────────────────────────────
    nodes["archive"] = FnNode(
        id="archive",
        command=(
            "cd {project_path} && "
            "mkdir -p .factory/archive && "
            "TIMESTAMP=$(date +%Y%m%d-%H%M%S) && "
            "cp .factory/reviews/difficulty-eval-latest.json "
            ".factory/archive/difficulty-$TIMESTAMP.json 2>/dev/null || true && "
            "cp .factory/reviews/builder-latest.md "
            ".factory/archive/builder-$TIMESTAMP.md 2>/dev/null || true && "
            "echo \"Archived difficulty experiment at $TIMESTAMP\""
        ),
        reads={".factory/reviews/builder-latest.md"},
    )

    # ── Edges ──────────────────────────────────────────────────────

    edges = [
        Edge(source="study", target="builder"),
        Edge(source="builder", target="gate_eval"),
        Edge(source="gate_eval", target="archive", condition=VerdictType.PROCEED),
        Edge(source="gate_eval", target="builder", condition=VerdictType.RELOOP),
    ]

    # ── Trigger ────────────────────────────────────────────────────

    def trigger(state: ProjectState, ctx: dict[str, Any]) -> bool:
        return ctx.get("mode") == "difficulty"

    return Workflow(
        name="difficulty",
        nodes=nodes,
        edges=edges,
        start_node="study",
        terminal=False,
        trigger=trigger,
    )
