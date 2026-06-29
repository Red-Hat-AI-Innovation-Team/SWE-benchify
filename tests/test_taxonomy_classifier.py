from __future__ import annotations

from swebenchify.ground_truth.models import GroundTruthChange
from swebenchify.taxonomy.classifier import (
    _has_agent_instructions,
    _has_architecture_docs,
    _has_ci_changes,
    _has_lint_config_changes,
    _has_policy_changes,
    _has_template_changes,
    _has_test_additions,
    aggregate_level,
    classify_change,
    evaluate_question,
)
from swebenchify.taxonomy.models import (
    TAXONOMY_QUESTIONS,
    TaxonomyEvaluation,
    TaxonomyQuestion,
)


def _make_change(**kwargs) -> GroundTruthChange:
    defaults = dict(
        repo="test/repo",
        change_id="pr:1",
        change_kind="pull_request",
        base_commit="aaa",
        head_commit="bbb",
    )
    defaults.update(kwargs)
    return GroundTruthChange(**defaults)


class TestF0Classification:
    def test_pure_code_change_no_signals(self) -> None:
        change = _make_change(code_patch="+x = 1\n+y = 2\n")
        result = classify_change(change)
        assert result.framework_level == "F0"
        assert result.level_confidence == 1.0

    def test_empty_change(self) -> None:
        change = _make_change()
        result = classify_change(change)
        assert result.framework_level == "F0"
        assert result.level_confidence == 1.0

    def test_no_patches_no_files(self) -> None:
        change = _make_change(changed_files=[])
        result = classify_change(change)
        assert result.framework_level == "F0"


class TestF1Classification:
    def test_new_constant(self) -> None:
        change = _make_change(code_patch="+MAX_RETRIES = 3\n")
        result = classify_change(change)
        assert result.framework_level == "F1"

    def test_new_api_endpoint(self) -> None:
        change = _make_change(code_patch="+@app.route('/users')\n+def list_users():\n")
        result = classify_change(change)
        assert result.framework_level == "F1"

    def test_domain_terminology_in_docs(self) -> None:
        change = _make_change(doc_patch="+" + "x" * 60 + "\n")
        result = classify_change(change)
        assert result.framework_level == "F1"

    def test_schema_migration(self) -> None:
        change = _make_change(code_patch="+    db.Column('name', String(100))\n")
        result = classify_change(change)
        assert result.framework_level in ("F1", "F2")


class TestF2Classification:
    def test_regression_test_addition(self) -> None:
        change = _make_change(test_patch="+def test_regression_fix():\n+    assert True\n")
        result = classify_change(change)
        assert result.framework_level in ("F1", "F2")

    def test_new_class_definition(self) -> None:
        change = _make_change(code_patch="+class MyNewPattern:\n+    pass\n")
        result = classify_change(change)
        assert result.framework_level == "F2"

    def test_validation_rule(self) -> None:
        change = _make_change(code_patch="+    if not isinstance(value, int):\n+        raise ValueError('must be int')\n")
        result = classify_change(change)
        assert result.framework_level == "F2"

    def test_error_message_improvement(self) -> None:
        change = _make_change(code_patch="+    logger.error('Connection failed: %s', err)\n")
        result = classify_change(change)
        assert result.framework_level == "F2"

    def test_abstract_base_class(self) -> None:
        change = _make_change(code_patch="+class BaseHandler(ABC):\n+    @abstractmethod\n+    def handle(self): ...\n")
        result = classify_change(change)
        assert result.framework_level == "F2"

    def test_property_test(self) -> None:
        change = _make_change(test_patch="+def test_property_holds():\n+    assert True\n")
        result = classify_change(change)
        assert result.framework_level in ("F1", "F2")


