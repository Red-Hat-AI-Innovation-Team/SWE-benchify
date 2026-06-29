from __future__ import annotations

import pytest

from swebenchify.ground_truth.patch_categorizer import (
    categorize_file,
    is_agent_instruction_file,
    is_doc_file,
    is_tooling_file,
    split_patch_5way,
    validate_patch_reconstruction,
)


# ---------------------------------------------------------------------------
# Helpers to build minimal unified diffs
# ---------------------------------------------------------------------------

def _make_diff(files: dict[str, str]) -> str:
    """Build a minimal unified diff from {filepath: content_line} pairs."""
    parts = []
    for path, line in files.items():
        parts.append(
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -1,1 +1,2 @@\n"
            f" existing\n"
            f"+{line}\n"
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# is_doc_file
# ---------------------------------------------------------------------------

class TestIsDocFile:
    def test_readme_md(self) -> None:
        assert is_doc_file("README.md") is True

    def test_docs_guide_rst(self) -> None:
        assert is_doc_file("docs/guide.rst") is True

    def test_changelog_md(self) -> None:
        assert is_doc_file("CHANGELOG.md") is True

    def test_src_main_py(self) -> None:
        assert is_doc_file("src/main.py") is False

    def test_docs_api_txt(self) -> None:
        assert is_doc_file("docs/api.txt") is True

    def test_license(self) -> None:
        assert is_doc_file("LICENSE") is True

    def test_contributing_rst(self) -> None:
        assert is_doc_file("CONTRIBUTING.rst") is True

    def test_history_adoc(self) -> None:
        assert is_doc_file("HISTORY.adoc") is True

    def test_authors(self) -> None:
        assert is_doc_file("AUTHORS") is True

    def test_root_txt(self) -> None:
        assert is_doc_file("notes.txt") is True

    def test_nested_txt_not_doc(self) -> None:
        assert is_doc_file("src/data.txt") is False

    def test_doc_dir(self) -> None:
        assert is_doc_file("doc/index.html") is True


# ---------------------------------------------------------------------------
# is_tooling_file
# ---------------------------------------------------------------------------

class TestIsToolingFile:
    def test_github_workflow(self) -> None:
        assert is_tooling_file(".github/workflows/ci.yml") is True

    def test_makefile(self) -> None:
        assert is_tooling_file("Makefile") is True

    def test_dockerfile(self) -> None:
        assert is_tooling_file("Dockerfile") is True

    def test_pyproject_toml(self) -> None:
        assert is_tooling_file("pyproject.toml") is True

    def test_src_app_py(self) -> None:
        assert is_tooling_file("src/app.py") is False

    def test_docker_compose(self) -> None:
        assert is_tooling_file("docker-compose.yml") is True

    def test_tox_ini(self) -> None:
        assert is_tooling_file("tox.ini") is True

    def test_pre_commit_config(self) -> None:
        assert is_tooling_file(".pre-commit-config.yaml") is True

    def test_github_copilot_not_tooling(self) -> None:
        assert is_tooling_file(".github/copilot-instructions.md") is False

    def test_travis_yml(self) -> None:
        assert is_tooling_file(".travis.yml") is True

    def test_cargo_toml(self) -> None:
        assert is_tooling_file("Cargo.toml") is True


# ---------------------------------------------------------------------------
# is_agent_instruction_file
# ---------------------------------------------------------------------------

class TestIsAgentInstructionFile:
    def test_claude_md(self) -> None:
        assert is_agent_instruction_file("CLAUDE.md") is True

    def test_cursorrules(self) -> None:
        assert is_agent_instruction_file(".cursorrules") is True

    def test_github_copilot_instructions(self) -> None:
        assert is_agent_instruction_file(".github/copilot-instructions.md") is True

    def test_main_py(self) -> None:
        assert is_agent_instruction_file("main.py") is False

    def test_agents_md(self) -> None:
        assert is_agent_instruction_file("AGENTS.md") is True

    def test_gemini_md(self) -> None:
        assert is_agent_instruction_file("GEMINI.md") is True

    def test_claude_dir(self) -> None:
        assert is_agent_instruction_file(".claude/settings.json") is True

    def test_cursor_dir(self) -> None:
        assert is_agent_instruction_file(".cursor/rules.json") is True

    def test_aider_conf(self) -> None:
        assert is_agent_instruction_file(".aider.conf.yml") is True

    def test_codex_md(self) -> None:
        assert is_agent_instruction_file("codex.md") is True


# ---------------------------------------------------------------------------
# categorize_file — precedence
# ---------------------------------------------------------------------------

class TestCategorizeFile:
    def test_test_file(self) -> None:
        assert categorize_file("tests/test_main.py") == "test"

    def test_agent_instruction(self) -> None:
        assert categorize_file("CLAUDE.md") == "agent_instruction"

    def test_tooling(self) -> None:
        assert categorize_file("Makefile") == "tooling"

    def test_doc(self) -> None:
        assert categorize_file("README.md") == "doc"

    def test_code(self) -> None:
        assert categorize_file("src/main.py") == "code"

    def test_precedence_test_over_agent(self) -> None:
        # A file in tests/ named CLAUDE.md -> test wins
        assert categorize_file("tests/CLAUDE.md") == "test"

    def test_precedence_agent_over_tooling(self) -> None:
        # .github/copilot-instructions.md -> agent_instruction wins over .github/ tooling
        assert categorize_file(".github/copilot-instructions.md") == "agent_instruction"

    def test_precedence_test_over_doc(self) -> None:
        assert categorize_file("tests/README.md") == "test"


# ---------------------------------------------------------------------------
# split_patch_5way
# ---------------------------------------------------------------------------

class TestSplitPatch5Way:
    def test_all_five_categories(self) -> None:
        diff = _make_diff({
            "src/main.py": "code change",
            "tests/test_main.py": "test change",
            "README.md": "doc change",
            "Makefile": "tooling change",
            "CLAUDE.md": "agent instruction",
        })
        result = split_patch_5way(diff)
        assert result["code_patch"] is not None
        assert "src/main.py" in result["code_patch"]
        assert result["test_patch"] is not None
        assert "tests/test_main.py" in result["test_patch"]
        assert result["doc_patch"] is not None
        assert "README.md" in result["doc_patch"]
        assert result["tooling_patch"] is not None
        assert "Makefile" in result["tooling_patch"]
        assert result["agent_instruction_patch"] is not None
        assert "CLAUDE.md" in result["agent_instruction_patch"]

    def test_code_only(self) -> None:
        diff = _make_diff({"src/app.py": "new code"})
        result = split_patch_5way(diff)
        assert result["code_patch"] is not None
        assert result["test_patch"] is None
        assert result["doc_patch"] is None
        assert result["tooling_patch"] is None
        assert result["agent_instruction_patch"] is None

    def test_test_only(self) -> None:
        diff = _make_diff({"tests/test_app.py": "new test"})
        result = split_patch_5way(diff)
        assert result["code_patch"] is None
        assert result["test_patch"] is not None

    def test_empty_diff(self) -> None:
        result = split_patch_5way("")
        assert all(v is None for v in result.values())

    def test_none_diff(self) -> None:
        result = split_patch_5way(None)
        assert all(v is None for v in result.values())

    def test_whitespace_only(self) -> None:
        result = split_patch_5way("   \n  ")
        assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# validate_patch_reconstruction
# ---------------------------------------------------------------------------

class TestValidatePatchReconstruction:
    def test_valid_reconstruction(self) -> None:
        diff = _make_diff({
            "src/main.py": "code",
            "tests/test_main.py": "test",
        })
        patches = split_patch_5way(diff)
        assert validate_patch_reconstruction(diff, patches) is True

    def test_missing_file_returns_false(self) -> None:
        diff = _make_diff({
            "src/main.py": "code",
            "tests/test_main.py": "test",
        })
        patches = split_patch_5way(diff)
        patches["test_patch"] = None
        assert validate_patch_reconstruction(diff, patches) is False

    def test_empty_diff(self) -> None:
        assert validate_patch_reconstruction("", {
            "code_patch": None,
            "test_patch": None,
            "doc_patch": None,
            "tooling_patch": None,
            "agent_instruction_patch": None,
        }) is True

    def test_five_way_roundtrip(self) -> None:
        diff = _make_diff({
            "src/main.py": "code",
            "tests/test_main.py": "test",
            "README.md": "doc",
            "Makefile": "tooling",
            "CLAUDE.md": "agent",
        })
        patches = split_patch_5way(diff)
        assert validate_patch_reconstruction(diff, patches) is True
