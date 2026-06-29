from __future__ import annotations

import logging
import re

from swebenchify.ground_truth.models import GroundTruthChange
from swebenchify.taxonomy.models import (
    TAXONOMY_QUESTIONS,
    TaxonomyClassification,
    TaxonomyEvaluation,
    TaxonomyQuestion,
)

logger = logging.getLogger(__name__)

_QUESTIONS_BY_ID: dict[str, TaxonomyQuestion] = {q.id: q for q in TAXONOMY_QUESTIONS}

_TEST_ADD_RE = re.compile(
    r"^\+\s*(?:def test_|fn test_|#\[test\]|it\(|it\s*\(|describe\(|test\()",
    re.MULTILINE,
)

_CI_PATHS = (
    ".github/workflows/",
    ".gitlab-ci",
    "Jenkinsfile",
    ".circleci/",
    ".travis.yml",
    "azure-pipelines",
    "buildkite/",
)

_LINT_FILES = (
    "ruff.toml",
    "pyproject.toml",
    ".eslintrc",
    "eslint.config",
    ".pylintrc",
    "pylintrc",
    "clippy.toml",
    ".pre-commit-config",
    ".flake8",
    "tslint.json",
    "biome.json",
)

_AGENT_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    ".cursorrules",
    ".github/copilot",
    ".cursor/",
)

_POLICY_FILES = (
    "SECURITY.md",
    "GOVERNANCE.md",
    "CODEOWNERS",
    "CODE_OF_CONDUCT.md",
    "MAINTAINERS",
    "MAINTAINERS.md",
)

_TEMPLATE_PATHS = (
    ".github/PULL_REQUEST_TEMPLATE",
    ".github/ISSUE_TEMPLATE",
    ".github/pull_request_template",
    ".github/issue_template",
)

_ERROR_MSG_RE = re.compile(
    r"^\+.*(?:raise\s+\w+Error|raise\s+\w+Exception|log\.\w+\(|logger\.\w+\(|"
    r"fmt\.Errorf|errors\.New|console\.(?:error|warn)|warning\.warn)",
    re.MULTILINE,
)

_NEW_TYPE_RE = re.compile(
    r"^\+\s*(?:class\s+\w+|interface\s+\w+|type\s+\w+\s+(?:struct|interface)|"
    r"@dataclass|@dataclasses\.dataclass|export\s+(?:interface|type|class)\s+\w+)",
    re.MULTILINE,
)

_ADR_RFC_RE = re.compile(r"(?:ADR|RFC|adr|rfc)[-_/\s]?\d+", re.IGNORECASE)

_SCHEMA_RE = re.compile(
    r"^\+.*(?:CREATE\s+TABLE|ALTER\s+TABLE|add_column|remove_column|"
    r"db\.Column|models\.Field|Schema\(|migration)",
    re.MULTILINE | re.IGNORECASE,
)


def _has_test_additions(patch: str | None) -> bool:
    if not patch:
        return False
    return bool(_TEST_ADD_RE.search(patch))


def _has_ci_changes(files: list[str]) -> bool:
    return any(
        any(f.startswith(ci) or f == ci.rstrip("/") for ci in _CI_PATHS)
        for f in files
    )


def _has_lint_config_changes(patch: str | None, files: list[str]) -> bool:
    for f in files:
        basename = f.rsplit("/", 1)[-1] if "/" in f else f
        for lint_file in _LINT_FILES:
            if basename == lint_file or basename.startswith(lint_file) or f.endswith(lint_file):
                return True
    if patch and re.search(r"^\+.*\[tool\.ruff|^\+.*\[tool\.pylint", patch, re.MULTILINE):
        return True
    return False


def _has_agent_instructions(patch: str | None, files: list[str]) -> bool:
    if patch:
        return True
    return any(
        any(f.startswith(af) or f.endswith(af) or af in f for af in _AGENT_FILES)
        for f in files
    )


def _has_architecture_docs(patch: str | None, files: list[str]) -> bool:
    if patch and _ADR_RFC_RE.search(patch):
        return True
    return any(
        _ADR_RFC_RE.search(f) or "architecture" in f.lower() or "decision-record" in f.lower()
        for f in files
    )


def _has_policy_changes(files: list[str]) -> bool:
    return any(
        any(f.endswith(pf) or f.rsplit("/", 1)[-1] == pf for pf in _POLICY_FILES)
        for f in files
    )