class TestF3Classification:
    def test_ci_workflow_addition(self) -> None:
        change = _make_change(changed_files=[".github/workflows/ci.yml"])
        result = classify_change(change)
        assert result.framework_level == "F3"

    def test_lint_rule_change(self) -> None:
        change = _make_change(changed_files=["ruff.toml"])
        result = classify_change(change)
        assert result.framework_level == "F3"

    def test_pr_template_change(self) -> None:
        change = _make_change(changed_files=[".github/PULL_REQUEST_TEMPLATE.md"])
        result = classify_change(change)
        assert result.framework_level == "F3"

    def test_build_system_change(self) -> None:
        change = _make_change(
            tooling_patch="+[tool.setuptools]\n+packages = ['mypackage']\n",
            changed_files=["pyproject.toml"],
        )
        result = classify_change(change)
        assert result.framework_level == "F3"

    def test_deployment_config(self) -> None:
        change = _make_change(changed_files=["Dockerfile", "deploy/config.yml"])
        result = classify_change(change)
        assert result.framework_level == "F3"


class TestF4Classification:
    def test_codeowners_modification(self) -> None:
        change = _make_change(changed_files=["CODEOWNERS"])
        result = classify_change(change)
        assert result.framework_level == "F4"

    def test_adr_document(self) -> None:
        change = _make_change(
            doc_patch="+# ADR-001: Use PostgreSQL\n",
            changed_files=["docs/adr/ADR-001.md"],
        )
        result = classify_change(change)
        assert result.framework_level == "F4"

    def test_license_change(self) -> None:
        change = _make_change(changed_files=["LICENSE"])
        result = classify_change(change)
        assert result.framework_level == "F4"

    def test_security_policy(self) -> None:
        change = _make_change(changed_files=["SECURITY.md"])
        result = classify_change(change)
        assert result.framework_level == "F4"


class TestAggregateLevel:
    def test_highest_level_wins(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q01", answer=True),
            TaxonomyEvaluation(question_id="q13", answer=True),
        ]
        level, conf = aggregate_level(evals)
        assert level == "F3"

    def test_no_true_answers_gives_f0(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q01", answer=False),
            TaxonomyEvaluation(question_id="q06", answer=False),
        ]
        level, conf = aggregate_level(evals)
        assert level == "F0"
        assert conf == 1.0

    def test_confidence_is_ratio(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q12", answer=True),
            TaxonomyEvaluation(question_id="q13", answer=False),
            TaxonomyEvaluation(question_id="q14", answer=False),
            TaxonomyEvaluation(question_id="q15", answer=False),
            TaxonomyEvaluation(question_id="q16", answer=False),
            TaxonomyEvaluation(question_id="q17", answer=False),
        ]
        level, conf = aggregate_level(evals)
        assert level == "F3"
        assert abs(conf - 1 / 6) < 0.01

    def test_unknown_question_id_ignored(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q99", answer=True),
        ]
        level, conf = aggregate_level(evals)
        assert level == "F0"

    def test_multiple_true_at_same_level(self) -> None:
        evals = [
            TaxonomyEvaluation(question_id="q12", answer=True),
            TaxonomyEvaluation(question_id="q13", answer=True),
            TaxonomyEvaluation(question_id="q14", answer=False),
            TaxonomyEvaluation(question_id="q15", answer=False),
            TaxonomyEvaluation(question_id="q16", answer=False),
            TaxonomyEvaluation(question_id="q17", answer=False),
        ]
        level, conf = aggregate_level(evals)
        assert level == "F3"
        assert abs(conf - 2 / 6) < 0.01


class TestMixedChanges:
    def test_test_plus_ci_gives_f3(self) -> None:
        change = _make_change(
            test_patch="+def test_new():\n+    pass\n",
            changed_files=[".github/workflows/test.yml"],
        )
        result = classify_change(change)
        assert result.framework_level == "F3"

    def test_claude_md_gives_f4(self) -> None:
        change = _make_change(
            agent_instruction_patch="+# CLAUDE.md instructions\n",
            changed_files=["CLAUDE.md"],
        )
        result = classify_change(change)
        assert result.framework_level == "F4"


class TestEvaluateQuestion:
    def test_unknown_question_defaults_false(self) -> None:
        q = TaxonomyQuestion(id="q99", text="Does X?", category="F1")
        change = _make_change()
        ev = evaluate_question(q, change)
        assert ev.answer is False
        assert ev.confidence == 0.5

    def test_returns_evaluation_with_evidence(self) -> None:
        q = TAXONOMY_QUESTIONS[0]
        change = _make_change(code_patch="+MAX_CONNECTIONS = 10\n")
        ev = evaluate_question(q, change)
        assert ev.answer is True
        assert ev.evidence != ""


