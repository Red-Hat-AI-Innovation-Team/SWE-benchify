"""Tests for swebenchify.parsers — TestLogParser protocol and GoJSONParser."""

from __future__ import annotations

import json
import textwrap

import pytest

from swebenchify.parsers import (
    GoJSONParser,
    ParseResult,
    PythonPassthroughParser,
    get_parser,
    register,
)


# ---------------------------------------------------------------------------
# Helpers — build synthetic go test -json output
# ---------------------------------------------------------------------------

def _event(**kwargs) -> str:
    return json.dumps(kwargs)


def _passing_test(pkg: str, test: str, elapsed: float = 0.001) -> list[str]:
    return [
        _event(Action="run",    Package=pkg, Test=test),
        _event(Action="output", Package=pkg, Test=test, Output=f"=== RUN   {test}\n"),
        _event(Action="pass",   Package=pkg, Test=test, Elapsed=elapsed),
    ]


def _failing_test(pkg: str, test: str, elapsed: float = 0.001) -> list[str]:
    return [
        _event(Action="run",    Package=pkg, Test=test),
        _event(Action="output", Package=pkg, Test=test, Output=f"--- FAIL: {test}\n"),
        _event(Action="fail",   Package=pkg, Test=test, Elapsed=elapsed),
    ]


def _skipped_test(pkg: str, test: str) -> list[str]:
    return [
        _event(Action="run",    Package=pkg, Test=test),
        _event(Action="output", Package=pkg, Test=test, Output=f"--- SKIP: {test}\n"),
        _event(Action="skip",   Package=pkg, Test=test, Elapsed=0.0),
    ]


def _package_pass(pkg: str) -> str:
    return _event(Action="pass", Package=pkg, Elapsed=0.1)


def _package_fail(pkg: str) -> str:
    return _event(Action="fail", Package=pkg, Elapsed=0.1)


def _compile_error(pkg: str) -> list[str]:
    """Simulate a build failure: package-level fail with no test events."""
    return [
        _event(Action="output", Package=pkg, Output="# " + pkg + "\n"),
        _event(Action="output", Package=pkg, Output="./main.go:10:5: undefined: Foo\n"),
        _event(Action="build-fail", Package=pkg),
        # go test -json also emits a package-level fail in this case
        _event(Action="fail", Package=pkg, Elapsed=0.0),
    ]


# ---------------------------------------------------------------------------
# GoJSONParser — core parsing
# ---------------------------------------------------------------------------

class TestGoJSONParserPassingTest:
    def test_single_passing_test(self) -> None:
        pkg = "github.com/foo/bar"
        lines = _passing_test(pkg, "TestFoo") + [_package_pass(pkg)]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["compiled"] is True
        assert result["tests"][f"{pkg}.TestFoo"] == "passed"

    def test_multiple_passing_tests(self) -> None:
        pkg = "github.com/foo/bar"
        lines = (
            _passing_test(pkg, "TestA")
            + _passing_test(pkg, "TestB")
            + [_package_pass(pkg)]
        )
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg}.TestA"] == "passed"
        assert result["tests"][f"{pkg}.TestB"] == "passed"


class TestGoJSONParserFailingTest:
    def test_single_failing_test(self) -> None:
        pkg = "github.com/foo/bar"
        lines = _failing_test(pkg, "TestBar") + [_package_fail(pkg)]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["compiled"] is True  # built OK, just a test failure
        assert result["tests"][f"{pkg}.TestBar"] == "failed"

    def test_mixed_pass_and_fail(self) -> None:
        pkg = "github.com/foo/bar"
        lines = (
            _passing_test(pkg, "TestOK")
            + _failing_test(pkg, "TestBad")
            + [_package_fail(pkg)]
        )
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg}.TestOK"] == "passed"
        assert result["tests"][f"{pkg}.TestBad"] == "failed"


class TestGoJSONParserSkippedTest:
    def test_skipped_test(self) -> None:
        pkg = "github.com/foo/bar"
        lines = _skipped_test(pkg, "TestSkip") + [_package_pass(pkg)]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg}.TestSkip"] == "skipped"


class TestGoJSONParserSubtests:
    def test_subtests_are_distinct_entries(self) -> None:
        pkg = "github.com/foo/bar"
        lines = (
            _passing_test(pkg, "TestFoo/case1")
            + _failing_test(pkg, "TestFoo/case2")
            + _passing_test(pkg, "TestFoo")
            + [_package_pass(pkg)]
        )
        result = GoJSONParser().parse("\n".join(lines))
        tests = result["tests"]
        assert tests[f"{pkg}.TestFoo/case1"] == "passed"
        assert tests[f"{pkg}.TestFoo/case2"] == "failed"
        assert tests[f"{pkg}.TestFoo"] == "passed"

    def test_deeply_nested_subtest(self) -> None:
        pkg = "github.com/foo/bar"
        lines = (
            _passing_test(pkg, "TestMatrix/row=1/col=A")
            + [_package_pass(pkg)]
        )
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg}.TestMatrix/row=1/col=A"] == "passed"


