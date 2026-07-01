"""Tests for swebenchify.synthesizer — no LLM calls required."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebenchify.synthesizer import (
    BugPlan,
    BugSpec,
    SynthesisResult,
    _build_social_context,
    _collect_repo_context,
    _count_changed_lines,
    _discover_repo_modules,
    _edge_case_score,
    _enforce_banned_openers,
    _find_existing_test_file,
    _find_file_commits,
    _find_related_files,
    _find_test_file_importing,
    _format_new_test_patch,
    _humanize_traceback,
    _is_stdlib_or_installed,
    _mine_issue_style_examples,
    _mine_social_artifacts,
    _normalize_test_whitespace,
    _parse_bug_response,
    _parse_incidental_changes,
    _parse_secondary_changes,
    _run_tests_on_buggy_code,
    _source_to_module_name,
    _strip_strategy_labels,
    _strip_issue_shas,
    _truncate_issue,
    _validate_mutation_parses,
    _validate_rst_references,
    _validate_test_code,
    _validate_test_imports,
    build_candidate,
    find_mutation_targets,
    generate_patch,
)


# ---------------------------------------------------------------------------
# find_mutation_targets — Python
# ---------------------------------------------------------------------------

def test_find_mutation_targets_python(tmp_path: Path) -> None:
    src = tmp_path / "module.py"
    src.write_text(textwrap.dedent("""\
        def hello(name):
            greeting = f"Hello, {name}!"
            return greeting

        def add(a, b):
            result = a + b
            return result
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    assert len(targets) == 2
    assert targets[0]["function_name"] == "hello"
    assert targets[0]["language"] == "python"
    assert targets[0]["file"] == "module.py"
    assert "def hello" in targets[0]["source"]
    assert targets[1]["function_name"] == "add"