class TestClassifyChange:
    def test_reasoning_includes_true_answers(self) -> None:
        change = _make_change(changed_files=["CODEOWNERS"])
        result = classify_change(change)
        assert "q21" in result.reasoning

    def test_f0_reasoning(self) -> None:
        change = _make_change()
        result = classify_change(change)
        assert "F0" in result.reasoning
        assert "no taxonomy signals" in result.reasoning

    def test_all_23_evaluations(self) -> None:
        change = _make_change()
        result = classify_change(change)
        assert len(result.evaluations) == 23


class TestHelperHasTestAdditions:
    def test_python_test(self) -> None:
        assert _has_test_additions("+def test_something():\n") is True

    def test_rust_test(self) -> None:
        assert _has_test_additions("+#[test]\n+fn test_it() {\n") is True

    def test_js_test(self) -> None:
        assert _has_test_additions("+it('should work', () => {\n") is True

    def test_go_test(self) -> None:
        assert _has_test_additions("+func TestFoo(t *testing.T) {\n") is False

    def test_none_patch(self) -> None:
        assert _has_test_additions(None) is False


class TestHelperHasCiChanges:
    def test_github_workflows(self) -> None:
        assert _has_ci_changes([".github/workflows/ci.yml"]) is True

    def test_gitlab_ci(self) -> None:
        assert _has_ci_changes([".gitlab-ci.yml"]) is True

    def test_jenkinsfile(self) -> None:
        assert _has_ci_changes(["Jenkinsfile"]) is True

    def test_regular_file(self) -> None:
        assert _has_ci_changes(["src/main.py"]) is False


class TestHelperHasLintConfig:
    def test_ruff_toml(self) -> None:
        assert _has_lint_config_changes(None, ["ruff.toml"]) is True

    def test_eslintrc(self) -> None:
        assert _has_lint_config_changes(None, [".eslintrc"]) is True

    def test_pre_commit_config(self) -> None:
        assert _has_lint_config_changes(None, [".pre-commit-config.yaml"]) is True

    def test_inline_ruff_config(self) -> None:
        assert _has_lint_config_changes("+[tool.ruff]\nselect = ['E']\n", []) is True

    def test_regular_file(self) -> None:
        assert _has_lint_config_changes(None, ["src/app.py"]) is False


class TestHelperHasAgentInstructions:
    def test_non_empty_patch(self) -> None:
        assert _has_agent_instructions("+ some instructions", []) is True

    def test_claude_md_in_files(self) -> None:
        assert _has_agent_instructions(None, ["CLAUDE.md"]) is True

    def test_agents_md_in_files(self) -> None:
        assert _has_agent_instructions(None, ["AGENTS.md"]) is True

    def test_no_instructions(self) -> None:
        assert _has_agent_instructions(None, ["src/main.py"]) is False


class TestHelperHasArchitectureDocs:
    def test_adr_in_patch(self) -> None:
        assert _has_architecture_docs("+ADR-001: Use PostgreSQL", []) is True

    def test_rfc_in_files(self) -> None:
        assert _has_architecture_docs(None, ["docs/rfc-042.md"]) is True

    def test_architecture_dir(self) -> None:
        assert _has_architecture_docs(None, ["docs/architecture/overview.md"]) is True

    def test_no_architecture(self) -> None:
        assert _has_architecture_docs(None, ["src/util.py"]) is False


class TestHelperHasPolicyChanges:
    def test_codeowners(self) -> None:
        assert _has_policy_changes(["CODEOWNERS"]) is True

    def test_security_md(self) -> None:
        assert _has_policy_changes(["SECURITY.md"]) is True

    def test_regular_file(self) -> None:
        assert _has_policy_changes(["src/main.py"]) is False


class TestHelperHasTemplateChanges:
    def test_pr_template(self) -> None:
        assert _has_template_changes([".github/PULL_REQUEST_TEMPLATE.md"]) is True

    def test_issue_template(self) -> None:
        assert _has_template_changes([".github/ISSUE_TEMPLATE/bug.md"]) is True

    def test_regular_file(self) -> None:
        assert _has_template_changes(["src/main.py"]) is False
