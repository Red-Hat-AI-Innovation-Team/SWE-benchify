"""Tests for swebenchify.synthesizer — no LLM calls required."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from swebenchify.synthesizer import (
    BugPlan,
    BugSpec,
    RepoSynthesisResult,
    SynthesisResult,
    _align_indentation,
    _analyze_test_assertions,
    _BraceCounter,
    _build_social_context,
    _collect_repo_context,
    _count_changed_lines,
    _count_test_functions,
    _describe_targeted_mutation,
    _discover_repo_modules,
    _edge_case_score,
    _enforce_banned_openers,
    _ensure_venv,
    _extract_brace_language_functions,
    _extract_called_func,
    _extract_failed_test_names,
    _find_existing_test_file,
    _find_file_commits,
    _find_related_files,
    _find_test_file_importing,
    _format_new_test_patch,
    _humanize_traceback,
    _is_stdlib_or_installed,
    _is_valid_test_output,
    _load_dataset_examples,
    _mine_issue_style_examples,
    _mine_social_artifacts,
    _mutate_remove_raise,
    _mutate_return_non_none,
    _mutate_return_none,
    _mutate_swap_operator,
    _normalize_test_whitespace,
    _parse_bug_response,
    _parse_incidental_changes,
    _parse_secondary_changes,
    _preserve_unchanged_lines,
    _run_tests_on_buggy_code,
    _sanitize_test_output,
    _source_to_module_name,
    _strip_issue_shas,
    _strip_strategy_labels,
    _targeted_mutation,
    _truncate_issue,
    _try_targeted_mutation,
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
            if not name:
                raise ValueError("name required")
            cleaned = name.strip()
            parts = cleaned.split()
            first = parts[0]
            return f"Hello, {first}!"

        def add(a, b):
            if a is None:
                raise TypeError("a is None")
            if b is None:
                raise TypeError("b is None")
            result = a + b
            validated = int(result)
            return validated
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    assert len(targets) == 2
    assert targets[0]["function_name"] in ("hello", "add")
    assert targets[0]["language"] == "python"
    assert targets[0]["file"] == "module.py"


def test_find_mutation_targets_python_nested(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    src = pkg / "core.py"
    src.write_text(textwrap.dedent("""\
        class Calculator:
            def multiply(self, a, b):
                if a is None:
                    raise TypeError("a is None")
                if b is None:
                    raise TypeError("b is None")
                result = a * b
                validated = int(result)
                return validated
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
            if a < 0 {
                return -1
            }
            if b < 0 {
                return -1
            }
            result := a + b
            return result
        }

        func (s *Server) Handle(req Request) Response {
            if req == nil {
                return Response{}
            }
            data := s.process(req)
            validated := s.validate(data)
            if validated == nil {
                return Response{}
            }
            return Response{Data: validated}
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    assert len(targets) == 2
    assert targets[0]["function_name"] in ("Add", "Handle")
    assert targets[0]["language"] == "go"


# ---------------------------------------------------------------------------
# find_mutation_targets — Rust
# ---------------------------------------------------------------------------

def test_find_mutation_targets_rust(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(textwrap.dedent("""\
        pub fn calculate(x: i32, y: i32) -> i32 {
            if x < 0 {
                return -1;
            }
            if y < 0 {
                return -1;
            }
            let result = x + y;
            result
        }

        fn helper(s: &str) -> String {
            if s.is_empty() {
                return String::new();
            }
            let trimmed = s.trim();
            let lower = trimmed.to_lowercase();
            let owned = lower.to_string();
            let validated = owned.clone();
            validated
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "rust")
    assert len(targets) == 2
    assert targets[0]["function_name"] in ("calculate", "helper")
    assert targets[0]["language"] == "rust"


def test_find_mutation_targets_rust_async(tmp_path: Path) -> None:
    src = tmp_path / "server.rs"
    src.write_text(textwrap.dedent("""\
        pub async fn fetch(url: &str) -> Result<String, Error> {
            if url.is_empty() {
                return Err(Error::new("empty url"));
            }
            let client = Client::new();
            let resp = client.get(url).await?;
            let body = resp.text().await?;
            let trimmed = body.trim().to_string();
            Ok(trimmed)
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
                if (a < 0) {
                    throw new IllegalArgumentException("a negative");
                }
                if (b < 0) {
                    throw new IllegalArgumentException("b negative");
                }
                int result = a + b;
                return result;
            }

            private String format(int value) {
                if (value < 0) {
                    return "negative";
                }
                String formatted = String.valueOf(value);
                String trimmed = formatted.trim();
                String padded = "  " + trimmed;
                String result = padded.strip();
                return result;
            }
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "java")
    assert len(targets) == 2
    assert targets[0]["function_name"] in ("add", "format")
    assert targets[0]["language"] == "java"


# ---------------------------------------------------------------------------
# _BraceCounter — unit tests for string/comment-aware brace counting
# ---------------------------------------------------------------------------


class TestBraceCounterBasic:
    def test_plain_braces(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("func main() {") == (1, 0)
        assert c.count_braces("}") == (0, 1)

    def test_braces_in_double_quoted_string(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces('x := "{ }"') == (0, 0)

    def test_braces_in_line_comment(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("x := 1 // { }") == (0, 0)

    def test_braces_in_block_comment(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("x := 1 /* { */") == (0, 0)
        assert c.in_block_comment is False

    def test_multiline_block_comment(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("/* start { ") == (0, 0)
        assert c.in_block_comment is True
        assert c.count_braces(" } end */") == (0, 0)
        assert c.in_block_comment is False
        assert c.count_braces("{") == (1, 0)

    def test_escaped_quote_in_string(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces(r'x := "hello \" { world"') == (0, 0)

    def test_mixed_code_and_string_braces(self) -> None:
        c = _BraceCounter("go")
        opens, closes = c.count_braces('if x == "{" {')
        assert opens == 1
        assert closes == 0


class TestBraceCounterGo:
    def test_backtick_string(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("x := `{ }`") == (0, 0)

    def test_multiline_backtick_string(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("x := `start {") == (0, 0)
        assert c.in_backtick_string is True
        assert c.count_braces("} end`") == (0, 0)
        assert c.in_backtick_string is False

    def test_single_char_literal(self) -> None:
        c = _BraceCounter("go")
        assert c.count_braces("x := '{'") == (0, 0)


class TestBraceCounterRust:
    def test_raw_string(self) -> None:
        c = _BraceCounter("rust")
        assert c.count_braces('let x = r#"{ }"#;') == (0, 0)

    def test_raw_string_double_hash(self) -> None:
        c = _BraceCounter("rust")
        assert c.count_braces('let x = r##"{ }"##;') == (0, 0)

    def test_multiline_raw_string(self) -> None:
        c = _BraceCounter("rust")
        assert c.count_braces('let x = r#"start {') == (0, 0)
        assert c.in_rust_raw_string is True
        assert c.count_braces('} end"#;') == (0, 0)
        assert c.in_rust_raw_string is False

    def test_char_literal(self) -> None:
        c = _BraceCounter("rust")
        assert c.count_braces("let c = '{';") == (0, 0)

    def test_escaped_char_literal(self) -> None:
        c = _BraceCounter("rust")
        assert c.count_braces("let c = '\\n';") == (0, 0)

    def test_lifetime_not_confused_as_char(self) -> None:
        c = _BraceCounter("rust")
        opens, closes = c.count_braces("fn foo<'a>(x: &'a str) -> &'a str {")
        assert opens == 1
        assert closes == 0


class TestBraceCounterJava:
    def test_char_literal(self) -> None:
        c = _BraceCounter("java")
        assert c.count_braces("char c = '{';") == (0, 0)

    def test_string_with_braces(self) -> None:
        c = _BraceCounter("java")
        assert c.count_braces('String s = "{ }";') == (0, 0)

    def test_escaped_quote(self) -> None:
        c = _BraceCounter("java")
        assert c.count_braces(r'String s = "hello \" { world";') == (0, 0)


# ---------------------------------------------------------------------------
# Brace-aware extraction — integration tests
# ---------------------------------------------------------------------------

def test_go_extractor_braces_in_strings(tmp_path: Path) -> None:
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Format(x int) string {
            if x < 0 {
                return "{ negative }"
            }
            msg := fmt.Sprintf("value={%d}", x)
            a := msg + " extra"
            b := a + " more"
            c := strings.TrimSpace(b)
            return c
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    names = [t["function_name"] for t in targets]
    assert "Format" in names
    fmt_target = next(t for t in targets if t["function_name"] == "Format")
    assert 'return "{ negative }"' in fmt_target["source"]


def test_go_extractor_braces_in_comments(tmp_path: Path) -> None:
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Compute(x int) int {
            // This does { complex stuff }
            if x > 0 {
                return x * 2
            }
            /* also handles {
               edge } cases */
            a := x + 1
            b := a + 2
            return b
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "Compute"
    assert "return b" in targets[0]["source"]


def test_go_extractor_backtick_string(tmp_path: Path) -> None:
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Template(name string) string {
            tmpl := `Hello {
                name }!`
            if name == "" {
                return "unknown"
            }
            cleaned := strings.TrimSpace(name)
            formatted := fmt.Sprintf(tmpl, cleaned)
            return formatted
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "go")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "Template"
    assert "return formatted" in targets[0]["source"]


def test_rust_extractor_raw_string(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(textwrap.dedent("""\
        pub fn pattern(x: i32) -> &'static str {
            let re = r#"\\{[0-9]+\\}"#;
            if x > 0 {
                return re;
            }
            let a = x + 1;
            let b = a + 2;
            let c = b * 3;
            "none"
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "rust")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "pattern"
    assert '"none"' in targets[0]["source"]


def test_java_extractor_braces_in_strings(tmp_path: Path) -> None:
    src = tmp_path / "Formatter.java"
    src.write_text(textwrap.dedent("""\
        public class Formatter {
            public String format(int value) {
                if (value < 0) {
                    return "{ error }";
                }
                String template = "result={" + value + "}";
                String wrapped = template.trim();
                String padded = "  " + wrapped;
                String result = padded.strip();
                return result;
            }
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "java")
    assert len(targets) == 1
    assert targets[0]["function_name"] == "format"
    assert "return result" in targets[0]["source"]


def test_brace_counter_preserves_state_between_functions() -> None:
    """Block comment starting before a function should carry state correctly."""
    lines = [
        "/* start of comment",
        " { } braces inside comment",
        " end of comment */",
        "func Foo() int {",
        "    return 1",
        "}",
    ]
    fns = _extract_brace_language_functions(lines, "go")
    assert len(fns) == 1
    assert fns[0]["function_name"] == "Foo"


# ---------------------------------------------------------------------------
# find_mutation_targets — exclusions
# ---------------------------------------------------------------------------

def test_find_mutation_targets_excludes_python_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.write_text(textwrap.dedent("""\
        def test_something():
            a = 1
            b = 2
            c = a + b
            d = c * 2
            e = d - 1
            assert e > 0
            return e
    """))
    conftest = tmp_path / "conftest.py"
    conftest.write_text(textwrap.dedent("""\
        def my_fixture():
            a = 1
            b = 2
            c = a + b
            d = c * 2
            e = d - 1
            f = e + 10
            return f
    """))
    setup = tmp_path / "setup.py"
    setup.write_text("from setuptools import setup\nsetup()\npass\n")
    init = tmp_path / "__init__.py"
    init.write_text("")

    src = tmp_path / "real.py"
    src.write_text(textwrap.dedent("""\
        def real_function():
            value = 42
            if value < 0:
                raise ValueError("negative")
            result = value * 2
            cleaned = str(result)
            validated = int(cleaned)
            return validated
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
            a := 1
            b := 2
            c := a + b
            d := c * 2
            e := d - 1
            result := Add(e, b)
            assert(result == 3)
        }
    """))
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    vendor_file = vendor / "lib.go"
    vendor_file.write_text(textwrap.dedent("""\
        package vendor

        func VendorFunc() int {
            a := 1
            b := 2
            c := a + b
            d := c * 2
            e := d - 1
            value := e + 42
            return value
        }
    """))
    src = tmp_path / "main.go"
    src.write_text(textwrap.dedent("""\
        package main

        func Main() int {
            a := 1
            b := 2
            c := a + b
            d := c * 2
            e := d - 1
            value := e + 1
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
            let a = 1;
            let b = 2;
            let c = a + b;
            let d = c * 2;
            let e = d - 1;
            let x = e + 10;
            assert_eq!(x, 15);
        }
    """))
    src = tmp_path / "lib.rs"
    src.write_text(textwrap.dedent("""\
        pub fn compute(x: i32) -> i32 {
            if x < 0 {
                return -1;
            }
            let a = x + 1;
            let b = a * 2;
            let result = b - x;
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
                int a = 1;
                int b = 2;
                int c = a + b;
                int d = c * 2;
                int result = calc.add(d, b);
                assertEquals(8, result);
            }
        }
    """))
    test_dir = tmp_path / "src" / "test" / "java"
    test_dir.mkdir(parents=True)
    test_dir_file = test_dir / "Foo.java"
    test_dir_file.write_text(textwrap.dedent("""\
        public class Foo {
            public void testBar() {
                int a = 1;
                int b = 2;
                int c = a + b;
                int d = c * 2;
                int x = d - 1;
                assertEquals(5, x);
            }
        }
    """))
    src = tmp_path / "Main.java"
    src.write_text(textwrap.dedent("""\
        public class Main {
            public int run(int x) {
                if (x < 0) {
                    throw new IllegalArgumentException("negative");
                }
                int a = x + 1;
                int b = a * 2;
                int result = b - x;
                return result;
            }
        }
    """))

    targets = find_mutation_targets(str(tmp_path), "java")
    files = {t["file"] for t in targets}
    assert "Main.java" in files
    assert "CalculatorTest.java" not in files
    assert "src/test/java/Foo.java" not in files


def test_find_mutation_targets_excludes_docs_dir(tmp_path: Path) -> None:
    """Files under docs/ directory are excluded from mutation targets."""
    docs = tmp_path / "docs"
    docs.mkdir()
    doc_file = docs / "conf.py"
    doc_file.write_text(textwrap.dedent("""\
        def setup(app):
            if app is None:
                raise ValueError("app required")
            config = app.config
            config.update({"key": "value"})
            validated = config.get("key")
            result = validated.strip()
            return result
    """))
    src = tmp_path / "core.py"
    src.write_text(textwrap.dedent("""\
        def process(data):
            if data is None:
                raise ValueError("data required")
            cleaned = data.strip()
            parts = cleaned.split(",")
            result = [p.strip() for p in parts]
            validated = [p for p in result if p]
            return validated
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    files = {t["file"] for t in targets}
    assert "core.py" in files
    assert "docs/conf.py" not in files


def test_find_mutation_targets_excludes_examples_dir(tmp_path: Path) -> None:
    """Files under examples/ directory are excluded from mutation targets."""
    examples = tmp_path / "examples"
    examples.mkdir()
    example_file = examples / "demo.py"
    example_file.write_text(textwrap.dedent("""\
        def run_demo():
            config = load_config()
            if config is None:
                raise RuntimeError("no config")
            app = create_app(config)
            result = app.start()
            status = result.get("status")
            return status
    """))
    src = tmp_path / "lib.py"
    src.write_text(textwrap.dedent("""\
        def compute(x, y):
            if x is None:
                raise TypeError("x required")
            if y is None:
                raise TypeError("y required")
            result = x + y
            validated = int(result)
            return validated
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    files = {t["file"] for t in targets}
    assert "lib.py" in files
    assert "examples/demo.py" not in files


def test_find_mutation_targets_min_function_size(tmp_path: Path) -> None:
    """Functions with fewer than 8 lines are excluded."""
    src = tmp_path / "module.py"
    src.write_text(textwrap.dedent("""\
        def tiny():
            return 1

        def small(x):
            result = x + 1
            return result

        def big_enough(data):
            if data is None:
                raise ValueError("data required")
            cleaned = data.strip()
            parts = cleaned.split(",")
            result = [p.strip() for p in parts]
            validated = [p for p in result if p]
            return validated
    """))

    targets = find_mutation_targets(str(tmp_path), "python")
    names = {t["function_name"] for t in targets}
    assert "big_enough" in names
    assert "tiny" not in names
    assert "small" not in names


def test_find_mutation_targets_unsupported_language(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        find_mutation_targets(str(tmp_path), "cobol")


def test_find_mutation_targets_max_files(tmp_path: Path) -> None:
    for i in range(10):
        f = tmp_path / f"mod{i}.py"
        f.write_text(textwrap.dedent(f"""\
            def func_{i}():
                value = {i}
                if value < 0:
                    raise ValueError("negative")
                result = value * 2
                cleaned = str(result)
                validated = int(cleaned)
                return validated
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

    # First prompt is _bug_to_symptom (may include file path for domain anchoring);
    # second is the issue generation — must NOT contain file paths or function names
    assert len(captured_prompts) >= 1
    for p in captured_prompts[1:]:
        assert "src/internal/processor.py" not in p
        assert "process_data" not in p
    assert result
    assert "src/internal/processor.py" not in result
    assert "process_data" not in result


def test_generate_issue_from_symptom_no_bugspec() -> None:
    """Without test_output, generate_issue_from_symptom returns symptom-based fallback."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    result = asyncio.run(generate_issue_from_symptom(
        symptom="time duration handling uses wrong units",
        repo_context={"version": "2.0", "lang_version": "3.11", "os_info": "Ubuntu 22.04"},
    ))
    assert "time duration handling" in result


def test_generate_issue_from_symptom_with_style_examples() -> None:
    """Without test_output, style_examples are ignored and symptom fallback is returned."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    result = asyncio.run(generate_issue_from_symptom(
        symptom="parsing breaks on unicode input",
        style_examples=["Fix config loading for nested keys", "Handle empty input gracefully"],
    ))
    assert "parsing breaks" in result


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
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    existing_test = "import pytest\n\ndef test_add_basic():\n    assert add(1, 2) == 3\n"
    (tmp_path / "tests" / "test_calc.py").write_text(existing_test)

    modified_test = "import pytest\n\ndef test_add_basic():\n    assert add(1, 2) == 3\n    assert add(-1, -2) == -3\n"

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
    assert "+    assert add(-1, -2) == -3" in result


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
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

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

    # Only _bug_to_symptom is called — issue generation no longer uses LLM
    assert len(captured_prompts) >= 1
    symptom_prompt = captured_prompts[0]
    assert "user-facing symptom" in symptom_prompt


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
    simple.write_text(textwrap.dedent("""\
        def add(a, b):
            x = a
            y = b
            total = x + y
            doubled = total * 2
            halved = doubled // 2
            result = halved
            return result
    """))
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


def test_find_test_file_importing_prefers_specific_over_parent(tmp_path: Path) -> None:
    """Specific module import is preferred even when a parent-only match sorts first."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_async.py").write_text(
        "from flask import Flask\n\ndef test_app(): pass\n"
    )
    (tmp_path / "tests" / "test_basic.py").write_text(
        "from flask.debughelpers import DebugFilesKeyError\n\ndef test_debug(): pass\n"
    )
    result = _find_test_file_importing(tmp_path, "flask.debughelpers")
    assert result == "tests/test_basic.py"


def test_find_test_file_importing_falls_back_to_parent(tmp_path: Path) -> None:
    """When no specific import exists, falls back to parent package match."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_views.py").write_text(
        "from flask import Flask, request\n\ndef test_request(): pass\n"
    )
    result = _find_test_file_importing(tmp_path, "flask.debughelpers")
    assert result == "tests/test_views.py"


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
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

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

    # Checkout clean commit so baseline runs on correct code
    subprocess.run(["git", "checkout", "HEAD~1"], cwd=tmp_path, capture_output=True, check=True)

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

def test_generate_issue_from_symptom_no_llm_without_test_output() -> None:
    """Without test_output, no LLM is called — symptom fallback is returned."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    result = asyncio.run(generate_issue_from_symptom(
        symptom="parsing breaks on unicode",
    ))
    assert "parsing breaks" in result
    assert "```" in result


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
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

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
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

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
    assert _humanize_traceback(None, str(tmp_path)) == ""  # type: ignore[arg-type]


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

def test_build_social_context_produces_output() -> None:
    """_build_social_context produces social references from artifacts."""
    artifacts = {
        "contributors": ["Alice"],
        "shas": ["abc1234"],
        "issues": ["42"],
        "branches": ["main", "develop"],
    }
    results = [_build_social_context(artifacts) for _ in range(100)]
    non_empty = [r for r in results if r]
    assert len(non_empty) > 0, "should produce non-empty output sometimes"
    for r in non_empty:
        assert any(s in r for s in ['abc1234', '@Alice', '#42'])


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
# _bug_to_symptom with file_path parameter
# ---------------------------------------------------------------------------

def test_bug_to_symptom_includes_file_context() -> None:
    """When file_path is provided, the prompt anchors the symptom to that module."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    import swebenchify.synthesizer as _synth

    captured_prompts: list[str] = []
    _RM = _synth.ResultMessage

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        msg = MagicMock(spec=_RM)
        msg.content = [type("B", (), {"text": "logging breaks under heavy load"})()]
        yield msg

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        result = asyncio.run(_synth._bug_to_symptom(
            "wrong operator in log formatter",
            file_path="src/flask/logging.py",
        ))

    assert len(captured_prompts) == 1
    assert "logging" in captured_prompts[0]
    assert "src/flask/logging.py" in captured_prompts[0]
    assert result == "logging breaks under heavy load"


def test_bug_to_symptom_no_file_path() -> None:
    """Without file_path, no file context appears in the prompt."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    import swebenchify.synthesizer as _synth

    captured_prompts: list[str] = []
    _RM = _synth.ResultMessage

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        msg = MagicMock(spec=_RM)
        msg.content = [type("B", (), {"text": "broken parsing"})()]
        yield msg

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio
        result = asyncio.run(_synth._bug_to_symptom("wrong operator in parser"))

    assert len(captured_prompts) == 1
    assert "module" not in captured_prompts[0].lower() or "module" in "wrong operator in parser"
    assert result == "broken parsing"


# ---------------------------------------------------------------------------
# H1: generate_issue_from_symptom with test_output (data-first path)
# ---------------------------------------------------------------------------

def test_generate_issue_from_symptom_data_first() -> None:
    """When test_output is provided, the issue contains the traceback text."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        class FakeResult:
            content = [type("B", (), {"text": "Broken parsing\n\nThis is completely broken."})()]
        yield FakeResult()

    real_test_output = (
        "FAILED tests/test_parse.py::test_decode - UnicodeDecodeError: 'utf-8' codec\n"
        "E       UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff\n"
        "tests/test_parse.py:42: UnicodeDecodeError\n"
        "======================== 1 failed, 10 passed ========================\n"
        "Extra padding to ensure output exceeds 200 chars. " * 3
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()), \
         mock_patch("swebenchify.synthesizer.ResultMessage", type("FR", (), {})):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="parsing fails on unicode",
            test_output=real_test_output,
            repo_context={"version": "2.0", "lang_version": "3.11", "os_info": "Ubuntu 22.04"},
        ))

    assert "UnicodeDecodeError" in result
    assert "```" in result
    assert "##" not in result


def test_generate_issue_from_symptom_data_first_fallback() -> None:
    """Data-first path produces reasonable output even when LLM fails."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    real_test_output = (
        "FAILED tests/test_core.py::test_add\n"
        "E       AssertionError: expected 3 got -1\n"
        "E       assert add(1, 2) == 3\n"
        "tests/test_core.py:15: AssertionError\n"
        "======================== 1 failed ========================\n"
        "Extra padding to ensure output exceeds 200 chars. " * 3
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="broken feature",
            test_output=real_test_output,
        ))

    assert "AssertionError" in result
    assert "```" in result


def test_generate_issue_from_symptom_with_social_context() -> None:
    """Social context is appended when test_output is provided."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    test_output = (
        "FAILED tests/test_foo.py::test_bar\n"
        "E       AssertionError: expected 1 got 0\n"
        "tests/test_foo.py:10: AssertionError\n"
        "=================== 1 failed ===================\n"
        "Extra padding to ensure output exceeds 200 chars. " * 3
    )
    result = asyncio.run(generate_issue_from_symptom(
        symptom="broken feature",
        test_output=test_output,
        social_context="\n\nMight be related to #42",
    ))
    assert "#42" in result


def test_generate_issue_from_symptom_no_llm_for_symptom_only() -> None:
    """Without test_output, result contains symptom in a code block."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    result = asyncio.run(generate_issue_from_symptom(
        symptom="test symptom",
    ))
    assert "test symptom" in result
    assert "```" in result


# ---------------------------------------------------------------------------
# H3: Patch floor thresholds
# ---------------------------------------------------------------------------

def test_patch_floor_accepts_5_lines_500_chars() -> None:
    """Verify new thresholds: 2 changed lines, 100 chars."""
    import inspect

    import swebenchify.synthesizer as mod
    source = inspect.getsource(mod.synthesize_repo)
    assert "changed >= 2" in source
    assert 'len(patch) >= 100' in source


def test_patch_floor_log_messages_updated() -> None:
    """Verify log messages reflect new thresholds."""
    import inspect

    import swebenchify.synthesizer as mod
    source = inspect.getsource(mod.synthesize_repo)
    assert 'changed lines < 2' in source
    assert 'chars < 100' in source


# ---------------------------------------------------------------------------
# Exp-11: _run_tests_on_buggy_code — pip install before test run
# ---------------------------------------------------------------------------

def test_ensure_venv_creates_venv_for_python(tmp_path: Path) -> None:
    """_ensure_venv creates a venv with pip install -e . for Python repos."""
    import subprocess
    from unittest.mock import patch as mock_patch

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup(name='testpkg')\n")
    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    original_run = subprocess.run
    all_calls: list = []

    def tracking_run(cmd, **kwargs):
        if cmd:
            all_calls.append(cmd)
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        _ensure_venv(str(tmp_path), "python")

    assert any(len(c) >= 3 and c[1:3] == ["-m", "venv"] for c in all_calls), "Expected venv creation"
    assert any("install" in str(c) and "-e" in str(c) for c in all_calls), "Expected pip install in venv"


def test_ensure_venv_noop_for_non_python(tmp_path: Path) -> None:
    """_ensure_venv returns None for non-Python languages."""
    assert _ensure_venv(str(tmp_path), "go") is None
    assert _ensure_venv(str(tmp_path), "rust") is None
    assert _ensure_venv(str(tmp_path), "java") is None


# ---------------------------------------------------------------------------
# Exp-11: _is_valid_test_output
# ---------------------------------------------------------------------------

def test_is_valid_test_output_module_not_found_error() -> None:
    output = (
        "ModuleNotFoundError: No module named 'flask'\n"
        "During handling of the above exception, another exception occurred."
    )
    assert _is_valid_test_output(output) is False


def test_is_valid_test_output_short_output() -> None:
    output = "ERROR: no tests ran\nexit code: 1"
    assert len(output.strip()) < 100
    assert _is_valid_test_output(output) is False


def test_is_valid_test_output_real_failure() -> None:
    output = (
        "FAILED tests/test_core.py::test_add\n"
        "E       AssertionError: assert -1 == 3\n"
        "E       + where -1 = add(1, 2)\n"
        "tests/test_core.py:5: AssertionError\n"
        "======================== 1 failed, 4 passed ========================\n"
        "Some extra padding to make it over 200 chars. " * 5
    )
    assert _is_valid_test_output(output) is True


def test_is_valid_test_output_import_error_without_failure() -> None:
    output = (
        "ImportError: cannot import name 'missing_func' from 'mypackage'\n"
        "During handling...\n"
        "Some extra padding to make it over 200 chars. " * 5
    )
    assert _is_valid_test_output(output) is False


def test_is_valid_test_output_import_error_with_failure() -> None:
    """ImportError is OK if there are also real FAILED markers."""
    output = (
        "ImportError: cannot import name 'func'\n"
        "FAILED tests/test_core.py::test_import\n"
        "Some extra padding to make it over 200 chars. " * 5
    )
    assert _is_valid_test_output(output) is True


def test_is_valid_test_output_all_pass() -> None:
    """Output with no failure signals (all tests pass) is rejected."""
    output = (
        "tests/test_core.py::test_add PASSED\n"
        "tests/test_core.py::test_sub PASSED\n"
        "tests/test_core.py::test_mul PASSED\n"
        "======================== 10 passed in 1.23s ========================\n"
        "Some extra padding to make it over 200 chars. " * 5
    )
    assert _is_valid_test_output(output) is False


# ---------------------------------------------------------------------------
# Exp-11: generate_issue_from_symptom — broken test_output triggers fallback
# ---------------------------------------------------------------------------

def test_generate_issue_from_symptom_module_not_found_fallback() -> None:
    """ModuleNotFoundError in test_output triggers LLM-only fallback."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    broken_output = "ModuleNotFoundError: No module named 'flask'"

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="debug warning inverted",
            test_output=broken_output,
        ))

    assert "ModuleNotFoundError" not in result
    assert "flask" not in result


def test_generate_issue_from_symptom_short_output_fallback() -> None:
    """Short test output (< 200 chars) triggers LLM-only fallback."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="broken feature",
            test_output="exit code 1",
        ))

    assert "exit code 1" not in result


def test_generate_issue_from_symptom_real_failure_uses_data_first() -> None:
    """Real test failure output uses the data-first path."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    async def fake_query(prompt: str, options: object = None):
        return
        yield

    real_output = (
        "FAILED tests/test_core.py::test_add\n"
        "E       AssertionError: assert -1 == 3\n"
        "E       + where -1 = add(1, 2)\n"
        "tests/test_core.py:5: AssertionError\n"
        "======================== 1 failed, 4 passed ========================\n"
        "Some extra padding to get over 200 chars. " * 5
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="calculation returns wrong value",
            test_output=real_output,
        ))

    assert "FAILED" in result
    assert "AssertionError" in result
    assert "```" in result


# ---------------------------------------------------------------------------
# Exp-12: _run_tests_on_buggy_code — PYTHONPATH and pip install fallback
# ---------------------------------------------------------------------------

def test_run_tests_on_buggy_code_sets_pythonpath(tmp_path: Path) -> None:
    """PYTHONPATH is set when running tests so repo source is importable."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    from unittest.mock import patch as mock_patch

    original_run = subprocess.run
    env_used: dict = {}

    def tracking_run(cmd, **kwargs):
        if isinstance(cmd, list) and "pytest" in str(cmd):
            env_used.update(kwargs.get("env", {}))
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")

    assert "PYTHONPATH" in env_used
    assert str(tmp_path) in env_used["PYTHONPATH"]


def test_run_tests_on_buggy_code_pythonpath_src_layout(tmp_path: Path) -> None:
    """When repo has src/ directory, PYTHONPATH includes src/ first."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "src" / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    from unittest.mock import patch as mock_patch

    original_run = subprocess.run
    env_used: dict = {}

    def tracking_run(cmd, **kwargs):
        if isinstance(cmd, list) and "pytest" in str(cmd):
            env_used.update(kwargs.get("env", {}))
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")

    assert "PYTHONPATH" in env_used
    pythonpath = env_used["PYTHONPATH"]
    parts = pythonpath.split(os.pathsep)
    src_path = str(tmp_path / "src")
    assert src_path in parts
    assert str(tmp_path) in parts
    assert parts.index(src_path) < parts.index(str(tmp_path))


def test_ensure_venv_graceful_failure(tmp_path: Path) -> None:
    """_ensure_venv returns None when pip install fails, without crashing."""
    import subprocess
    from unittest.mock import patch as mock_patch

    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup(name='testpkg')\n")

    original_run = subprocess.run

    def failing_run(cmd, **kwargs):
        if isinstance(cmd, list) and "install" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=failing_run):
        result = _ensure_venv(str(tmp_path), "python")

    assert result is None


# ---------------------------------------------------------------------------
# Exp-13: _load_dataset_examples
# ---------------------------------------------------------------------------

def test_load_dataset_examples_with_matching_repo(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    import json
    lines = [
        json.dumps({"repo": "pallets/flask", "problem_statement": "Setting error handler for unknown code fails"}),
        json.dumps({"repo": "pallets/flask", "problem_statement": "JSONEncoder encodes aware datetime incorrectly"}),
        json.dumps({"repo": "pallets/flask", "problem_statement": "Don't overwrite Vary header for cookie access"}),
        json.dumps({"repo": "other/repo", "problem_statement": "Unrelated issue"}),
    ]
    dataset.write_text("\n".join(lines) + "\n")

    examples = _load_dataset_examples(str(dataset), "pallets/flask", n=5)
    assert len(examples) == 3
    assert all("flask" not in ex or "pallets" not in ex for ex in examples)
    assert "Unrelated issue" not in examples


def test_load_dataset_examples_samples_n(tmp_path: Path) -> None:
    import json
    dataset = tmp_path / "dataset.jsonl"
    lines = [
        json.dumps({"repo": "org/repo", "problem_statement": f"Issue {i}"})
        for i in range(20)
    ]
    dataset.write_text("\n".join(lines) + "\n")

    examples = _load_dataset_examples(str(dataset), "org/repo", n=3)
    assert len(examples) == 3


def test_load_dataset_examples_missing_file() -> None:
    examples = _load_dataset_examples("/nonexistent/path/dataset.jsonl", "pallets/flask")
    assert examples == []


def test_load_dataset_examples_no_matching_repo(tmp_path: Path) -> None:
    import json
    dataset = tmp_path / "dataset.jsonl"
    lines = [
        json.dumps({"repo": "other/repo", "problem_statement": "Some issue"}),
    ]
    dataset.write_text("\n".join(lines) + "\n")

    examples = _load_dataset_examples(str(dataset), "pallets/flask")
    assert examples == []


def test_load_dataset_examples_handles_malformed_json(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    import json
    content = (
        "not valid json\n"
        + json.dumps({"repo": "org/repo", "problem_statement": "Valid issue"}) + "\n"
        + "{broken\n"
    )
    dataset.write_text(content)

    examples = _load_dataset_examples(str(dataset), "org/repo")
    assert len(examples) == 1
    assert examples[0] == "Valid issue"


# ---------------------------------------------------------------------------
# Exp-13: generate_issue_from_symptom with dataset_examples (few-shot path)
# ---------------------------------------------------------------------------

def test_generate_issue_from_symptom_dataset_examples_ignored() -> None:
    """dataset_examples are ignored since LLM is no longer used for issues."""
    import asyncio

    from swebenchify.synthesizer import generate_issue_from_symptom
    result = asyncio.run(generate_issue_from_symptom(
        symptom="parsing breaks on unicode",
        dataset_examples=["Example issue text"],
    ))
    assert "parsing breaks" in result


def test_generate_issue_from_symptom_few_shot_not_used_for_data_first() -> None:
    """The data-first path (with test_output) is unchanged by dataset_examples."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    real_test_output = (
        "FAILED tests/test_core.py::test_add\n"
        "E       AssertionError: assert -1 == 3\n"
        "tests/test_core.py:5: AssertionError\n"
        "======================== 1 failed ========================\n"
        "Extra padding to ensure output exceeds 200 chars. " * 3
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="calculation fails",
            test_output=real_test_output,
            dataset_examples=["Example issue 1", "Example issue 2"],
        ))

    assert "FAILED" in result
    assert "AssertionError" in result
    assert "```" in result


# ---------------------------------------------------------------------------
# Exp-14: sys.executable for pip install
# ---------------------------------------------------------------------------

def test_pip_install_uses_sys_executable() -> None:
    """Verify pip install commands use sys.executable, not bare 'pip'."""
    import inspect

    import swebenchify.synthesizer as mod
    source = inspect.getsource(mod._run_tests_on_buggy_code)
    assert "sys.executable" in source
    assert '["pip"' not in source


# ---------------------------------------------------------------------------
# Exp-14: sys.executable replaces 'python' in test commands
# ---------------------------------------------------------------------------

def test_test_commands_use_sys_executable(tmp_path: Path) -> None:
    """Verify 'python' in _TEST_COMMANDS is replaced with sys.executable at runtime."""
    import subprocess
    import sys

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    from unittest.mock import patch as mock_patch

    original_run = subprocess.run
    test_cmds: list = []

    def tracking_run(cmd, **kwargs):
        if isinstance(cmd, list) and "pytest" in str(cmd):
            test_cmds.append(cmd)
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")

    assert len(test_cmds) >= 1
    assert test_cmds[0][0] == sys.executable
    assert "python" not in test_cmds[0]


# ---------------------------------------------------------------------------
# Exp-15: _sanitize_test_output
# ---------------------------------------------------------------------------

def test__sanitize_test_output_strips_anthropic_vars() -> None:
    output = (
        "E       AssertionError: assert {'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'claude-haiku-4-5-20251001',\n"
        "E        'ANTHROPIC_API_KEY': 'sk-ant-xxx',\n"
        "E        'HOME': '/home/user'} == {}\n"
        "tests/test_app.py:42: AssertionError"
    )
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "ANTHROPIC_" not in result
    assert "sk-ant-xxx" not in result
    assert "AssertionError" in result


def test__sanitize_test_output_strips_local_paths() -> None:
    output = (
        "  File \"/Users/aaye/Documents/code/project/src/app.py\", line 42\n"
        "  File \"/Users/bob/projects/mylib/core.py\", line 10"
    )
    result = _sanitize_test_output(output, "/Users/aaye/Documents/code/project")
    assert "/Users/aaye/" not in result
    assert "/Users/bob/" not in result
    assert "/home/user/" in result


def test__sanitize_test_output_strips_synth_paths() -> None:
    output = (
        "  File \"/tmp/abc123-synth-test/repo/test_foo.py\", line 5\n"
        "  File \"/tmp/xyz-synth/build/main.py\", line 10\n"
        "  cachedir: /tmp/pytest-synth-factory/.cache\n"
        "  File \"/path/to/remote-factory/run/thing.py\", line 1\n"
        "  File \"/repo/.factory-worktrees/run-abc123/src/app.py\", line 3"
    )
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "synth-test" not in result
    assert "synth/" not in result
    assert "remote-factory" not in result
    assert ".factory-worktrees" not in result
    assert "/tmp/test-env/" in result


def test__sanitize_test_output_strips_factory_env_vars() -> None:
    output = (
        "E       'FACTORY_RUN_ID': 'run-123',\n"
        "E       'CLAUDE_CODE_VERSION': '1.0',\n"
        "E       'SWEBENCHIFY_DATASET': '/path/to/data',\n"
        "E       'PATH': '/usr/bin'\n"
    )
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "FACTORY_" not in result
    assert "CLAUDE_" not in result
    assert "SWEBENCHIFY_" not in result
    assert "PATH" in result


def test__sanitize_test_output_empty_input() -> None:
    assert _sanitize_test_output("", "/tmp/repo") == ""


# ---------------------------------------------------------------------------
# Exp-15: _extract_failed_test_names
# ---------------------------------------------------------------------------

def test__extract_failed_test_names() -> None:
    output = (
        "FAILED tests/test_foo.py::TestBar::test_baz - AssertionError\n"
        "FAILED tests/test_core.py::test_bad_environ_raises_bad_request\n"
        "PASSED tests/test_ok.py::test_success\n"
        "2 failed, 5 passed"
    )
    names = _extract_failed_test_names(output)
    assert "tests/test_foo.py::TestBar::test_baz" in names
    assert "tests/test_core.py::test_bad_environ_raises_bad_request" in names
    assert len(names) == 2


def test__extract_failed_test_names_empty() -> None:
    assert _extract_failed_test_names("") == set()
    assert _extract_failed_test_names("all passed") == set()


# ---------------------------------------------------------------------------
# Exp-15: _run_tests baseline diffing
# ---------------------------------------------------------------------------

def test__run_tests_baseline_diffing(tmp_path: Path) -> None:
    """Pre-existing failures are deselected; only mutation-induced failures appear."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n\n"
        "def test_preexisting_broken():\n    assert False\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial with broken test"], cwd=tmp_path, capture_output=True, check=True)
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", clean_sha], cwd=tmp_path, capture_output=True, check=True)

    output = _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")
    assert output is not None
    assert "test_add" in output
    assert "failed" in output.lower()


def test__baseline_diffing_no_substring_collision(tmp_path: Path) -> None:
    """Pre-existing failure is deselected; mutation-induced failure still runs."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add, multiply\n\n"
        "def test_preexisting_broken():\n    assert False\n\n"
        "def test_multiply():\n    assert multiply(2, 3) == 6\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return 0\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy multiply"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", clean_sha], cwd=tmp_path, capture_output=True, check=True)

    output = _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")
    assert output is not None
    assert "test_multiply" in output


# ---------------------------------------------------------------------------
# Exp-15: tone calibration
# ---------------------------------------------------------------------------

def test_run_tests_deselects_preexisting_failures(tmp_path: Path) -> None:
    """Pre-existing failures are deselected so only mutation-induced failures appear."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n\n"
        "def test_preexisting_broken():\n    assert False\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial with broken test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", "HEAD~1"], cwd=tmp_path, capture_output=True, check=True)

    from unittest.mock import patch as mock_patch

    original_run = subprocess.run
    test_cmds_used: list = []

    def tracking_run(cmd, **kwargs):
        if isinstance(cmd, list) and "pytest" in str(cmd) and "--deselect" not in str(cmd) and "--tb=no" not in str(cmd):
            pass
        if isinstance(cmd, list) and "--deselect" in str(cmd):
            test_cmds_used.append(cmd)
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")

    assert any("--deselect" in str(c) for c in test_cmds_used), \
        f"Expected --deselect in test commands, got: {test_cmds_used}"
    deselect_args = [arg for cmd in test_cmds_used for arg in cmd if "--deselect=" in str(arg)]
    assert any("test_preexisting_broken" in arg for arg in deselect_args)


def test_run_tests_no_deselect_when_baseline_clean(tmp_path: Path) -> None:
    """When baseline has no failures, no --deselect args are added."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_module.py").write_text(
        "from module import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    (tmp_path / "module.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "buggy"], cwd=tmp_path, capture_output=True, check=True)
    buggy_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", "HEAD~1"], cwd=tmp_path, capture_output=True, check=True)

    from unittest.mock import patch as mock_patch

    original_run = subprocess.run
    all_cmds: list = []

    def tracking_run(cmd, **kwargs):
        if isinstance(cmd, list):
            all_cmds.append(cmd)
        return original_run(cmd, **kwargs)

    with mock_patch("swebenchify.synthesizer.subprocess.run", side_effect=tracking_run):
        output = _run_tests_on_buggy_code(str(tmp_path), buggy_sha, "python")

    deselect_cmds = [c for c in all_cmds if "--deselect" in str(c)]
    assert len(deselect_cmds) == 0
    assert output is not None
    assert "FAILED" in output or "assert" in output.lower()


def test_data_first_uses_narrative_rewrite_with_fallback() -> None:
    """Data-first path calls LLM for narrative rewrite, falls back to programmatic draft."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    real_test_output = (
        "FAILED tests/test_core.py::test_add\n"
        "E       AssertionError: assert -1 == 3\n"
        "tests/test_core.py:5: AssertionError\n"
        "======================== 1 failed ========================\n"
        "Extra padding to ensure output exceeds 200 chars. " * 3
    )

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import generate_issue_from_symptom
        result = asyncio.run(generate_issue_from_symptom(
            symptom="calculation fails",
            test_output=real_test_output,
        ))

    assert len(captured_prompts) == 1
    assert "terse GitHub issue" in captured_prompts[0]
    assert "AssertionError" in result
    assert "```" in result
    assert "##" not in result


# ---------------------------------------------------------------------------
# Exp-21: _count_test_functions
# ---------------------------------------------------------------------------

def test_count_test_functions_counts_correctly() -> None:
    code = textwrap.dedent("""\
        import pytest

        def helper():
            return 42

        def test_add():
            assert 1 + 1 == 2

        def test_subtract():
            assert 2 - 1 == 1

        class TestGroup:
            def test_multiply(self):
                assert 2 * 3 == 6
    """)
    assert _count_test_functions(code) == 3


def test_count_test_functions_empty() -> None:
    assert _count_test_functions("") == 0
    assert _count_test_functions("def helper():\n    pass\n") == 0


# ---------------------------------------------------------------------------
# Exp-21: test patch rejects missing function def in LLM response
# ---------------------------------------------------------------------------

def test_test_patch_rejects_missing_function_def(tmp_path: Path) -> None:
    """When the LLM response lacks the function definition, the patch is rejected."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    existing_test = "import pytest\n\ndef test_add_basic():\n    assert add(1, 2) == 3\n"
    (tmp_path / "tests" / "test_calc.py").write_text(existing_test)

    bad_response = "Here are some assertions you could add."

    class FakeResult:
        content = [type("B", (), {"text": bad_response})()]

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

        from swebenchify.synthesizer import _generate_test_patch_existing
        result = asyncio.run(_generate_test_patch_existing(
            bug_spec, str(tmp_path), "tests/test_calc.py", "python", "sonnet",
        ))

    assert result is None


def test_test_patch_accepts_modified_existing_functions(tmp_path: Path) -> None:
    """When the LLM returns a modified function, the patch is accepted."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    existing_test = "import pytest\n\ndef test_add_basic():\n    assert add(1, 2) == 3\n"
    (tmp_path / "tests" / "test_calc.py").write_text(existing_test)

    modified_func = "def test_add_basic():\n    assert add(1, 2) == 3\n    assert add(0, 0) == 0\n"

    class FakeResult:
        content = [type("B", (), {"text": f"```python\n{modified_func}\n```"})()]

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

        from swebenchify.synthesizer import _generate_test_patch_existing
        result = asyncio.run(_generate_test_patch_existing(
            bug_spec, str(tmp_path), "tests/test_calc.py", "python", "sonnet",
        ))

    assert result is not None
    assert "tests/test_calc.py" in result
    assert "+    assert add(0, 0) == 0" in result


# ---------------------------------------------------------------------------
# Exp-21: test generation prompt sends only the function, not the whole file
# ---------------------------------------------------------------------------

def test_test_generation_prompt_function_level() -> None:
    """Verify the prompt sends only the target function and uses HARD CONSTRAINT."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mock_patch

    captured_prompts: list[str] = []

    async def fake_query(prompt: str, options: object = None):
        captured_prompts.append(prompt)
        return
        yield

    bug_spec = BugSpec(
        file="src/calc.py",
        function_name="add",
        original_code="def add(a, b):\n    return a + b",
        buggy_code="def add(a, b):\n    return a - b",
        bug_description="Changed + to -",
        bug_category="incorrect-operator",
    )

    (tmp_dir := Path("/tmp/test_prompt_check")).mkdir(exist_ok=True)
    test_file = tmp_dir / "test_calc.py"
    test_file.write_text("def test_add():\n    assert add(1, 2) == 3\n")

    with mock_patch("swebenchify.synthesizer.query", fake_query), \
         mock_patch("swebenchify.synthesizer.ClaudeCodeOptions", MagicMock()):
        import asyncio

        from swebenchify.synthesizer import _generate_test_patch_existing
        asyncio.run(_generate_test_patch_existing(
            bug_spec, str(tmp_dir), "test_calc.py", "python", "sonnet",
        ))

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "HARD CONSTRAINT" in prompt
    assert "Return ONLY the modified test function" in prompt
    assert "Do NOT return the complete file" in prompt
    assert "def test_add" in prompt


# ---------------------------------------------------------------------------
# _align_indentation
# ---------------------------------------------------------------------------

def test_align_indentation_fixes_mismatch() -> None:
    original = "    def foo():\n        return 1"
    buggy = "def foo():\n    return 2"
    result = _align_indentation(original, buggy)
    assert result == "    def foo():\n        return 2"


def test_align_indentation_noop_when_matching() -> None:
    original = "    def foo():\n        return 1\n"
    buggy = "    def foo():\n        return 2\n"
    result = _align_indentation(original, buggy)
    assert result == buggy


def test_align_indentation_empty_code() -> None:
    assert _align_indentation("", "def foo(): pass") == "def foo(): pass"
    assert _align_indentation("def foo(): pass", "") == ""


def test_align_indentation_normalizes_blank_lines() -> None:
    original = "    def foo():\n        x = 1\n\n        return x"
    buggy = "def foo():\n    x = 2\n    \n    return x"
    result = _align_indentation(original, buggy)
    lines = result.split('\n')
    assert lines[2] == ''


def test_synthesize_repo_skips_candidate_without_test_failures() -> None:
    """Candidates without valid test output are skipped (data-first path required)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    target = {
        "file": "src/foo.py",
        "function_name": "bar",
        "source": "def bar():\n    return 1\n",
        "start_line": 1,
        "end_line": 2,
        "language": "python",
    }

    from swebenchify.synthesizer import synthesize_repo

    with (
        patch("swebenchify.synthesizer.find_mutation_targets", return_value=[target]),
        patch("swebenchify.synthesizer._find_existing_test_file", return_value="tests/test_foo.py"),
        patch("swebenchify.synthesizer._find_related_files", return_value=[]),
        patch("swebenchify.synthesizer._plan_multi_file_mutation", new_callable=AsyncMock, return_value=BugPlan(primary_description="change return value")),
        patch("swebenchify.synthesizer.introduce_bug", new_callable=AsyncMock, return_value=BugSpec(
            file="src/foo.py",
            function_name="bar",
            original_code="def bar():\n    return 1\n",
            buggy_code="def bar():\n    return 0\n",
            bug_description="returns wrong value",
            bug_category="logic",
        )),
        patch("swebenchify.synthesizer._create_buggy_commit_multi", return_value="abc123"),
        patch("swebenchify.synthesizer._run_tests_on_buggy_code", return_value=None),
        patch("swebenchify.synthesizer._load_dataset_examples", return_value=[]),
    ):
        result = asyncio.run(synthesize_repo(
            repo_path="/tmp/fake",
            repo_slug="test/repo",
            base_commit="abc123",
            language="python",
            max_mutations=1,
        ))
        assert isinstance(result, RepoSynthesisResult)
        assert len(result.candidates) == 0
        assert result.mutations_attempted >= 1


def test_repo_synthesis_result_dataclass() -> None:
    """RepoSynthesisResult stores candidates and mutation attempt count."""
    r = RepoSynthesisResult(candidates=[], mutations_attempted=10)
    assert r.candidates == []
    assert r.mutations_attempted == 10

    r2 = RepoSynthesisResult(candidates=[], mutations_attempted=0)
    assert r2.mutations_attempted == 0


# ---------------------------------------------------------------------------
# _preserve_unchanged_lines
# ---------------------------------------------------------------------------

def test_preserve_unchanged_lines_fixes_trailing_spaces() -> None:
    """Lines with identical stripped content but trailing whitespace are restored."""
    original = "def foo():\n    return 1\n    x = 2"
    buggy = "def foo():  \n    return 1  \n    x = 3"
    result = _preserve_unchanged_lines(original, buggy)
    lines = result.splitlines()
    assert lines[0] == "def foo():"
    assert lines[1] == "    return 1"
    assert lines[2] == "    x = 3"


def test_preserve_unchanged_lines_fixes_tab_space_mixing() -> None:
    """Lines where tabs were swapped for spaces are restored from original."""
    original = "\treturn 1\n\tx = 2"
    buggy = "    return 1\n    x = 3"
    result = _preserve_unchanged_lines(original, buggy)
    lines = result.splitlines()
    assert lines[0] == "\treturn 1"
    assert lines[1] == "    x = 3"


def test_preserve_unchanged_lines_no_change_needed() -> None:
    """When buggy code already matches original whitespace, nothing changes."""
    original = "def foo():\n    return 1"
    buggy = "def foo():\n    return 2"
    result = _preserve_unchanged_lines(original, buggy)
    lines = result.splitlines()
    assert lines[0] == "def foo():"
    assert lines[1] == "    return 2"


def test_preserve_unchanged_lines_identical() -> None:
    """Identical code is returned unchanged."""
    code = "def foo():\n    return 1"
    assert _preserve_unchanged_lines(code, code) == code


def test_preserve_unchanged_lines_empty() -> None:
    """Empty inputs are handled gracefully."""
    assert _preserve_unchanged_lines("", "") == ""


# ---------------------------------------------------------------------------
# Info-leak sanitization — judge evasion
# ---------------------------------------------------------------------------

def test__sanitize_test_output_strips_homebrew_go_paths() -> None:
    output = '  File "/opt/homebrew/Cellar/go/1.26.4/libexec/src/testing/testing.go", line 42'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "/opt/homebrew/Cellar/go/" not in result
    assert "/usr/local/go/" in result


def test__sanitize_test_output_strips_homebrew_rust_paths() -> None:
    output = '  File "/opt/homebrew/Cellar/rust/1.75.0/lib/rustlib/src/rust/library/core/src/result.rs"'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "/opt/homebrew/Cellar/rust/" not in result
    assert "/usr/local/lib/rust/" in result


def test__sanitize_test_output_strips_var_folders_paths() -> None:
    output = '  File "/var/folders/xh/abc123def/T/go-build456/test_main.go", line 10'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "/var/folders/" not in result
    assert "/tmp/test-env/" in result


def test__sanitize_test_output_replaces_impossible_go_versions() -> None:
    output = 'go/1.26.4/libexec/src/testing/testing.go:1234'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "1.26.4" not in result
    assert "go/1.23.4" in result


def test__sanitize_test_output_replaces_future_go_versions() -> None:
    output = 'go/1.35.1/libexec/src/runtime/panic.go:100'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "1.35.1" not in result
    assert "go/1.23.4" in result


def test__sanitize_test_output_keeps_valid_go_versions() -> None:
    output = 'go/1.22.5/libexec/src/testing/testing.go:1234'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "go/1.22.5" in result


def test__sanitize_test_output_strips_private_prefix() -> None:
    output = '  File "/private/home/mike/projects/grpc-go/rpc_util_test.go", line 5'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "/private/" not in result


def test__sanitize_test_output_strips_synth_keywords_in_paths() -> None:
    output = '  File "/home/mike/projects/grpc-go-synth-test/rpc_util_test.go", line 5'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "synth-test" not in result
    assert "synth_test" not in result


def test__sanitize_test_output_strips_synth_bench_in_paths() -> None:
    output = '  File "/home/user/synth_bench/main.go", line 1'
    result = _sanitize_test_output(output, "/tmp/repo")
    assert "synth_bench" not in result
    assert "synth-bench" not in result


def test_humanize_traceback_handles_private_tmp(tmp_path: Path) -> None:
    test_output = (
        '  File "/private/tmp/pytest-abc123/test_core.py", line 5\n'
        "    assert add(1, 2) == 3\n"
        "AssertionError: -1 != 3"
    )
    result = _humanize_traceback(test_output, str(tmp_path))
    assert "/private/tmp/" not in result
    assert "/home/" in result
    assert "AssertionError" in result


def test_humanize_traceback_strips_synth_from_repo_name() -> None:
    test_output = '  File "/tmp/pytest-abc/test_core.py", line 5\n    assert add(1, 2) == 3'
    result = _humanize_traceback(
        test_output,
        "/home/user/grpc-go-synth-test",
    )
    assert "synth" not in result.lower()
    assert "grpc-go" in result


def test_humanize_traceback_strips_factory_from_repo_name() -> None:
    test_output = '  File "/tmp/pytest-abc/test_core.py", line 5\n    assert add(1, 2) == 3'
    result = _humanize_traceback(
        test_output,
        "/home/user/grpc-go-factory-run",
    )
    assert "factory" not in result.lower()


def test_humanize_traceback_empty_repo_name_after_strip() -> None:
    test_output = '  File "/tmp/pytest-abc/test_core.py", line 5\n    assert add(1, 2) == 3'
    result = _humanize_traceback(
        test_output,
        "/home/user/synth-test",
    )
    assert "project" in result


def test_humanize_traceback_handles_var_folders(tmp_path: Path) -> None:
    test_output = (
        '  File "/var/folders/xh/abc123/T/go-build456/test_main.go", line 10\n'
        "    assert result == expected"
    )
    result = _humanize_traceback(test_output, str(tmp_path))
    assert "/var/folders/" not in result
    assert "/home/" in result


# ---------------------------------------------------------------------------
# H10: Targeted mutation — test assertion analysis & mutation
# ---------------------------------------------------------------------------


class TestExtractCalledFunc:
    """Tests for _extract_called_func."""

    def test_simple_call(self) -> None:
        assert _extract_called_func("calculate(x, y)") == "calculate"

    def test_method_call(self) -> None:
        assert _extract_called_func("obj.process(data)") == "process"

    def test_builtin_skipped(self) -> None:
        assert _extract_called_func("len(items)") == "len"

    def test_builtin_then_custom(self) -> None:
        assert _extract_called_func("len(get_items())") == "get_items"

    def test_no_call(self) -> None:
        assert _extract_called_func("x + y") is None


class TestAnalyzeTestAssertions:
    """Tests for _analyze_test_assertions."""

    def test_assert_equal(self) -> None:
        src = "def test_add():\n    assert add(2, 3) == 5\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "equality"
        assert "add" in result[0]["expression"]
        assert result[0]["expected"] == "5"
        assert result[0]["called_function"] == "add"

    def test_unittest_assertEqual(self) -> None:
        src = (
            "class TestCalc(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "equality"
        assert result[0]["called_function"] == "add"

    def test_assert_raises(self) -> None:
        src = (
            "class TestCalc(unittest.TestCase):\n"
            "    def test_invalid(self):\n"
            "        self.assertRaises(ValueError, validate, -1)\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "raises"
        assert result[0]["expected"] == "ValueError"
        assert result[0]["called_function"] == "validate"

    def test_pytest_raises(self) -> None:
        src = (
            "def test_invalid():\n"
            "    with pytest.raises(ValueError):\n"
            "        validate(-1)\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "raises"
        assert result[0]["expected"] == "ValueError"
        assert result[0]["called_function"] == "validate"

    def test_assert_is_none(self) -> None:
        src = "def test_empty():\n    assert get_value() is None\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "is_none"
        assert result[0]["called_function"] == "get_value"

    def test_assert_is_not_none(self) -> None:
        src = "def test_exists():\n    assert find_item(x) is not None\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "not_none"
        assert result[0]["called_function"] == "find_item"

    def test_assert_in(self) -> None:
        src = "def test_contains():\n    assert 'hello' in get_words()\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "in"
        assert result[0]["called_function"] == "get_words"

    def test_assert_true(self) -> None:
        src = (
            "class TestCalc(unittest.TestCase):\n"
            "    def test_positive(self):\n"
            "        self.assertTrue(is_valid(42))\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "truthy"
        assert result[0]["called_function"] == "is_valid"

    def test_assert_false(self) -> None:
        src = (
            "class TestCalc(unittest.TestCase):\n"
            "    def test_negative(self):\n"
            "        self.assertFalse(is_valid(-1))\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "falsy"
        assert result[0]["called_function"] == "is_valid"

    def test_non_python_returns_empty(self) -> None:
        src = "func TestAdd(t *testing.T) {}\n"
        result = _analyze_test_assertions(src, "go")
        assert result == []

    def test_multiple_assertions(self) -> None:
        src = (
            "def test_math():\n"
            "    assert add(1, 2) == 3\n"
            "    assert subtract(5, 2) == 3\n"
            "    assert multiply(2, 3) == 6\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 3
        funcs = [a["called_function"] for a in result]
        assert "add" in funcs
        assert "subtract" in funcs
        assert "multiply" in funcs

    def test_assertIn(self) -> None:
        src = (
            "class TestFoo(unittest.TestCase):\n"
            "    def test_search(self):\n"
            "        self.assertIn('key', get_results())\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "in"
        assert result[0]["called_function"] == "get_results"

    def test_assertIsNone(self) -> None:
        src = (
            "class TestFoo(unittest.TestCase):\n"
            "    def test_empty(self):\n"
            "        self.assertIsNone(lookup('missing'))\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "is_none"
        assert result[0]["called_function"] == "lookup"

    def test_assertIsNotNone(self) -> None:
        src = (
            "class TestFoo(unittest.TestCase):\n"
            "    def test_present(self):\n"
            "        self.assertIsNotNone(lookup('key'))\n"
        )
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "not_none"
        assert result[0]["called_function"] == "lookup"

    def test_generic_assert(self) -> None:
        src = "def test_check():\n    assert validate(data)\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "truthy"
        assert result[0]["called_function"] == "validate"

    def test_assert_not(self) -> None:
        src = "def test_check():\n    assert not is_empty(data)\n"
        result = _analyze_test_assertions(src, "python")
        assert len(result) == 1
        assert result[0]["type"] == "falsy"
        assert result[0]["called_function"] == "is_empty"


class TestMutateSwapOperator:
    """Tests for _mutate_swap_operator."""

    def test_swaps_in_return(self) -> None:
        lines = ["def add(a, b):", "    return a + b"]
        result = _mutate_swap_operator(lines)
        assert result is not None
        orig, mutated = result
        assert " + " in orig
        assert " - " in mutated

    def test_swaps_comparison(self) -> None:
        lines = ["def check(x):", "    if x >= 0:", "        return True"]
        result = _mutate_swap_operator(lines)
        assert result is not None
        orig, mutated = result
        assert " >= " in orig
        assert " > " in mutated

    def test_no_operators(self) -> None:
        lines = ["def noop():", "    pass"]
        result = _mutate_swap_operator(lines)
        assert result is None

    def test_skips_def_lines(self) -> None:
        lines = ["def add(a, b):", "    x = 42", "    return x"]
        result = _mutate_swap_operator(lines)
        assert result is None  # no operators in non-def, non-return lines either


class TestMutateRemoveRaise:
    """Tests for _mutate_remove_raise."""

    def test_inverts_guard(self) -> None:
        lines = [
            "def validate(x):",
            "    if x < 0:",
            "        raise ValueError('negative')",
            "    return x",
        ]
        result = _mutate_remove_raise(lines, "ValueError")
        assert result is not None
        orig, mutated = result
        assert "if x < 0:" in orig
        assert "if not x < 0:" in mutated

    def test_removes_standalone_raise(self) -> None:
        lines = [
            "def fail():",
            "    raise RuntimeError('oops')",
        ]
        result = _mutate_remove_raise(lines, "RuntimeError")
        assert result is not None
        orig, mutated = result
        assert "raise " in orig
        assert mutated.strip() == "pass"

    def test_no_matching_raise(self) -> None:
        lines = [
            "def validate(x):",
            "    raise ValueError('negative')",
        ]
        result = _mutate_remove_raise(lines, "TypeError")
        assert result is None


class TestMutateReturnNone:
    """Tests for _mutate_return_none and _mutate_return_non_none."""

    def test_return_none(self) -> None:
        lines = ["def calc():", "    return 42"]
        result = _mutate_return_none(lines)
        assert result is not None
        orig, mutated = result
        assert "return 42" in orig
        assert "return None" in mutated

    def test_already_none(self) -> None:
        lines = ["def calc():", "    return None"]
        result = _mutate_return_none(lines)
        assert result is None

    def test_return_non_none(self) -> None:
        lines = ["def calc():", "    return None"]
        result = _mutate_return_non_none(lines)
        assert result is not None
        orig, mutated = result
        assert "return None" in orig
        assert "return 0" in mutated

    def test_bare_return(self) -> None:
        lines = ["def noop():", "    return"]
        result = _mutate_return_non_none(lines)
        assert result is not None
        _, mutated = result
        assert "return 0" in mutated


class TestTargetedMutation:
    """Tests for _targeted_mutation."""

    def test_equality_assertion_swaps_operator(self) -> None:
        source = "def add(a, b):\n    return a + b\n"
        assertion = {
            "type": "equality",
            "expression": "add(2, 3)",
            "expected": "5",
            "called_function": "add",
            "line": 1,
        }
        result = _targeted_mutation(source, assertion, "python")
        assert result is not None
        orig, mutated = result
        assert " + " in orig
        assert " - " in mutated

    def test_raises_assertion_removes_raise(self) -> None:
        source = (
            "def validate(x):\n"
            "    if x < 0:\n"
            "        raise ValueError('negative')\n"
            "    return x\n"
        )
        assertion = {
            "type": "raises",
            "expression": "validate",
            "expected": "ValueError",
            "called_function": "validate",
            "line": 1,
        }
        result = _targeted_mutation(source, assertion, "python")
        assert result is not None

    def test_is_none_changes_return(self) -> None:
        source = "def empty():\n    return None\n"
        assertion = {
            "type": "is_none",
            "expression": "empty()",
            "expected": "None",
            "called_function": "empty",
            "line": 1,
        }
        result = _targeted_mutation(source, assertion, "python")
        assert result is not None
        _, mutated = result
        assert "return 0" in mutated

    def test_not_none_returns_none(self) -> None:
        source = "def find():\n    return 42\n"
        assertion = {
            "type": "not_none",
            "expression": "find()",
            "expected": "not None",
            "called_function": "find",
            "line": 1,
        }
        result = _targeted_mutation(source, assertion, "python")
        assert result is not None
        _, mutated = result
        assert "return None" in mutated

    def test_non_python_returns_none(self) -> None:
        result = _targeted_mutation("fn main() {}", {}, "rust")
        assert result is None


class TestDescribeTargetedMutation:
    """Tests for _describe_targeted_mutation."""

    def test_operator_swap_description(self) -> None:
        desc = _describe_targeted_mutation(
            "    return a + b", "    return a - b",
            {"type": "equality"},
        )
        assert "+" in desc and "-" in desc

    def test_raise_removal_description(self) -> None:
        desc = _describe_targeted_mutation(
            "        raise ValueError('x')", "        pass",
            {"type": "raises"},
        )
        assert "error" in desc.lower() or "raise" in desc.lower()

    def test_return_none_description(self) -> None:
        desc = _describe_targeted_mutation(
            "    return 42", "    return None",
            {"type": "not_none"},
        )
        assert "None" in desc

    def test_generic_description(self) -> None:
        desc = _describe_targeted_mutation(
            "    x = foo()", "    x = bar()",
            {"type": "equality"},
        )
        assert len(desc) > 10  # some meaningful text


class TestTryTargetedMutation:
    """Tests for _try_targeted_mutation (integration test with temp files)."""

    def test_returns_bugspec_for_matching_test(self, tmp_path: Path) -> None:
        # Source file
        src_dir = tmp_path / "mylib"
        src_dir.mkdir()
        src_file = src_dir / "calc.py"
        src_file.write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n",
        )

        # Test file
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_calc.py"
        test_file.write_text(
            "from mylib.calc import add, subtract\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_subtract():\n"
            "    assert subtract(5, 2) == 3\n",
        )

        target = {
            "file": "mylib/calc.py",
            "function_name": "add",
            "source": "def add(a, b):\n    return a + b",
        }

        result = _try_targeted_mutation(
            str(tmp_path), target, "tests/test_calc.py", "python",
        )
        assert result is not None
        assert isinstance(result, BugSpec)
        assert result.file == "mylib/calc.py"
        assert result.function_name == "add"
        assert result.bug_category == "targeted-mutation"
        assert " - " in result.buggy_code  # + swapped to -

    def test_returns_none_for_no_matching_assertion(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "mylib"
        src_dir.mkdir()
        src_file = src_dir / "calc.py"
        src_file.write_text("def add(a, b):\n    return a + b\n")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_calc.py"
        test_file.write_text(
            "def test_other():\n"
            "    assert other_func() == 42\n",
        )

        target = {
            "file": "mylib/calc.py",
            "function_name": "add",
            "source": "def add(a, b):\n    return a + b",
        }

        result = _try_targeted_mutation(
            str(tmp_path), target, "tests/test_calc.py", "python",
        )
        assert result is None

    def test_returns_none_for_non_python(self, tmp_path: Path) -> None:
        result = _try_targeted_mutation(str(tmp_path), {}, "test.go", "go")
        assert result is None