def test_find_mutation_targets_python_nested(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    src = pkg / "core.py"
    src.write_text(textwrap.dedent("""\
        class Calculator:
            def multiply(self, a, b):
                result = a * b
                return result
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "multiply"
    assert targets[0]["file"] == "pkg/core.py"


# ---------------------------------------------------------------------------
# find_mutation_targets — Go
# ---------------------------------------------------------------------------

def test_find_mutation_targets_go(tmp_path: Path) -> None:
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Add(a, b int) int {
            result := a + b
            return result
        }

        func (s *Server) Handle(req Request) Response {
            data := s.process(req)
            return Response{Data: data}
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    assert len(targets) == 2
    assert targets[0]["function_name"] == "Add"
    assert targets[0]["language"] == "go"
    assert targets[1]["function_name"] == "Handle"


# ---------------------------------------------------------------------------
# find_mutation_targets — Rust
# ---------------------------------------------------------------------------

def test_find_mutation_targets_rust(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(textwrap.dedent("""\
        pub fn calculate(x: i32, y: i32) -> i32 {
            let result = x + y;
            result
        }

        fn helper(s: &str) -> String {
            let trimmed = s.trim();
            trimmed.to_string()
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "rust")
    assert len(targets) == 2
    assert targets[0]["function_name"] == "calculate"
    assert targets[0]["language"] == "rust"
    assert targets[1]["function_name"] == "helper"


def test_find_mutation_targets_rust_async(tmp_path: Path) -> None:
    src = tmp_path / "server.rs"
    src.write_text(textwrap.dedent("""\
        pub async fn fetch(url: &str) -> Result<String, Error> {
            let resp = client.get(url).await?;
            Ok(resp.text().await?)
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "rust")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "fetch"


# ---------------------------------------------------------------------------
# find_mutation_targets — Java
# ---------------------------------------------------------------------------

def test_find_mutation_targets_java(tmp_path: Path) -> None:
    src = tmp_path / "Calculator.java"
    src.write_text(textwrap.dedent("""\
        public class Calculator {
            public int add(int a, int b) {
                int result = a + b;
                return result;
            }

            private String format(int value) {
                String formatted = String.valueOf(value);
                return formatted;
            }
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "java")
    assert len(targets) == 2
    assert targets[0]["function_name"] == "add"
    assert targets[0]["language"] == "java"
    assert targets[1]["function_name"] == "format"


# ---------------------------------------------------------------------------
# find_mutation_targets — exclusions
# ---------------------------------------------------------------------------

def test_find_mutation_targets_excludes_python_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.write_text(textwrap.dedent("""\
        def test_something():
            assert True
            pass
    """))
    conftest = tmp_path / "conftest.py"
    conftest.write_text(textwrap.dedent("""\
        def my_fixture():
            return 42
            pass
    """))
    setup = tmp_path / "setup.py"
    setup.write_text("from setuptools import setup\nsetup()\npass\n")
    init = tmp_path / "__init__.py"
    init.write_text("")

    src = tmp_path / "real.py"
    src.write_text(textwrap.dedent("""\
        def real_function():
            value = 42
            return value
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    files = {t["file"] for t in targets}
    assert "real.py" in files
    assert "tests/test_foo.py" not in files
    assert "conftest.py" not in files
    assert "setup.py" not in files
    assert "__init__.py" not in files


def test_find_mutation_targets_excludes_go_tests(tmp_path: Path) -> None:
    test_file = tmp_path / "foo_test.go"
    test_file.write_text(textwrap.dedent("""\
        package main

        func TestFoo(t *testing.T) {
            result := Add(1, 2)
            assert(result == 3)
        }
    """))
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    vendor_file = vendor / "lib.go"
    vendor_file.write_text(textwrap.dedent("""\
        package vendor

        func VendorFunc() int {
            value := 42
            return value
        }
    """))
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Main() int {
            value := 1
            return value
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    files = {t["file"] for t in targets}
    assert "main.go" in files
    assert "foo_test.go" not in files
    assert "vendor/lib.go" not in files


def test_find_mutation_targets_excludes_rust_tests(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "integration.rs"
    test_file.write_text(textwrap.dedent("""\
        fn test_integration() {
            let x = 1;
            assert_eq!(x, 1);
        }
    """))
    src = tmp_path / "lib.rs"
    src.write_text(textwrap.dedent("""\
        pub fn compute(x: i32) -> i32 {
            let result = x * 2;
            result
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "rust")
    files = {t["file"] for t in targets}
    assert "lib.rs" in files
    assert "tests/integration.rs" not in files


def test_find_mutation_targets_excludes_java_tests(tmp_path: Path) -> None:
    test_file = tmp_path / "CalculatorTest.java"
    test_file.write_text(textwrap.dedent("""\
        public class CalculatorTest {
            public void testAdd() {
                int result = calc.add(1, 2);
                assertEquals(3, result);
            }
        }
    """))
    test_dir = tmp_path / "src" / "test" / "java"
    test_dir.mkdir(parents=True)
    test_dir_file = test_dir / "Foo.java"
    test_dir_file.write_text(textwrap.dedent("""\
        public class Foo {
            public void testBar() {
                int x = 1;
                assertEquals(1, x);
            }
        }
    """))
    src = tmp_path / "Main.java"
    src.write_text(textwrap.dedent("""\
        public class Main {
            public int run(int x) {
                int result = x + 1;
                return result;
            }
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "java")
    files = {t["file"] for t in targets}
    assert "Main.java" in files
    assert "CalculatorTest.java" not in files
    assert "src/test/java/Foo.java" not in files


def test_find_mutation_targets_unsupported_language(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        find_mutation_targets(str(tmp_path), "cobol")


def test_find_mutation_targets_max_files(tmp_path: Path) -> None:
    for i in range(10):
        f = tmp_path / f"mod{i}.py"
        f.write_text(textwrap.dedent(f"""\
            def func_{i}():
                value = {i}
                return value
        """))

    targets = find_mutation_targets(str(tmp_path), "python", max_files=3)
    files = {t["file"] for t in targets}
    assert len(files) <= 3


# ---------------------------------------------------------------------------
# generate_patch
# ---------------------------------------------------------------------------

def test_generate_patch_basic() -> None:
    original = "def add(a, b):\n    return a + b\n"
    mutated = "def add(a, b):\n    return a - b\n"

    patch = generate_patch(original, mutated, "module.py")
    assert patch  # non-empty
    assert "--- a/module.py" in patch
    assert "+++ b/module.py" in patch
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch


def test_generate_patch_multiline() -> None:
    original = textwrap.dedent("""\
        def process(items):
            result = []
            for item in items:
                if item > 0:
                    result.append(item)
            return result
    """)
    mutated = textwrap.dedent("""\
        def process(items):
            result = []
            for item in items:
                if item >= 0:
                    result.append(item)
            return result
    """)

    patch = generate_patch(original, mutated, "processor.py")
    assert patch
    assert "--- a/processor.py" in patch
    assert "+++ b/processor.py" in patch
    assert "item > 0" in patch or "item >= 0" in patch


def test_generate_patch_no_diff() -> None:
    source = "def foo():\n    return 1\n"
    patch = generate_patch(source, source, "foo.py")
    assert patch == ""


# ---------------------------------------------------------------------------
# build_candidate
# ---------------------------------------------------------------------------

def test_build_candidate_fields() -> None:
    bug_spec = BugSpec(
        file="src/core.py",
        function_name="calculate",
        original_code="def calculate(x):\n    return x + 1",
        buggy_code="def calculate(x):\n    return x - 1",
        bug_description="Changed + to - causing incorrect calculation",
        bug_category="incorrect-operator",
    )
    synthesis_result = SynthesisResult(
        bug_spec=bug_spec,
        patch="--- a/src/core.py\n+++ b/src/core.py\n...",
        problem_statement="Calculate returns wrong results",
        instance_id="",
        base_commit="abc123",
    )

    candidate = build_candidate(
        "owner/repo", "abc123", synthesis_result, test_patch="diff --git ...",
    )

    assert candidate.repo == "owner/repo"
    assert candidate.base_commit == "abc123"
    assert candidate.patch == "--- a/src/core.py\n+++ b/src/core.py\n..."
    assert candidate.test_patch == "diff --git ..."
    assert candidate.problem_statement == "Calculate returns wrong results"
    assert candidate.hints_text == ""
    assert 90000 <= candidate.pr_number <= 99999
    assert candidate.created_at  # non-empty ISO timestamp


def test_build_candidate_instance_id_format() -> None:
    bug_spec = BugSpec(
        file="main.go",
        function_name="Process",
        original_code="func Process() {}",
        buggy_code="func Process() { return }",
        bug_description="Early return",
        bug_category="logic-error",
    )
    synthesis_result = SynthesisResult(
        bug_spec=bug_spec,
        patch="diff",
        problem_statement="issue",
        instance_id="",
        base_commit="def456",
    )

    candidate = build_candidate("myorg/myrepo", "def456", synthesis_result)

    assert candidate.instance_id.startswith("myorg__myrepo-")
    pr_num = candidate.instance_id.split("-")[-1]
    assert pr_num.isdigit()
    assert 90000 <= int(pr_num) < 100000


def test_build_candidate_provenance() -> None:
    bug_spec = BugSpec(
        file="lib.rs",
        function_name="parse",
        original_code="fn parse() {}",
        buggy_code="fn parse() { todo!() }",
        bug_description="Unimplemented",
        bug_category="missing-implementation",
    )
    synthesis_result = SynthesisResult(
        bug_spec=bug_spec,
        patch="diff",
        problem_statement="issue",
        instance_id="",
        base_commit="ghi789",
    )

    candidate = build_candidate("org/repo", "ghi789", synthesis_result)
    assert candidate.provenance == "synthetic"


def test_build_candidate_deterministic_id() -> None:
    """Same inputs produce the same instance_id."""
    bug_spec = BugSpec(
        file="a.py",
        function_name="f",
        original_code="code",
        buggy_code="buggy",
        bug_description="desc",
        bug_category="cat",
    )
    sr = SynthesisResult(
        bug_spec=bug_spec,
        patch="p",
        problem_statement="ps",
        instance_id="",
        base_commit="c",
    )

    c1 = build_candidate("o/r", "c", sr)
    c2 = build_candidate("o/r", "c", sr)
    assert c1.instance_id == c2.instance_id


# ---------------------------------------------------------------------------
# _parse_bug_response
# ---------------------------------------------------------------------------

def test_parse_bug_response_valid() -> None:
    target = {
        "file": "mod.py",
        "function_name": "add",
        "source": "def add(a, b):\n    return a + b",
        "language": "python",
    }
    response = textwrap.dedent("""\
        <bug_category>incorrect-operator</bug_category>

        <bug_description>Changed addition to subtraction</bug_description>

        <buggy_code>
        def add(a, b):
            return a - b
        </buggy_code>
    """)

    result = _parse_bug_response(response, target)
    assert result is not None
    assert result.bug_category == "incorrect-operator"
    assert result.bug_description == "Changed addition to subtraction"
    assert "return a - b" in result.buggy_code
    assert result.file == "mod.py"
    assert result.function_name == "add"


def test_parse_bug_response_with_code_fence() -> None:
    target = {
        "file": "mod.py",
        "function_name": "add",
        "source": "def add(a, b):\n    return a + b",
        "language": "python",
    }
    response = textwrap.dedent("""\
        <bug_category>off-by-one</bug_category>
        <bug_description>Off by one</bug_description>
        <buggy_code>
        ```python
        def add(a, b):
            return a + b + 1
        ```
        </buggy_code>
    """)

    result = _parse_bug_response(response, target)
    assert result is not None
    assert "return a + b + 1" in result.buggy_code
    assert "```" not in result.buggy_code


def test_parse_bug_response_no_code_block() -> None:
    target = {
        "file": "mod.py",
        "function_name": "add",
        "source": "def add(a, b):\n    return a + b",
        "language": "python",
    }
    response = "Just some text without proper tags"

    result = _parse_bug_response(response, target)
    assert result is None


def test_parse_bug_response_identical_code() -> None:
    target = {
        "file": "mod.py",
        "function_name": "add",
        "source": "def add(a, b):\n    return a + b",
        "language": "python",
    }
    response = textwrap.dedent("""\
        <bug_category>none</bug_category>
        <bug_description>No change</bug_description>
        <buggy_code>
        def add(a, b):
            return a + b
        </buggy_code>
    """)

    result = _parse_bug_response(response, target)
    assert result is None


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def test_cli_synthesize_args() -> None:
    from swebenchify.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "synthesize",
        "--repo", "owner/repo",
        "--language", "python",
        "--max-mutations", "5",
        "--output-dir", "/tmp/out",
        "--base-commit", "abc123",
        "--model", "haiku",
    ])

    assert args.command == "synthesize"
    assert args.repo == "owner/repo"
    assert args.language == "python"
    assert args.max_mutations == 5
    assert args.output_dir == "/tmp/out"
    assert args.base_commit == "abc123"
    assert args.model == "haiku"


def test_cli_synthesize_defaults() -> None:
    from swebenchify.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "synthesize",
        "--repo", "org/project",
        "--language", "go",
    ])

    assert args.command == "synthesize"
    assert args.max_mutations == 10
    assert args.output_dir == "output"
    assert args.base_commit is None
    assert args.model == "sonnet"


def test_cli_synthesize_language_choices() -> None:
    from swebenchify.cli import build_parser

    parser = build_parser()
    for lang in ("python", "go", "rust", "java"):
        args = parser.parse_args([
            "synthesize", "--repo", "o/r", "--language", lang,
        ])
        assert args.language == lang

    with pytest.raises(SystemExit):
        parser.parse_args([
            "synthesize", "--repo", "o/r", "--language", "cobol",
        ])


# ---------------------------------------------------------------------------
# generate_test_patch — format & helpers
# ---------------------------------------------------------------------------

def test_generate_test_patch_format() -> None:
    """Verify the test_patch is a valid unified diff with proper git headers."""
    test_content = "import pytest\n\ndef test_example():\n    assert 1 + 1 == 2\n"
    test_path = "tests/test_synth_add.py"

    patch = _format_new_test_patch(test_content, test_path)

    assert patch.startswith("diff --git a/tests/test_synth_add.py b/tests/test_synth_add.py")
    assert "new file mode 100644" in patch
    assert "--- a/tests/test_synth_add.py" in patch
    assert "+++ b/tests/test_synth_add.py" in patch
    assert "+import pytest" in patch
    assert "+def test_example():" in patch


def test_build_candidate_with_test_patch() -> None:
    """Verify test_patch is set correctly on CandidateInstance."""
    bug_spec = BugSpec(
        file="src/util.py",
        function_name="parse",
        original_code="def parse(s):\n    return int(s)",
        buggy_code="def parse(s):\n    return float(s)",
        bug_description="Returns float instead of int",
        bug_category="wrong-type",
    )
    sr = SynthesisResult(
        bug_spec=bug_spec,
        patch="diff...",
        problem_statement="issue",
        instance_id="",
        base_commit="aaa",
    )

    tp = "diff --git a/tests/test_synth_parse.py b/tests/test_synth_parse.py\n+test"
    candidate = build_candidate("o/r", "aaa", sr, test_patch=tp)
    assert candidate.test_patch == tp

    candidate_empty = build_candidate("o/r", "aaa", sr)
    assert candidate_empty.test_patch == ""


# ---------------------------------------------------------------------------
# _validate_mutation_parses
# ---------------------------------------------------------------------------

def test_validate_mutation_parses_python_valid() -> None:
    code = "def hello():\n    return 42\n"
    assert _validate_mutation_parses(code, "python") is True


def test_validate_mutation_parses_python_invalid() -> None:
    code = "def hello(\n    return 42\n"
    assert _validate_mutation_parses(code, "python") is False


def test_validate_mutation_parses_go() -> None:
    code = "this is not valid go but we don't validate it"
    assert _validate_mutation_parses(code, "go") is True


# ---------------------------------------------------------------------------
# issue description — no file/function leak
# ---------------------------------------------------------------------------

def test_issue_description_no_file_leak() -> None:
    """Verify the prompt template doesn't contain file paths or function names."""
    from unittest.mock import MagicMock, patch

    bug_spec = BugSpec(
        file="src/internal/processor.py",
        function_name="process_data",
        original_code="def process_data(x):\n    return x + 1",
        buggy_code="def process_data(x):\n    return x - 1",
        bug_description="Returns wrong result for positive inputs",
        bug_category="incorrect-operator",
    )

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield  # make it an async generator

    with patch("swebenchify.synthesizer.query", fake_query), \
         patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_description
        result = asyncio.run(generate_issue_description(bug_spec))

    # First prompt is _bug_to_symptom; second is the issue generation
    # Neither should contain file paths or function names
    for p in captured_prompts:
        assert "src/internal/processor.py" not in p
        assert "process_data" not in p
    assert "Seeing an issue with" in result
    assert "src/internal/processor.py" not in result
    assert "process_data" not in result


def test_generate_issue_from_symptom_no_bugspec() -> None:
    """Verify generate_issue_from_symptom takes no BugSpec and only symptom."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="time duration handling uses wrong units",
            repo_context={"version": "2.0", "lang_version": "3.11", "os_info": "Ubuntu 22.04"},
        ))

    assert len(captured_prompts) >= 1
    issue_prompt = captured_prompts[0]
    assert "time duration handling" in issue_prompt
    assert "2.0" in issue_prompt
    assert "Ubuntu 22.04" in issue_prompt
    # Fallback result since fake_query returns nothing
    assert "Seeing an issue with" in result


def test_generate_issue_from_symptom_with_style_examples() -> None:
    """Verify style examples are included in the prompt."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        asyncio.run(generate_issue_from_symptom(
            symptom="parsing breaks on unicode input",
            style_examples=["Fix config loading for nested keys", "Handle empty input gracefully"],
        ))

    assert len(captured_prompts) >= 1
    assert "Fix config loading for nested keys" in captured_prompts[0]
    assert "Handle empty input gracefully" in captured_prompts[0]


# ---------------------------------------------------------------------------
# _find_existing_test_file
# ---------------------------------------------------------------------------

def test_find_existing_test_file_python(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def foo(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")

    result = _find_existing_test_file(str(tmp_path), "src/foo.py", "python")
    assert result == "tests/test_foo.py"


def test_find_existing_test_file_python_subdir(tmp_path: Path) -> None:
    (tmp_path / "src" / "bar").mkdir(parents=True)
    (tmp_path / "src" / "bar" / "baz.py").write_text("pass\n")
    (tmp_path / "src" / "bar" / "test_baz.py").write_text("pass\n")

    result = _find_existing_test_file(str(tmp_path), "src/bar/baz.py", "python")
    assert result == "src/bar/test_baz.py"


def test_find_existing_test_file_go(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "foo.go").write_text("package pkg\n")
    (tmp_path / "pkg" / "foo_test.go").write_text("package pkg\n")

    result = _find_existing_test_file(str(tmp_path), "pkg/foo.go", "go")
    assert result == "pkg/foo_test.go"


def test_find_existing_test_file_not_found(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("pass\n")

    result = _find_existing_test_file(str(tmp_path), "src/foo.py", "python")
    assert result is None


def test_test_patch_modifies_existing_file(tmp_path: Path) -> None:
    """When an existing test file is found, the patch should modify it, not create a new file."""
    from unittest.mock import MagicMock, patch as mock_patch

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    existing_test = "import pytest\n\ndef test_add_basic():\n    assert add(1, 2) == 3\n"
    (tmp_path / "tests" / "test_calc.py").write_text(existing_test)

    modified_test = existing_test + "\ndef test_add_negative():\n    assert add(-1, -2) == -3\n"

    class FakeResult:
        content = [type("B", (), {"text": f"```python\n{modified_test}\n```"})()]

    async def fake_query(prompt: str, options: object = None):
        yield FakeResult()

    bug_spec = BugSpec(
        file="src/calc.py",
        function_name="add",
        original_code="def add(a, b):\n    return a + b",
        buggy_code="def add(a, b):\n    return a - b",
        bug_description="Changed + to -",
        bug_category="incorrect-operator",
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()), \
         mock_patch("swebenchify.synthesizer.ResultMessage", FakeResult):
        import asyncio
        from swebenchify.synthesizer import generate_test_patch
        result = asyncio.run(generate_test_patch(bug_spec, str(tmp_path), "python"))

    assert result is not None
    assert "new file mode" not in result
    assert "tests/test_calc.py" in result
    assert "+def test_add_negative" in result


# ---------------------------------------------------------------------------
# _parse_incidental_changes
# ---------------------------------------------------------------------------

def test_parse_incidental_changes() -> None:
    text = """Here are some changes:
<change>
<file>CHANGELOG.md</file>
<original>
## 1.2.0
</original>
<modified>
## 1.2.1

- Fixed calculation bug

## 1.2.0
</modified>
</change>
<change>
<file>src/util.py</file>
<original>EMPTY</original>
<modified>
# end of file marker
</modified>
</change>"""

    changes = _parse_incidental_changes(text)
    assert len(changes) == 2
    assert changes[0][0] == "CHANGELOG.md"
    assert "## 1.2.0" in changes[0][1]
    assert "## 1.2.1" in changes[0][2]
    assert changes[1][0] == "src/util.py"
    assert changes[1][1] == "EMPTY"


# ---------------------------------------------------------------------------
# _collect_repo_context
# ---------------------------------------------------------------------------

def test_collect_repo_context(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "mypackage"\nversion = "2.3.1"\n'
        '\n[project.requires-python]\npython_requires = ">=3.9"\n'
    )

    ctx = _collect_repo_context(str(tmp_path))
    assert ctx["version"] == "2.3.1"
    assert ctx["os_info"]  # should be one of the OS choices


def test_collect_repo_context_empty(tmp_path: Path) -> None:
    ctx = _collect_repo_context(str(tmp_path))
    assert ctx["version"] == ""
    assert ctx["os_info"]
    assert ctx["recent_issues"] == [] or isinstance(ctx["recent_issues"], list)


# ---------------------------------------------------------------------------
# issue description — context in prompt
# ---------------------------------------------------------------------------

def test_issue_description_has_context(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch as mock_patch

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.5.0"\n')

    bug_spec = BugSpec(
        file="src/foo.py",
        function_name="foo",
        original_code="def foo(): return 1",
        buggy_code="def foo(): return 0",
        bug_description="Returns wrong value",
        bug_category="wrong-return",
    )

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_description
        asyncio.run(generate_issue_description(
            bug_spec, repo_path=str(tmp_path),
        ))

    # First call is _bug_to_symptom, second is issue generation
    assert len(captured_prompts) >= 2
    symptom_prompt = captured_prompts[0]
    assert "user-facing symptom" in symptom_prompt
    issue_prompt = captured_prompts[1]
    assert "1.5.0" in issue_prompt
    assert "OS:" in issue_prompt


# ---------------------------------------------------------------------------
# _validate_test_code
# ---------------------------------------------------------------------------

def test_validate_test_code_valid_python() -> None:
    code = textwrap.dedent("""\
        def test_parse_config():
            result = parse_config("key=val")
            assert result["key"] == "val"
    """)
    assert _validate_test_code(code, "python") is True


def test_validate_test_code_tautology_assert_true() -> None:
    code = textwrap.dedent("""\
        def test_something():
            assert True
    """)
    assert _validate_test_code(code, "python") is False


def test_validate_test_code_tautology_one_equals_one() -> None:
    code = textwrap.dedent("""\
        def test_something():
            assert 1 == 1
    """)
    assert _validate_test_code(code, "python") is False


def test_validate_test_code_no_assertions() -> None:
    code = textwrap.dedent("""\
        def test_something():
            result = compute(42)
            print(result)
    """)
    assert _validate_test_code(code, "python") is False


def test_validate_test_code_syntax_error() -> None:
    code = "def test_broken(:\n    pass"
    assert _validate_test_code(code, "python") is False


def test_validate_test_code_non_python_passes() -> None:
    """Non-Python languages skip validation (always True)."""
    code = "fn test_something() { }"
    assert _validate_test_code(code, "rust") is True


def test_validate_test_code_pytest_raises() -> None:
    code = textwrap.dedent("""\
        def test_raises():
            with pytest.raises(ValueError):
                parse_config("")
    """)
    assert _validate_test_code(code, "python") is True


def test_validate_test_code_self_assert() -> None:
    code = textwrap.dedent("""\
        class TestParser(unittest.TestCase):
            def test_parse(self):
                self.assertEqual(parse("x"), "x")
    """)
    assert _validate_test_code(code, "python") is True


# ---------------------------------------------------------------------------
# _find_related_files
# ---------------------------------------------------------------------------

def test_find_related_files(tmp_path: Path) -> None:
    """Find files that reference the target function."""
    (tmp_path / ".git").mkdir()
    src = tmp_path / "core.py"
    src.write_text("def calculate(x):\n    return x + 1\n")
    caller = tmp_path / "api.py"
    caller.write_text("from core import calculate\n\ndef handle():\n    return calculate(42)\n")
    unrelated = tmp_path / "utils.py"
    unrelated.write_text("def helper():\n    return 0\n")

    target = {"function_name": "calculate", "file": "core.py"}
    related = _find_related_files(str(tmp_path), target, "python")
    assert len(related) == 1
    assert related[0]["file"] == "api.py"
    assert "calculate" in related[0]["snippet"]


def test_find_related_files_excludes_target(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    src = tmp_path / "core.py"
    src.write_text("def foo():\n    return foo()\n")

    target = {"function_name": "foo", "file": "core.py"}
    related = _find_related_files(str(tmp_path), target, "python")
    assert len(related) == 0


# ---------------------------------------------------------------------------
# _parse_secondary_changes
# ---------------------------------------------------------------------------

def test_parse_secondary_changes_valid() -> None:
    text = """<buggy_code>...</buggy_code>

<secondary_change>
<sec_file>api.py</sec_file>
<sec_original>
result = calculate(x)
if result is None:
    raise ValueError("calculation failed")
</sec_original>
<sec_buggy>
result = calculate(x)
</sec_buggy>
<sec_description>Remove None check to match primary bug</sec_description>
</secondary_change>"""

    changes = _parse_secondary_changes(text)
    assert len(changes) == 1
    assert changes[0].file == "api.py"
    assert "ValueError" in changes[0].original_snippet
    assert "calculate(x)" in changes[0].buggy_snippet
    assert "None check" in changes[0].description


def test_parse_secondary_changes_falls_back_to_sec_fixed() -> None:
    """Old format with sec_fixed should still parse."""
    text = """<secondary_change>
<sec_file>api.py</sec_file>
<sec_original>result = calculate(x)</sec_original>
<sec_fixed>result = calculate(x, strict=True)</sec_fixed>
<sec_description>Add strict mode</sec_description>
</secondary_change>"""

    changes = _parse_secondary_changes(text)
    assert len(changes) == 1
    assert changes[0].buggy_snippet == "result = calculate(x, strict=True)"


def test_parse_secondary_changes_empty() -> None:
    text = "<buggy_code>def foo(): pass</buggy_code>"
    changes = _parse_secondary_changes(text)
    assert changes == []


def test_parse_secondary_changes_identical_rejected() -> None:
    text = """<secondary_change>
<sec_file>api.py</sec_file>
<sec_original>same code</sec_original>
<sec_buggy>same code</sec_buggy>
<sec_description>no-op</sec_description>
</secondary_change>"""

    changes = _parse_secondary_changes(text)
    assert changes == []


def test_parse_bug_response_with_secondary() -> None:
    target = {
        "file": "core.py",
        "function_name": "calc",
        "source": "def calc(x):\n    return x + 1",
        "language": "python",
    }
    text = """<bug_category>off-by-one</bug_category>
<bug_description>Returns x instead of x+1 for zero</bug_description>
<buggy_code>
def calc(x):
    return x
</buggy_code>
<secondary_change>
<sec_file>api.py</sec_file>
<sec_original>val = calc(n)\n    assert val > 0</sec_original>
<sec_buggy>val = calc(n)</sec_buggy>
<sec_description>Remove assertion that catches the bug</sec_description>
</secondary_change>"""

    spec = _parse_bug_response(text, target)
    assert spec is not None
    assert len(spec.secondary_changes) == 1
    assert spec.secondary_changes[0].file == "api.py"


# ---------------------------------------------------------------------------
# BugSpec with secondary_changes
# ---------------------------------------------------------------------------

def test_bugspec_default_secondary_changes() -> None:
    spec = BugSpec(
        file="f.py",
        function_name="fn",
        original_code="def fn(): pass",
        buggy_code="def fn(): return None",
        bug_description="returns None",
        bug_category="wrong-return",
    )
    assert spec.secondary_changes == []


# ---------------------------------------------------------------------------
# _edge_case_score
# ---------------------------------------------------------------------------

def test_edge_case_score_error_handling() -> None:
    target = {"source": "def handle():\n    try:\n        x()\n    except ValueError:\n        raise RuntimeError()"}
    assert _edge_case_score(target) >= 2


def test_edge_case_score_happy_path() -> None:
    target = {"source": "def add(a, b):\n    return a + b"}
    assert _edge_case_score(target) == 0


def test_edge_case_score_null_check() -> None:
    target = {"source": "def safe(x):\n    if x is None:\n        return default"}
    assert _edge_case_score(target) >= 1


def test_find_mutation_targets_sorted_by_score(tmp_path: Path) -> None:
    """Functions with error handling should sort before simple functions."""
    simple = tmp_path / "simple.py"
    simple.write_text("def add(a, b):\n    result = a + b\n    return result\n")
    complex_f = tmp_path / "handler.py"
    complex_f.write_text(textwrap.dedent("""\
        def process(data):
            try:
                result = parse(data)
            except ValueError:
                raise RuntimeError("bad data")
            if result is None:
                return fallback()
            return result
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    assert len(targets) == 2
    assert targets[0]["function_name"] == "process"
    assert targets[1]["function_name"] == "add"


# ---------------------------------------------------------------------------
# _find_file_commits
# ---------------------------------------------------------------------------

def test_find_file_commits(tmp_path: Path) -> None:
    """Find commits that touched a specific file in a real git repo."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    f = tmp_path / "core.py"
    f.write_text("v1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial core"], cwd=tmp_path, capture_output=True, check=True)

    f.write_text("v2")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "update core"], cwd=tmp_path, capture_output=True, check=True)

    commits = _find_file_commits(str(tmp_path), "core.py")
    assert len(commits) == 2
    assert commits[0]["subject"] == "update core"
    assert commits[0]["file"] == "core.py"
    assert len(commits[0]["sha"]) >= 7


def test_find_file_commits_no_repo(tmp_path: Path) -> None:
    commits = _find_file_commits(str(tmp_path), "nonexistent.py")
    assert commits == []


# ---------------------------------------------------------------------------
# _strip_strategy_labels
# ---------------------------------------------------------------------------

def test_strip_strategy_labels_removes_strategy_a() -> None:
    code = textwrap.dedent("""\
        def test_foo():
            # Strategy A: modify existing test
            assert foo() == 1
    """)
    result = _strip_strategy_labels(code)
    assert "Strategy A" not in result
    assert "assert foo() == 1" in result


def test_strip_strategy_labels_removes_approach_step() -> None:
    code = textwrap.dedent("""\
        # Approach 1: check edge case
        def test_edge():
            pass
        # Step 2: add assertion
        def test_more():
            pass
    """)
    result = _strip_strategy_labels(code)
    assert "Approach 1" not in result
    assert "Step 2" not in result
    assert "def test_edge():" in result
    assert "def test_more():" in result


def test_strip_strategy_labels_removes_modify_existing() -> None:
    code = "# MODIFY existing test function\ndef test_x():\n    pass\n"
    result = _strip_strategy_labels(code)
    assert "MODIFY existing" not in result
    assert "def test_x():" in result


def test_strip_strategy_labels_preserves_normal_comments() -> None:
    code = "# This is a normal comment\ndef test_x():\n    pass\n"
    result = _strip_strategy_labels(code)
    assert "# This is a normal comment" in result


def test_strip_strategy_labels_collapses_blank_lines() -> None:
    code = "line1\n\n\n\n\nline2\n"
    result = _strip_strategy_labels(code)
    assert "\n\n\n" not in result
    assert "line1" in result
    assert "line2" in result


# ---------------------------------------------------------------------------
# _validate_rst_references
# ---------------------------------------------------------------------------

def test_validate_rst_references_keeps_real() -> None:
    content = "Fixed bug :issue:`1234` and :pr:`5678`."
    result = _validate_rst_references(content, ["#1234", "#5678"])
    assert ":issue:`1234`" in result
    assert ":pr:`5678`" in result


def test_validate_rst_references_strips_fabricated() -> None:
    content = "Fixed bug :issue:`9999` and :pr:`8888`."
    result = _validate_rst_references(content, ["#1234"])
    assert ":issue:`9999`" not in result
    assert ":pr:`8888`" not in result
    assert "Fixed bug" in result


def test_validate_rst_references_mixed() -> None:
    content = "See :issue:`100` and :issue:`999`."
    result = _validate_rst_references(content, ["#100"])
    assert ":issue:`100`" in result
    assert ":issue:`999`" not in result


def test_validate_rst_references_empty_real_list() -> None:
    content = "See :issue:`42`."
    result = _validate_rst_references(content, [])
    assert ":issue:`42`" not in result


def test_validate_rst_references_no_refs() -> None:
    content = "No references here."
    result = _validate_rst_references(content, ["#100"])
    assert result == content


# ---------------------------------------------------------------------------
# _normalize_test_whitespace
# ---------------------------------------------------------------------------

def test_normalize_test_whitespace_matches_def_separator() -> None:
    original = "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"
    generated = "def test_a():\n    pass\n\ndef test_b():\n    pass\n"
    result = _normalize_test_whitespace(generated, original)
    # Original has 2 blank lines between functions; generated had 1
    # Normalization should enforce 2
    assert "\n\n\ndef test_b" in result


def test_normalize_test_whitespace_strips_trailing() -> None:
    original = "line1\nline2\n"
    generated = "line1   \nline2  \n"
    result = _normalize_test_whitespace(generated, original)
    assert "line1   " not in result
    assert "line1\n" in result


def test_normalize_test_whitespace_ensures_trailing_newline() -> None:
    original = "line1\n"
    generated = "line1"
    result = _normalize_test_whitespace(generated, original)
    assert result.endswith("\n")


# ---------------------------------------------------------------------------
# _strip_issue_shas
# ---------------------------------------------------------------------------

def test_strip_issue_shas_strips_all_hex() -> None:
    text = "See commit abcdef1234567 for details."
    result = _strip_issue_shas(text)
    assert "abcdef1234567" not in result


def test_strip_issue_shas_strips_parenthesized() -> None:
    text = "the recent merge from stable (3a9d54f) broke things"
    result = _strip_issue_shas(text)
    assert "3a9d54f" not in result


def test_strip_issue_shas_preserves_short_hex() -> None:
    text = "Error code abc12 returned."
    result = _strip_issue_shas(text)
    assert result == text


# ---------------------------------------------------------------------------
# _mine_issue_style_examples
# ---------------------------------------------------------------------------

def test_mine_issue_style_examples(tmp_path: Path) -> None:
    """Extract issue titles from git commit messages."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    f = tmp_path / "a.py"
    f.write_text("v1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Fix #42: Handle empty config gracefully"], cwd=tmp_path, capture_output=True, check=True)

    f.write_text("v2")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Closes #99: Parsing fails on unicode input"], cwd=tmp_path, capture_output=True, check=True)

    f.write_text("v3")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Regular commit with no issue ref"], cwd=tmp_path, capture_output=True, check=True)

    examples = _mine_issue_style_examples(str(tmp_path))
    assert len(examples) == 2
    assert "Parsing fails on unicode input" in examples[0]
    assert "Handle empty config gracefully" in examples[1]


def test_mine_issue_style_examples_no_repo(tmp_path: Path) -> None:
    examples = _mine_issue_style_examples(str(tmp_path))
    assert examples == []


def test_mine_issue_style_examples_no_matches(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    f = tmp_path / "a.py"
    f.write_text("v1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, capture_output=True, check=True)

    examples = _mine_issue_style_examples(str(tmp_path))
    assert examples == []


# ---------------------------------------------------------------------------
# _count_changed_lines
# ---------------------------------------------------------------------------

def test_count_changed_lines_basic() -> None:
    patch = textwrap.dedent("""\
        --- a/module.py
        +++ b/module.py
        @@ -1,3 +1,3 @@
         def add(a, b):
        -    return a - b
        +    return a + b
    """)
    assert _count_changed_lines(patch) == 2


def test_count_changed_lines_multiline() -> None:
    patch = textwrap.dedent("""\
        --- a/module.py
        +++ b/module.py
        @@ -1,5 +1,5 @@
         def process(items):
             result = []
        -    for item in items:
        -        if item >= 0:
        +    for item in items[:]:
        +        if item > 0:
                     result.append(item)
        -    return result
        +    return sorted(result)
    """)
    assert _count_changed_lines(patch) == 6


def test_count_changed_lines_empty() -> None:
    assert _count_changed_lines("") == 0


    # (critique-rewrite tests removed: _critique_and_rewrite_issue was deleted in H1)


# ---------------------------------------------------------------------------
# _find_existing_test_file — broadened search
# ---------------------------------------------------------------------------

def test_find_existing_test_file_by_import(tmp_path: Path) -> None:
    """Finds a test file that imports the same module, even with a different name."""
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "utils.py").write_text("def helper(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_integration.py").write_text(
        "from mypackage.utils import helper\n\ndef test_it():\n    assert helper() is None\n"
    )

    result = _find_existing_test_file(str(tmp_path), "mypackage/utils.py", "python")
    assert result == "tests/test_integration.py"


def test_find_existing_test_file_package_dir_fallback(tmp_path: Path) -> None:
    """Falls back to test files in the same package subdirectory under tests/."""
    (tmp_path / "mypackage" / "sub").mkdir(parents=True)
    (tmp_path / "mypackage" / "sub" / "core.py").write_text("pass\n")
    (tmp_path / "tests" / "sub").mkdir(parents=True)
    (tmp_path / "tests" / "sub" / "test_other.py").write_text("def test_x(): pass\n")

    result = _find_existing_test_file(str(tmp_path), "mypackage/sub/core.py", "python")
    assert result == "tests/sub/test_other.py"


# ---------------------------------------------------------------------------
# _source_to_module_name
# ---------------------------------------------------------------------------

def test_source_to_module_name_basic() -> None:
    assert _source_to_module_name("mypackage/utils.py") == "mypackage.utils"


def test_source_to_module_name_strips_src() -> None:
    assert _source_to_module_name("src/mypackage/utils.py") == "mypackage.utils"


def test_source_to_module_name_non_python() -> None:
    assert _source_to_module_name("main.go") is None


# ---------------------------------------------------------------------------
# _find_test_file_importing
# ---------------------------------------------------------------------------

def test_find_test_file_importing_found(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text(
        "from mypackage.api import Client\n\ndef test_client(): pass\n"
    )
    result = _find_test_file_importing(tmp_path, "mypackage.api")
    assert result == "tests/test_api.py"


def test_find_test_file_importing_parent_match(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "from mypackage import core\n\ndef test_core(): pass\n"
    )
    result = _find_test_file_importing(tmp_path, "mypackage.core")
    assert result == "tests/test_core.py"


def test_find_test_file_importing_not_found(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_other.py").write_text(
        "from unrelated import stuff\n"
    )
    result = _find_test_file_importing(tmp_path, "mypackage.core")
    assert result is None


# ---------------------------------------------------------------------------
# _discover_repo_modules
# ---------------------------------------------------------------------------

def test_discover_repo_modules(tmp_path: Path) -> None:
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "core.py").write_text("pass\n")
    (tmp_path / "mypackage" / "sub").mkdir()
    (tmp_path / "mypackage" / "sub" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "sub" / "util.py").write_text("pass\n")

    modules = _discover_repo_modules(str(tmp_path))
    assert "mypackage" in modules
    assert "mypackage.core" in modules
    assert "mypackage.sub" in modules
    assert "mypackage.sub.util" in modules


def test_discover_repo_modules_src_layout(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("")
    (tmp_path / "src" / "pkg" / "api.py").write_text("pass\n")

    modules = _discover_repo_modules(str(tmp_path))
    assert "pkg" in modules
    assert "pkg.api" in modules


# ---------------------------------------------------------------------------
# _is_stdlib_or_installed
# ---------------------------------------------------------------------------

def test_is_stdlib_or_installed_stdlib() -> None:
    assert _is_stdlib_or_installed("os", ["os"]) is True
    assert _is_stdlib_or_installed("os.path", ["os", "path"]) is True


def test_is_stdlib_or_installed_nonexistent() -> None:
    assert _is_stdlib_or_installed("totally_fake_module_xyz", ["totally_fake_module_xyz"]) is False


def test_is_stdlib_or_installed_dotted_nonexistent() -> None:
    assert _is_stdlib_or_installed("os.nonexistent_submodule_xyz", ["os", "nonexistent_submodule_xyz"]) is False


# ---------------------------------------------------------------------------
# _validate_test_imports — strengthened
# ---------------------------------------------------------------------------

def test_validate_test_imports_valid_repo_module(tmp_path: Path) -> None:
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "core.py").write_text("pass\n")

    code = "from mypackage.core import something\n"
    assert _validate_test_imports(code, str(tmp_path)) is True


def test_validate_test_imports_rejects_fabricated_submodule(tmp_path: Path) -> None:
    code = "from os.nonexistent_submodule_xyz import something\n"
    assert _validate_test_imports(code, str(tmp_path)) is False


def test_validate_test_imports_allows_stdlib(tmp_path: Path) -> None:
    code = "from os.path import join\nimport json\n"
    assert _validate_test_imports(code, str(tmp_path)) is True


def test_validate_test_imports_rejects_completely_fake(tmp_path: Path) -> None:
    code = "from totally_fake_xyz import stuff\n"
    assert _validate_test_imports(code, str(tmp_path)) is False


# ---------------------------------------------------------------------------
# generate_test_patch — returns None without existing test file
# ---------------------------------------------------------------------------

def test_generate_test_patch_returns_none_without_existing_test(tmp_path: Path) -> None:
    """When no existing test file exists, generate_test_patch returns None."""
    from unittest.mock import MagicMock, patch as mock_patch

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "orphan.py").write_text("def orphan(): pass\n")

    bug_spec = BugSpec(
        file="src/orphan.py",
        function_name="orphan",
        original_code="def orphan(): pass",
        buggy_code="def orphan(): return None",
        bug_description="Returns None",
        bug_category="wrong-return",
    )

    with mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_test_patch
        result = asyncio.run(generate_test_patch(bug_spec, str(tmp_path), "python"))

    assert result is None


# ---------------------------------------------------------------------------
# SynthesisResult.test_output field
# ---------------------------------------------------------------------------

def test_synthesis_result_has_test_output() -> None:
    bug_spec = BugSpec(
        file="a.py",
        function_name="f",
        original_code="code",
        buggy_code="buggy",
        bug_description="desc",
        bug_category="cat",
    )
    sr = SynthesisResult(
        bug_spec=bug_spec,
        patch="p",
        problem_statement="ps",
        instance_id="",
        base_commit="c",
        test_output="FAILED test_foo - AssertionError",
    )
    assert sr.test_output == "FAILED test_foo - AssertionError"


def test_synthesis_result_test_output_default() -> None:
    bug_spec = BugSpec(
        file="a.py",
        function_name="f",
        original_code="code",
        buggy_code="buggy",
        bug_description="desc",
        bug_category="cat",
    )
    sr = SynthesisResult(
        bug_spec=bug_spec,
        patch="p",
        problem_statement="ps",
        instance_id="",
        base_commit="c",
    )
    assert sr.test_output == ""


# ---------------------------------------------------------------------------
# _run_tests_on_buggy_code
# ---------------------------------------------------------------------------

def test_run_tests_on_buggy_code_captures_failure(tmp_path: Path) -> None:
    """Captures test output when tests fail against buggy code."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    f = tmp_path / "module.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    test_f = tmp_path / "test_module.py"
    test_f.write_text("from module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "correct version"], cwd=tmp_path, capture_output=True, check=True)

    f.write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy version"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    output = _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")
    assert output is not None
    assert "FAILED" in output or "assert" in output.lower() or "Error" in output


def test_run_tests_on_buggy_code_no_repo(tmp_path: Path) -> None:
    result = _run_tests_on_buggy_code(str(tmp_path), "fake_sha", "python")
    assert result is None


# ---------------------------------------------------------------------------
# H1: _critique_and_rewrite_issue is removed
# ---------------------------------------------------------------------------

def test_critique_and_rewrite_issue_is_removed() -> None:
    """Verify _critique_and_rewrite_issue no longer exists."""
    import swebenchify.synthesizer as mod
    assert not hasattr(mod, "_critique_and_rewrite_issue")


# ---------------------------------------------------------------------------
# H1: _enforce_banned_openers
# ---------------------------------------------------------------------------

def test_enforce_banned_openers_replaces() -> None:
    text = "## Title\nIs this expected behavior when parsing configs?"
    result = _enforce_banned_openers(text)
    assert not result.split("\n")[1].lower().startswith("is this expected")


def test_enforce_banned_openers_no_match() -> None:
    text = "## Title\nSomething completely different happened."
    result = _enforce_banned_openers(text)
    assert "Something completely different happened." in result


def test_enforce_banned_openers_case_insensitive() -> None:
    text = "I noticed that the output is wrong."
    result = _enforce_banned_openers(text)
    assert not result.lower().startswith("i noticed that")


def test_enforce_banned_openers_im_experiencing() -> None:
    text = "## Bug\nI'm experiencing crashes when loading data"
    result = _enforce_banned_openers(text)
    assert not result.split("\n")[1].lower().startswith("i'm experiencing")


def test_enforce_banned_openers_i_was_trying_to() -> None:
    text = "I was trying to import the module and it failed"
    result = _enforce_banned_openers(text)
    assert not result.lower().startswith("i was trying to")


# ---------------------------------------------------------------------------
# H1: _truncate_issue
# ---------------------------------------------------------------------------

def test_truncate_issue_keeps_first_paragraph_and_code() -> None:
    text = (
        "## Bug report\n"
        "First paragraph of text.\n"
        "\n"
        "Second paragraph should be dropped.\n"
        "\n"
        "```python\nprint('hello')\n```\n"
        "\n"
        "Third paragraph also dropped."
    )
    result = _truncate_issue(text)
    assert "First paragraph" in result
    assert "print('hello')" in result
    assert "Third paragraph" not in result


def test_truncate_issue_keeps_title() -> None:
    text = "## Title\nSome text.\n\nMore text.\n\nEven more."
    result = _truncate_issue(text)
    assert "## Title" in result
    assert "Some text." in result


# ---------------------------------------------------------------------------
# H1: generate_issue_from_symptom — character budget in prompt
# ---------------------------------------------------------------------------

def test_generate_issue_from_symptom_has_char_budget() -> None:
    """Verify char budget instruction appears in the prompt."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        asyncio.run(generate_issue_from_symptom(
            symptom="parsing breaks on unicode",
        ))

    assert len(captured_prompts) >= 1
    prompt = captured_prompts[0]
    assert "characters" in prompt.lower()
    assert "CONCISE" in prompt


def test_generate_issue_from_symptom_no_critical_requirements() -> None:
    """Verify the CRITICAL REQUIREMENTS block is gone from the prompt."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        asyncio.run(generate_issue_from_symptom(
            symptom="test symptom",
        ))

    prompt = captured_prompts[0]
    assert "CRITICAL REQUIREMENTS" not in prompt


def test_generate_issue_from_symptom_no_structure_templates() -> None:
    """Verify the 4 structure options (ERROR FIRST etc.) are gone."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        asyncio.run(generate_issue_from_symptom(
            symptom="test symptom",
        ))

    prompt = captured_prompts[0]
    assert "ERROR FIRST" not in prompt
    assert "QUESTION FIRST" not in prompt
    assert "REPRODUCTION FIRST" not in prompt
    assert "RAMBLING" not in prompt


# ---------------------------------------------------------------------------
# H2: _find_related_files — import scanning
# ---------------------------------------------------------------------------

def test_find_related_files_finds_importers(tmp_path: Path) -> None:
    """Finds files that import the target module."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "core.py").write_text(
        "def process(x):\n    return x + 1\n"
    )
    (tmp_path / "mypackage" / "api.py").write_text(
        "from mypackage.core import process\n\ndef handle():\n    return process(42)\n"
    )

    target = {
        "function_name": "process",
        "file": "mypackage/core.py",
    }
    related = _find_related_files(str(tmp_path), target, "python")
    files = [r["file"] for r in related]
    assert "mypackage/api.py" in files


def test_find_related_files_finds_imports_of_target(tmp_path: Path) -> None:
    """Finds files imported by the target module."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "utils.py").write_text(
        "def helper():\n    return 0\n"
    )
    (tmp_path / "mypackage" / "core.py").write_text(
        "from mypackage.utils import helper\n\ndef process(x):\n    return helper() + x\n"
    )

    target = {
        "function_name": "process",
        "file": "mypackage/core.py",
    }
    related = _find_related_files(str(tmp_path), target, "python")
    files = [r["file"] for r in related]
    assert "mypackage/utils.py" in files


def test_find_related_files_finds_test_files(tmp_path: Path) -> None:
    """Finds test files for the target module."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "core.py").write_text(
        "def process(x):\n    return x + 1\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "from mypackage.core import process\n\ndef test_process():\n    assert process(1) == 2\n"
    )

    target = {
        "function_name": "process",
        "file": "mypackage/core.py",
    }
    related = _find_related_files(str(tmp_path), target, "python")
    files = [r["file"] for r in related]
    assert "tests/test_core.py" in files


# ---------------------------------------------------------------------------
# H2: _plan_multi_file_mutation — prompt construction
# ---------------------------------------------------------------------------

def test_plan_multi_file_mutation_prompt() -> None:
    """Verify prompt is constructed correctly with target and related files."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import _plan_multi_file_mutation
        result = asyncio.run(_plan_multi_file_mutation(
            target_func_code="def process(x):\n    return x + 1",
            related_files=[
                {"file": "api.py", "snippet": "from core import process"},
            ],
        ))

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "def process(x)" in prompt
    assert "api.py" in prompt
    assert "spans multiple files" in prompt
    assert result is None  # fake_query returns nothing


def test_plan_multi_file_mutation_returns_none_without_related() -> None:
    """Returns None when no related files are provided."""
    import asyncio
    from swebenchify.synthesizer import _plan_multi_file_mutation
    result = asyncio.run(_plan_multi_file_mutation(
        target_func_code="def foo(): pass",
        related_files=[],
    ))
    assert result is None


# ---------------------------------------------------------------------------
# H2: BugPlan dataclass
# ---------------------------------------------------------------------------

def test_bugplan_defaults() -> None:
    plan = BugPlan(primary_description="change return type")
    assert plan.primary_description == "change return type"
    assert plan.secondary_descriptions == []


def test_bugplan_with_secondaries() -> None:
    plan = BugPlan(
        primary_description="primary bug",
        secondary_descriptions=[
            {"file": "api.py", "plan": "update caller"},
        ],
    )
    assert len(plan.secondary_descriptions) == 1
    assert plan.secondary_descriptions[0]["file"] == "api.py"


# ---------------------------------------------------------------------------
# Issue 2: _truncate_issue hard cap on single-paragraph text
# ---------------------------------------------------------------------------

def test_truncate_issue_hard_caps_single_paragraph() -> None:
    """A single long paragraph with no breaks is sliced at 1500 chars."""
    text = "## Title\n" + "A" * 2000
    result = _truncate_issue(text)
    assert len(result) <= 1500


# ---------------------------------------------------------------------------
# Issue 3: _enforce_banned_openers produces grammatically valid text
# ---------------------------------------------------------------------------

def test_enforce_banned_openers_no_awkward_concatenation() -> None:
    """Replacement should be a complete opener, not prefix + leftover."""
    text = "## Title\nIs this expected behavior when parsing configs?"
    result = _enforce_banned_openers(text)
    second_line = result.split("\n")[1]
    assert second_line in [
        'Has anyone seen this before?',
        'Possible bug —',
        'Something broke after the latest update.',
        'Getting unexpected behavior.',
        'Not sure if this is a bug, but...',
    ]


# ---------------------------------------------------------------------------
# Issue 1: bug_plan is passed to introduce_bug when available
# ---------------------------------------------------------------------------

def test_introduce_bug_receives_bug_plan() -> None:
    """When bug_plan is provided, its content appears in the LLM prompt."""
    from unittest.mock import MagicMock, patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    target = {
        "file": "core.py",
        "function_name": "process",
        "source": "def process(x):\n    return x + 1",
        "language": "python",
    }
    plan = BugPlan(
        primary_description="Change return type from int to str",
        secondary_descriptions=[
            {"file": "api.py", "plan": "Update caller to handle str"},
        ],
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import introduce_bug
        asyncio.run(introduce_bug(target, bug_plan=plan))

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "MULTI-FILE BUG PLAN: Change return type from int to str" in prompt
    assert "Secondary change needed in api.py: Update caller to handle str" in prompt
    assert "Your bug MUST include the secondary changes" in prompt


# ---------------------------------------------------------------------------
# H1: _humanize_traceback
# ---------------------------------------------------------------------------

def test_humanize_traceback_replaces_tmp_paths(tmp_path: Path) -> None:
    test_output = (
        "FAILED tests/test_core.py::test_add\n"
        "  File \"/tmp/pytest-abc123/test_core.py\", line 5\n"
        "    assert add(1, 2) == 3\n"
        "AssertionError: -1 != 3"
    )
    result = _humanize_traceback(test_output, str(tmp_path))
    assert "/tmp/pytest-abc123/" not in result
    assert "/home/" in result
    assert "AssertionError" in result


def test_humanize_traceback_strips_headers(tmp_path: Path) -> None:
    test_output = (
        "============================= test session starts =============================\n"
        "collected 5 items\n"
        "FAILED tests/test_core.py::test_add - AssertionError\n"
        "============================== 1 failed ==============================="
    )
    result = _humanize_traceback(test_output, str(tmp_path))
    assert "test session starts" not in result
    assert "collected 5 items" not in result
    assert "1 failed" not in result
    assert "FAILED" in result


def test_humanize_traceback_empty_input(tmp_path: Path) -> None:
    assert _humanize_traceback("", str(tmp_path)) == ""
    assert _humanize_traceback(None, str(tmp_path)) == ""


def test_humanize_traceback_preserves_error_data(tmp_path: Path) -> None:
    test_output = (
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
        "  File \"module.py\", line 42"
    )
    result = _humanize_traceback(test_output, str(tmp_path))
    assert "TypeError" in result
    assert "line 42" in result


# ---------------------------------------------------------------------------
# H2: _mine_social_artifacts
# ---------------------------------------------------------------------------

def test_mine_social_artifacts(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Alice Dev"], cwd=tmp_path, capture_output=True, check=True)

    f = tmp_path / "a.py"
    f.write_text("v1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Fix #42: initial commit"], cwd=tmp_path, capture_output=True, check=True)

    f.write_text("v2")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Closes #99: second commit"], cwd=tmp_path, capture_output=True, check=True)

    artifacts = _mine_social_artifacts(str(tmp_path))
    assert "Alice Dev" in artifacts["contributors"]
    assert len(artifacts["shas"]) == 2
    assert "42" in artifacts["issues"]
    assert "99" in artifacts["issues"]


def test_mine_social_artifacts_no_repo(tmp_path: Path) -> None:
    artifacts = _mine_social_artifacts(str(tmp_path))
    assert artifacts["contributors"] == []
    assert artifacts["shas"] == []
    assert artifacts["issues"] == []
    assert artifacts["branches"] == []


# ---------------------------------------------------------------------------
# H2: _build_social_context
# ---------------------------------------------------------------------------

def test_build_social_context_produces_references() -> None:
    import random as _random
    _random.seed(42)
    artifacts = {
        "contributors": ["Alice", "Bob"],
        "shas": ["abc1234"],
        "issues": ["42"],
        "branches": ["main", "develop"],
    }
    results = set()
    for _ in range(50):
        ctx = _build_social_context(artifacts)
        if ctx:
            lines = [ln for ln in ctx.strip().split("\n") if ln.strip()]
            assert len(lines) <= 2
            results.add(len(lines))
    assert 1 in results or 2 in results


def test_build_social_context_empty_artifacts() -> None:
    artifacts: dict[str, list[str]] = {
        "contributors": [],
        "shas": [],
        "issues": [],
        "branches": [],
    }
    result = _build_social_context(artifacts)
    assert result == ""


# ---------------------------------------------------------------------------
# H1: generate_issue_from_symptom with test_output (data-first path)
# ---------------------------------------------------------------------------

def test_generate_issue_from_symptom_data_first() -> None:
    """When test_output is provided, the issue contains the traceback text."""
    from unittest.mock import MagicMock, patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        class FakeResult:
            content = [type("B", (), {"text": "Broken parsing\n\nThis is completely broken."})()]
        yield FakeResult()

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()), \
         mock_patch("swebenchify.synthesizer.ResultMessage", type("FR", (), {})):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="parsing fails on unicode",
            test_output="FAILED test_parse - UnicodeDecodeError: 'utf-8' codec",
            repo_context={"version": "2.0", "lang_version": "3.11", "os_info": "Ubuntu 22.04"},
        ))

    assert "FAILED test_parse" in result
    assert "UnicodeDecodeError" in result
    assert "```" in result
    assert "Environment:" in result


def test_generate_issue_from_symptom_data_first_fallback() -> None:
    """Data-first path produces reasonable output even when LLM fails."""
    from unittest.mock import MagicMock, patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="broken feature",
            test_output="AssertionError: expected 3 got -1",
        ))

    assert "AssertionError" in result
    assert "Bug:" in result


def test_generate_issue_from_symptom_with_social_context() -> None:
    """Social context is appended to the issue."""
    from unittest.mock import MagicMock, patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="broken feature",
            social_context="\n\n@alice might know more",
        ))

    assert "@alice might know more" in result


def test_generate_issue_from_symptom_no_strip_shas() -> None:
    """Verify _strip_issue_shas is no longer applied to issue text."""
    from unittest.mock import MagicMock, patch as mock_patch

    class FakeResult:
        content = [type("B", (), {"text": "## Bug\nSee commit abcdef1234567 for context."})()]

    async def fake_query(prompt: str, options: object = None):
        yield FakeResult()

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()), \
         mock_patch("swebenchify.synthesizer.ResultMessage", FakeResult):
        import asyncio
        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="test symptom",
        ))

    assert "abcdef1234567" in result


# ---------------------------------------------------------------------------
# H3: Patch floor thresholds
# ---------------------------------------------------------------------------

def test_patch_floor_accepts_5_lines_500_chars() -> None:
    """Verify new thresholds: 5 changed lines, 500 chars."""
    import swebenchify.synthesizer as mod
    import inspect
    source = inspect.getsource(mod.synthesize_repo)
    assert "changed >= 5" in source
    assert 'len(patch) >= 500' in source


def test_patch_floor_log_messages_updated() -> None:
    """Verify log messages reflect new thresholds."""
    import swebenchify.synthesizer as mod
    import inspect
    source = inspect.getsource(mod.synthesize_repo)
    assert 'changed lines < 5' in source
    assert 'chars < 500' in source