def _has_template_changes(files: list[str]) -> bool:
    return any(
        any(tp in f for tp in _TEMPLATE_PATHS)
        for f in files
    )


def _has_error_msg_additions(patch: str | None) -> bool:
    if not patch:
        return False
    return bool(_ERROR_MSG_RE.search(patch))


def _has_new_types(patch: str | None) -> bool:
    if not patch:
        return False
    return bool(_NEW_TYPE_RE.search(patch))


def _has_schema_changes(patch: str | None) -> bool:
    if not patch:
        return False
    return bool(_SCHEMA_RE.search(patch))


def _has_deployment_changes(files: list[str]) -> bool:
    deploy_patterns = (
        "Dockerfile", "docker-compose", "Makefile",
        "terraform/", ".terraform", "helm/", "k8s/", "kubernetes/",
        "deploy/", "infra/",
    )
    return any(
        any(dp in f for dp in deploy_patterns)
        for f in files
    )


def evaluate_question(question: TaxonomyQuestion, change: GroundTruthChange) -> TaxonomyEvaluation:
    qid = question.id
    files = change.changed_files

    # F1 questions
    if qid == "q01":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\+\s*(?:[A-Z_]{3,}\s*=|const\s+[A-Z_]|FEATURE_|CONFIG_)",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.6, evidence="constant/config pattern in code_patch" if answer else "")

    if qid == "q02":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\+.*(?:@app\.route|@router\.|add_command|register_command|"
                r"HandleFunc|\.get\(|\.post\(|endpoint|cli\.command)",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="API/CLI entry point in code_patch" if answer else "")

    if qid == "q03":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\+\s*(?:class\s+\w+Error|class\s+\w+Status|"
                r"[A-Z_]+\s*=\s*['\"]|Enum\)|IntEnum\))",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="error code/enum in code_patch" if answer else "")

    if qid == "q04":
        answer = bool(change.doc_patch and len(change.doc_patch) > 50)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="domain terminology in doc_patch" if answer else "")

    if qid == "q05":
        answer = _has_schema_changes(change.code_patch)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="schema/migration pattern in code_patch" if answer else "")

    # F2 questions
    if qid == "q06":
        answer = _has_new_types(change.code_patch)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="new type/class definition in code_patch" if answer else "")

    if qid == "q07":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\+.*(?:assert\s|validate|constraint|invariant|"
                r"if\s+not\s+isinstance|raise\s+ValueError|raise\s+TypeError)",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="validation/invariant in code_patch" if answer else "")

    if qid == "q08":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\+\s*(?:class\s+\w+\(ABC\)|class\s+\w+\(Protocol\)|"
                r"@abstractmethod|interface\s+\w+|trait\s+\w+|"
                r"abstract\s+class\s+\w+)",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="new abstraction in code_patch" if answer else "")

    if qid == "q09":
        answer = _has_test_additions(change.test_patch)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.8 if answer else 0.6, evidence="test additions in test_patch" if answer else "")

    if qid == "q10":
        answer = _has_error_msg_additions(change.code_patch)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="error handling/logging in code_patch" if answer else "")

    if qid == "q11":
        answer = bool(
            change.doc_patch
            and re.search(r"(?:template|style.guide|contribut|CONTRIBUTING)", change.doc_patch, re.IGNORECASE)
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="doc template/style guide in doc_patch" if answer else "")

    # F3 questions
    if qid == "q12":
        answer = bool(change.tooling_patch and re.search(
            r"(?:setup\.py|setup\.cfg|pyproject\.toml|Cargo\.toml|go\.mod|package\.json|"
            r"Makefile|CMakeLists|requirements\.txt|Gemfile)",
            change.tooling_patch,
            re.IGNORECASE,
        ))
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.8 if answer else 0.5, evidence="build/package config in tooling_patch" if answer else "")

    if qid == "q13":
        answer = _has_ci_changes(files)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.9 if answer else 0.5, evidence="CI/CD file change" if answer else "")

    if qid == "q14":
        answer = bool(change.tooling_patch and re.search(
            r"(?:pytest\.ini|conftest|jest\.config|karma\.conf|"
            r"\.coveragerc|tox\.ini|noxfile|test.*config)",
            change.tooling_patch,
            re.IGNORECASE,
        ))
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="test infrastructure in tooling_patch" if answer else "")

    if qid == "q15":
        has_templates = _has_template_changes(files)
        has_codegen = bool(change.tooling_patch and re.search(
            r"(?:template|scaffold|codegen|generator|cookiecutter)",
            change.tooling_patch,
            re.IGNORECASE,
        ))
        answer = has_templates or has_codegen
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="template/scaffolding change" if answer else "")

    if qid == "q16":
        answer = _has_lint_config_changes(change.tooling_patch, files)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.8 if answer else 0.5, evidence="lint/formatting config change" if answer else "")

    if qid == "q17":
        answer = _has_deployment_changes(files)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.7 if answer else 0.5, evidence="deployment/infra file change" if answer else "")

    # F4 questions
    if qid == "q18":
        if not change.changed_files:
            answer = False
        else:
            dirs = {f.rsplit("/", 1)[0] for f in files if "/" in f}
            answer = len(dirs) > 10
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.5, evidence="many directories touched" if answer else "")

    if qid == "q19":
        answer = bool(
            change.code_patch
            and re.search(
                r"^\-\s*(?:def\s+\w+|class\s+\w+|func\s+\w+|export\s+)",
                change.code_patch,
                re.MULTILINE,
            )
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.5, evidence="public API removal in code_patch" if answer else "")

    if qid == "q20":
        answer = any(
            f in ("CHANGELOG.md", "CHANGES.md", "VERSION", "version.py", ".bumpversion.cfg")
            or f.rsplit("/", 1)[-1] in ("CHANGELOG.md", "CHANGES.md", "VERSION")
            for f in files
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6 if answer else 0.5, evidence="versioning/release file changed" if answer else "")

    if qid == "q21":
        answer = _has_policy_changes(files)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.9 if answer else 0.5, evidence="governance doc changed" if answer else "")

    if qid == "q22":
        answer = _has_agent_instructions(change.agent_instruction_patch, files) or _has_architecture_docs(change.doc_patch, files)
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.6, evidence="architecture/agent instruction change" if answer else "")

    if qid == "q23":
        answer = any(
            f.rsplit("/", 1)[-1].upper() in ("LICENSE", "LICENSE.md", "LICENSE.txt", "SECURITY.md", "COMPLIANCE.md")
            for f in files
        )
        return TaxonomyEvaluation(question_id=qid, answer=answer, confidence=0.8 if answer else 0.5, evidence="license/security/compliance file changed" if answer else "")

    return TaxonomyEvaluation(question_id=qid, answer=False, confidence=0.5, evidence="no heuristic for this question")