class TestGoJSONParserCompileError:
    def test_compile_error_gives_compiled_false(self) -> None:
        pkg = "github.com/foo/bar"
        lines = _compile_error(pkg)
        result = GoJSONParser().parse("\n".join(lines))
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_compile_error_empty_tests_dict(self) -> None:
        pkg = "github.com/foo/bar"
        lines = _compile_error(pkg)
        result = GoJSONParser().parse("\n".join(lines))
        assert len(result["tests"]) == 0

    def test_package_fail_with_tests_is_not_compile_error(self) -> None:
        pkg = "github.com/foo/bar"
        # Package fails but at least one test ran → build succeeded
        lines = _failing_test(pkg, "TestBroken") + [_package_fail(pkg)]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["compiled"] is True


class TestGoJSONParserInterleavedPackages:
    def test_interleaved_parallel_packages(self) -> None:
        pkg_a = "github.com/foo/pkg_a"
        pkg_b = "github.com/foo/pkg_b"
        # Interleave events from two packages
        lines = [
            _event(Action="run", Package=pkg_a, Test="TestA1"),
            _event(Action="run", Package=pkg_b, Test="TestB1"),
            _event(Action="pass", Package=pkg_a, Test="TestA1", Elapsed=0.001),
            _event(Action="fail", Package=pkg_b, Test="TestB1", Elapsed=0.001),
            _event(Action="pass", Package=pkg_a, Elapsed=0.01),
            _event(Action="fail", Package=pkg_b, Elapsed=0.01),
        ]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg_a}.TestA1"] == "passed"
        assert result["tests"][f"{pkg_b}.TestB1"] == "failed"

    def test_results_not_mixed_across_packages(self) -> None:
        pkg_a = "github.com/foo/pkg_a"
        pkg_b = "github.com/foo/pkg_b"
        lines = (
            _passing_test(pkg_a, "TestSharedName")
            + _failing_test(pkg_b, "TestSharedName")
            + [_package_pass(pkg_a), _package_fail(pkg_b)]
        )
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"][f"{pkg_a}.TestSharedName"] == "passed"
        assert result["tests"][f"{pkg_b}.TestSharedName"] == "failed"


class TestGoJSONParserEdgeCases:
    def test_empty_string(self) -> None:
        result = GoJSONParser().parse("")
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_whitespace_only(self) -> None:
        result = GoJSONParser().parse("   \n  \n")
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_non_json_lines_skipped(self) -> None:
        pkg = "github.com/foo/bar"
        raw = "\n".join([
            "SOME BUILD OUTPUT",
            "# github.com/foo/bar",
            _event(Action="run", Package=pkg, Test="TestFoo"),
            _event(Action="pass", Package=pkg, Test="TestFoo", Elapsed=0.001),
            _event(Action="pass", Package=pkg, Elapsed=0.01),
            "more non-json",
        ])
        result = GoJSONParser().parse(raw)
        assert result["tests"][f"{pkg}.TestFoo"] == "passed"
        assert result["compiled"] is True

    def test_deterministic_across_repeated_calls(self) -> None:
        pkg = "github.com/foo/bar"
        lines = (
            _passing_test(pkg, "TestA")
            + _failing_test(pkg, "TestB")
            + [_package_fail(pkg)]
        )
        raw = "\n".join(lines)
        parser = GoJSONParser()
        results = [parser.parse(raw) for _ in range(5)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_no_package_field(self) -> None:
        # Events without a Package field should still be parsed gracefully;
        # key is just the test name when package is absent/empty.
        lines = [
            _event(Action="run", Test="TestFoo"),
            _event(Action="pass", Test="TestFoo", Elapsed=0.001),
        ]
        result = GoJSONParser().parse("\n".join(lines))
        assert result["tests"]["TestFoo"] == "passed"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_parser_go_returns_go_json_parser(self) -> None:
        parser = get_parser("go")
        assert parser is not None
        assert isinstance(parser, GoJSONParser)

    def test_get_parser_python_returns_python_passthrough(self) -> None:
        parser = get_parser("python")
        assert parser is not None
        assert isinstance(parser, PythonPassthroughParser)

    def test_get_parser_unknown_returns_none(self) -> None:
        assert get_parser("cobol") is None
        assert get_parser("") is None
        assert get_parser("rust") is None

    def test_register_custom_parser(self) -> None:
        class FakeParser:
            def parse(self, raw_output: str) -> ParseResult:
                return ParseResult(tests={}, compiled=True)

        register("test_lang_xyz", FakeParser())
        assert get_parser("test_lang_xyz") is not None

    def test_register_overrides_existing(self) -> None:
        class ParserV2:
            def parse(self, raw_output: str) -> ParseResult:
                return ParseResult(tests={"x": "passed"}, compiled=True)

        register("test_override_lang", ParserV2())
        p = get_parser("test_override_lang")
        assert p is not None
        result = p.parse("")
        assert result["tests"] == {"x": "passed"}


# ---------------------------------------------------------------------------
# PythonPassthroughParser
# ---------------------------------------------------------------------------

class TestPythonPassthroughParser:
    def test_returns_empty_tests(self) -> None:
        result = PythonPassthroughParser().parse("any output")
        assert result["tests"] == {}

    def test_compiled_true(self) -> None:
        result = PythonPassthroughParser().parse("")
        assert result["compiled"] is True
