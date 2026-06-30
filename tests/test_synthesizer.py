"""Tests for swebenchify.synthesizer — no LLM calls required."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebenchify.synthesizer import (
    BugSpec,
    SynthesisResult,
    _parse_bug_response,
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

    candidate = build_candidate("owner/repo", "abc123", synthesis_result)

    assert candidate.repo == "owner/repo"
    assert candidate.base_commit == "abc123"
    assert candidate.patch == "--- a/src/core.py\n+++ b/src/core.py\n..."
    assert candidate.test_patch == ""
    assert candidate.problem_statement == "Calculate returns wrong results"
    assert candidate.hints_text == ""
    assert candidate.pr_number == 0
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

    assert candidate.instance_id.startswith("myorg__myrepo-synth-")
    parts = candidate.instance_id.split("-synth-")
    assert len(parts) == 2
    assert len(parts[1]) == 8  # short SHA-256 hash


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