def aggregate_level(evaluations: list[TaxonomyEvaluation]) -> tuple[str, float]:
    level_true: dict[str, int] = {"F1": 0, "F2": 0, "F3": 0, "F4": 0}
    level_total: dict[str, int] = {"F1": 0, "F2": 0, "F3": 0, "F4": 0}

    for ev in evaluations:
        q = _QUESTIONS_BY_ID.get(ev.question_id)
        if q is None:
            continue
        cat = q.category
        level_total[cat] += 1
        if ev.answer:
            level_true[cat] += 1

    for level in ("F4", "F3", "F2", "F1"):
        if level_true[level] > 0:
            confidence = level_true[level] / level_total[level]
            return level, confidence

    return "F0", 1.0


def classify_change(change: GroundTruthChange) -> TaxonomyClassification:
    evaluations: list[TaxonomyEvaluation] = []
    for question in TAXONOMY_QUESTIONS:
        ev = evaluate_question(question, change)
        evaluations.append(ev)

    level, confidence = aggregate_level(evaluations)

    true_evals = [ev for ev in evaluations if ev.answer]
    if true_evals:
        parts: list[str] = []
        for ev in true_evals:
            q = _QUESTIONS_BY_ID.get(ev.question_id)
            label = f"{q.category}:{ev.question_id}" if q else ev.question_id
            parts.append(f"{label} ({ev.evidence})" if ev.evidence else label)
        reasoning = f"Level {level}: " + "; ".join(parts)
    else:
        reasoning = "F0: no taxonomy signals detected"

    return TaxonomyClassification(
        change_id=change.change_id,
        framework_level=level,
        level_confidence=confidence,
        evaluations=evaluations,
        reasoning=reasoning,
    )
