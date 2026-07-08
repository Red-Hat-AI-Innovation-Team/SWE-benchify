"""Tests for swebenchify.parsers — TestLogParser protocol and GoJSONParser."""

from __future__ import annotations

import json

from swebenchify.parsers import (
    GoJSONParser,
    MavenSurefireParser,
    ParseResult,
    PytestVerboseParser,
    RustTestParser,
    get_parser,
    normalize_rust_f2p,
    normalize_rust_test_id,
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

    def test_get_parser_python_returns_pytest_verbose_parser(self) -> None:
        parser = get_parser("python")
        assert parser is not None
        assert isinstance(parser, PytestVerboseParser)

    def test_get_parser_unknown_returns_none(self) -> None:
        assert get_parser("cobol") is None
        assert get_parser("") is None
        assert get_parser("fortran") is None

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
# PytestVerboseParser
# ---------------------------------------------------------------------------

class TestPytestVerboseParser:
    def test_single_passing_test(self) -> None:
        output = "tests/test_foo.py::test_bar PASSED\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar"] == "passed"
        assert result["compiled"] is True

    def test_single_failing_test(self) -> None:
        output = "tests/test_foo.py::test_bar FAILED\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar"] == "failed"
        assert result["compiled"] is True

    def test_mixed_pass_fail(self) -> None:
        output = (
            "tests/test_foo.py::test_bar PASSED\n"
            "tests/test_foo.py::test_baz FAILED\n"
        )
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar"] == "passed"
        assert result["tests"]["tests/test_foo.py::test_baz"] == "failed"

    def test_class_based_test(self) -> None:
        output = "tests/test_app.py::TestApp::test_login PASSED\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_app.py::TestApp::test_login"] == "passed"

    def test_parametrized_tests(self) -> None:
        output = (
            "tests/test_foo.py::test_bar[param1] PASSED\n"
            "tests/test_foo.py::test_bar[param2] FAILED\n"
        )
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar[param1]"] == "passed"
        assert result["tests"]["tests/test_foo.py::test_bar[param2]"] == "failed"

    def test_skipped_test(self) -> None:
        output = "tests/test_foo.py::test_skip SKIPPED\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_skip"] == "skipped"

    def test_xfail_is_failed(self) -> None:
        output = "tests/test_foo.py::test_expected XFAIL\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_expected"] == "failed"

    def test_xpass_is_passed(self) -> None:
        output = "tests/test_foo.py::test_surprise XPASS\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_surprise"] == "passed"

    def test_error_is_failed(self) -> None:
        output = "tests/test_foo.py::test_broken ERROR\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_broken"] == "failed"

    def test_collection_error_is_compile_false(self) -> None:
        output = "ERROR collecting tests/test_foo.py\nModuleNotFoundError: No module named 'foo'\n"
        result = PytestVerboseParser().parse(output)
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_import_error_is_compile_false(self) -> None:
        output = "ImportError: cannot import name 'bar' from 'foo'\n"
        result = PytestVerboseParser().parse(output)
        assert result["compiled"] is False

    def test_syntax_error_is_compile_false(self) -> None:
        output = "SyntaxError: invalid syntax\n"
        result = PytestVerboseParser().parse(output)
        assert result["compiled"] is False

    def test_empty_output(self) -> None:
        result = PytestVerboseParser().parse("")
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_non_test_lines_ignored(self) -> None:
        output = (
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.11, pytest-7.4.0\n"
            "tests/test_foo.py::test_bar PASSED\n"
            "============================== 1 passed in 0.01s ==============================\n"
        )
        result = PytestVerboseParser().parse(output)
        assert len(result["tests"]) == 1
        assert result["tests"]["tests/test_foo.py::test_bar"] == "passed"

    def test_with_percentage_indicator(self) -> None:
        output = "tests/test_foo.py::test_bar PASSED                              [ 50%]\n"
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar"] == "passed"

    def test_failed_priority_on_duplicate(self) -> None:
        output = (
            "tests/test_foo.py::test_bar PASSED\n"
            "tests/test_foo.py::test_bar FAILED\n"
        )
        result = PytestVerboseParser().parse(output)
        assert result["tests"]["tests/test_foo.py::test_bar"] == "failed"

    def test_compiled_true_when_tests_present_despite_collection_keyword(self) -> None:
        output = (
            "tests/test_foo.py::test_bar PASSED\n"
            "Some unrelated line with ERROR collecting mention\n"
        )
        result = PytestVerboseParser().parse(output)
        assert result["compiled"] is True
        assert len(result["tests"]) == 1


# ---------------------------------------------------------------------------
# normalize_go_test_id / is_e2e_test_id / normalize_go_f2p
# ---------------------------------------------------------------------------

class TestNormalizeGoTestId:
    def test_strips_module_path_prefix(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        result = normalize_go_test_id(
            "go.etcd.io/etcd/server/v3/etcdserver/api/etcdhttp.TestFoo"
        )
        assert result == "TestFoo"

    def test_collapses_subtest_suffix(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        assert normalize_go_test_id("TestFoo/case1") == "TestFoo"

    def test_strips_prefix_and_collapses_subtest(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        result = normalize_go_test_id(
            "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo/case1"
        )
        assert result == "TestFoo"

    def test_bare_test_name_unchanged(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        assert normalize_go_test_id("TestFoo") == "TestFoo"

    def test_benchmark_prefix(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        assert normalize_go_test_id("pkg.BenchmarkFoo/run1") == "BenchmarkFoo"

    def test_example_prefix(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        assert normalize_go_test_id("pkg.ExampleBar") == "ExampleBar"

    def test_nested_subtest(self) -> None:
        from swebenchify.parsers import normalize_go_test_id
        # Only the first "/" level is stripped — deepest parent name
        result = normalize_go_test_id(
            'go.etcd.io/etcd/tests/v3/e2e.TestAuthority/Size:_1,_Scenario:_"http://address"'
        )
        assert result == "TestAuthority"


class TestIsE2eTestId:
    def test_e2e_package(self) -> None:
        from swebenchify.parsers import is_e2e_test_id
        assert is_e2e_test_id("go.etcd.io/etcd/tests/v3/e2e.TestFoo") is True

    def test_integration_package(self) -> None:
        from swebenchify.parsers import is_e2e_test_id
        assert is_e2e_test_id("github.com/foo/bar/integration/TestBaz") is True

    def test_unit_test_not_e2e(self) -> None:
        from swebenchify.parsers import is_e2e_test_id
        assert is_e2e_test_id(
            "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo"
        ) is False

    def test_pkg_not_e2e(self) -> None:
        from swebenchify.parsers import is_e2e_test_id
        assert is_e2e_test_id("go.etcd.io/etcd/pkg/v3/featuregate.TestBar") is False

    def test_bare_test_name_not_e2e(self) -> None:
        from swebenchify.parsers import is_e2e_test_id
        assert is_e2e_test_id("TestFoo") is False


class TestNormalizeGoF2p:
    def test_normalises_and_deduplicates(self) -> None:
        from swebenchify.parsers import normalize_go_f2p
        raw = [
            "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo/case1",
            "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo/case2",  # same parent → dedup
            "go.etcd.io/etcd/server/v3/etcdhttp.TestBar",
        ]
        result = normalize_go_f2p(raw)
        assert result == ["TestBar", "TestFoo"]

    def test_excludes_e2e_tests(self) -> None:
        from swebenchify.parsers import normalize_go_f2p
        raw = [
            "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo",
            "go.etcd.io/etcd/tests/v3/e2e.TestE2EFoo",   # should be excluded
        ]
        result = normalize_go_f2p(raw)
        assert result == ["TestFoo"]
        assert "TestE2EFoo" not in result

    def test_empty_input(self) -> None:
        from swebenchify.parsers import normalize_go_f2p
        assert normalize_go_f2p([]) == []

    def test_sorted_output(self) -> None:
        from swebenchify.parsers import normalize_go_f2p
        raw = [
            "pkg.TestZebra",
            "pkg.TestAlpha",
        ]
        assert normalize_go_f2p(raw) == ["TestAlpha", "TestZebra"]

    def test_msb_harness_check_real_ids(self) -> None:
        """Reproduce the IDs observed in the MSB harness check for #19086."""
        from swebenchify.parsers import normalize_go_f2p
        raw_our_f2p = [
            "go.etcd.io/etcd/server/v3/etcdserver/api/etcdhttp.TestHTTPSubPath",
            "go.etcd.io/etcd/server/v3/etcdserver/api/etcdhttp.TestHTTPSubPath//readyz/learner_ok",
            "go.etcd.io/etcd/server/v3/etcdserver/api/etcdhttp.TestLearnerReadyCheck",
        ]
        result = normalize_go_f2p(raw_our_f2p)
        # Should match what MSB's regex parser produces
        assert "TestHTTPSubPath" in result
        assert "TestLearnerReadyCheck" in result
        # Subtest collapsed into parent — no duplicates
        assert result.count("TestHTTPSubPath") == 1


# ---------------------------------------------------------------------------
# MavenSurefireParser
# ---------------------------------------------------------------------------

class TestMavenSurefireParser:
    def test_single_passing_class(self) -> None:
        output = (
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.5 s -- in com.fasterxml.jackson.databind.SomeTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.fasterxml.jackson.databind.SomeTest"] == "passed"
        assert result["compiled"] is True

    def test_single_failing_class(self) -> None:
        output = (
            "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.3 s <<< FAILURE! -- in com.pkg.OtherTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.OtherTest"] == "failed"
        assert result["compiled"] is True

    def test_class_with_errors(self) -> None:
        output = (
            "[ERROR] Tests run: 2, Failures: 0, Errors: 1, Skipped: 0, "
            "Time elapsed: 0.1 s <<< ERROR! -- in com.pkg.ErrorTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.ErrorTest"] == "failed"

    def test_mixed_pass_and_fail(self) -> None:
        output = (
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.5 s -- in com.pkg.GoodTest\n"
            "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.3 s <<< FAILURE! -- in com.pkg.BadTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.GoodTest"] == "passed"
        assert result["tests"]["com.pkg.BadTest"] == "failed"

    def test_all_skipped_class(self) -> None:
        output = (
            "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 3, "
            "Time elapsed: 0.01 s -- in com.pkg.SkippedTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.SkippedTest"] == "skipped"

    def test_partial_skip_is_passed(self) -> None:
        output = (
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 2, "
            "Time elapsed: 0.3 s -- in com.pkg.PartialTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.PartialTest"] == "passed"

    def test_compile_failure(self) -> None:
        output = (
            "[ERROR] COMPILATION ERROR :\n"
            "[ERROR] /repo/src/main/java/com/pkg/Foo.java:[10,5] "
            "cannot find symbol\n"
            "[INFO] BUILD FAILURE\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_build_failure_without_tests(self) -> None:
        output = (
            "[INFO] BUILD FAILURE\n"
            "[ERROR] Failed to execute goal org.apache.maven.plugins:"
            "maven-compiler-plugin:3.11.0:compile\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_build_failure_with_test_results_is_test_failure(self) -> None:
        output = (
            "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.3 s <<< FAILURE! -- in com.pkg.FailTest\n"
            "[INFO] \n"
            "[INFO] BUILD FAILURE\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["compiled"] is True
        assert result["tests"]["com.pkg.FailTest"] == "failed"

    def test_empty_output(self) -> None:
        result = MavenSurefireParser().parse("")
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_whitespace_only(self) -> None:
        result = MavenSurefireParser().parse("   \n  \n")
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_non_test_lines_ignored(self) -> None:
        output = (
            "[INFO] Scanning for projects...\n"
            "[INFO] Building jackson-databind 2.16.0-SNAPSHOT\n"
            "[INFO] --- maven-surefire-plugin:3.2.5:test (default-test) ---\n"
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.5 s -- in com.pkg.SomeTest\n"
            "[INFO] Results:\n"
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0\n"
        )
        result = MavenSurefireParser().parse(output)
        assert len(result["tests"]) == 1
        assert result["tests"]["com.pkg.SomeTest"] == "passed"

    def test_multiple_classes(self) -> None:
        output = (
            "[INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 1.2 s -- in com.pkg.AlphaTest\n"
            "[INFO] Tests run: 8, Failures: 0, Errors: 0, Skipped: 1, "
            "Time elapsed: 0.8 s -- in com.pkg.BetaTest\n"
            "[ERROR] Tests run: 3, Failures: 2, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.3 s <<< FAILURE! -- in com.pkg.GammaTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert len(result["tests"]) == 3
        assert result["tests"]["com.pkg.AlphaTest"] == "passed"
        assert result["tests"]["com.pkg.BetaTest"] == "passed"
        assert result["tests"]["com.pkg.GammaTest"] == "failed"

    def test_inner_class_name(self) -> None:
        output = (
            "[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.1 s -- in com.pkg.OuterTest$InnerTest\n"
        )
        result = MavenSurefireParser().parse(output)
        assert result["tests"]["com.pkg.OuterTest$InnerTest"] == "passed"

    def test_deterministic_across_repeated_calls(self) -> None:
        output = (
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.5 s -- in com.pkg.SomeTest\n"
            "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, "
            "Time elapsed: 0.3 s <<< FAILURE! -- in com.pkg.OtherTest\n"
        )
        parser = MavenSurefireParser()
        results = [parser.parse(output) for _ in range(5)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_registry_java_returns_maven_parser(self) -> None:
        parser = get_parser("java")
        assert parser is not None
        assert isinstance(parser, MavenSurefireParser)


# ---------------------------------------------------------------------------
# Rust test fixtures
# ---------------------------------------------------------------------------

RUST_PASSING_OUTPUT = '''
running 3 tests
test utils::tests::test_parse_url ... ok
test config::tests::test_default_config ... ok
test config::tests::test_custom_config ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
'''

RUST_FAILING_OUTPUT = '''
running 2 tests
test utils::tests::test_parse_url ... FAILED
test config::tests::test_default_config ... ok

test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.02s
'''

RUST_COMPILE_ERROR_OUTPUT = '''
error[E0425]: cannot find value `foo` in this scope
  --> src/lib.rs:10:5
   |
10 |     foo
   |     ^^^ not found in this scope
'''

RUST_WORKSPACE_OUTPUT = '''
   Compiling pingora-core v0.1.0
   Compiling pingora-proxy v0.1.0
running 2 tests
test core::tests::test_server ... ok
test core::tests::test_connection ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.03s

running 1 test
test proxy::tests::test_upstream ... FAILED

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.05s
'''

RUST_IGNORED_OUTPUT = '''
running 2 tests
test slow_test ... ignored
test fast_test ... ok

test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.01s
'''


# ---------------------------------------------------------------------------
# RustTestParser
# ---------------------------------------------------------------------------

class TestRustTestParserPassing:
    def test_all_three_pass(self) -> None:
        result = RustTestParser().parse(RUST_PASSING_OUTPUT)
        assert result["compiled"] is True
        assert len(result["tests"]) == 3
        assert result["tests"]["utils::tests::test_parse_url"] == "passed"
        assert result["tests"]["config::tests::test_default_config"] == "passed"
        assert result["tests"]["config::tests::test_custom_config"] == "passed"


class TestRustTestParserFailing:
    def test_mixed_pass_and_fail(self) -> None:
        result = RustTestParser().parse(RUST_FAILING_OUTPUT)
        assert result["compiled"] is True
        assert result["tests"]["utils::tests::test_parse_url"] == "failed"
        assert result["tests"]["config::tests::test_default_config"] == "passed"


class TestRustTestParserCompileError:
    def test_compile_error(self) -> None:
        result = RustTestParser().parse(RUST_COMPILE_ERROR_OUTPUT)
        assert result["compiled"] is False
        assert result["tests"] == {}


class TestRustTestParserWorkspace:
    def test_workspace_multiple_crates(self) -> None:
        result = RustTestParser().parse(RUST_WORKSPACE_OUTPUT)
        assert result["compiled"] is True
        assert result["tests"]["core::tests::test_server"] == "passed"
        assert result["tests"]["core::tests::test_connection"] == "passed"
        assert result["tests"]["proxy::tests::test_upstream"] == "failed"


class TestRustTestParserIgnored:
    def test_ignored_mapped_to_skipped(self) -> None:
        result = RustTestParser().parse(RUST_IGNORED_OUTPUT)
        assert result["compiled"] is True
        assert result["tests"]["slow_test"] == "skipped"
        assert result["tests"]["fast_test"] == "passed"


class TestRustTestParserEmpty:
    def test_empty_string(self) -> None:
        result = RustTestParser().parse("")
        assert result["compiled"] is False
        assert result["tests"] == {}


class TestRustParserRegistry:
    def test_get_parser_rust(self) -> None:
        parser = get_parser("rust")
        assert parser is not None
        assert isinstance(parser, RustTestParser)


class TestNormalizeRustTestId:
    def test_bare_name_unchanged(self) -> None:
        assert normalize_rust_test_id("test_foo") == "test_foo"

    def test_module_path_preserved(self) -> None:
        assert normalize_rust_test_id("utils::tests::test_parse_url") == "utils::tests::test_parse_url"


class TestNormalizeRustF2p:
    def test_normalise_dedup_sort(self) -> None:
        raw = [
            "config::tests::test_b",
            "config::tests::test_a",
            "config::tests::test_b",
        ]
        result = normalize_rust_f2p(raw)
        assert result == ["config::tests::test_a", "config::tests::test_b"]

    def test_empty_input(self) -> None:
        assert normalize_rust_f2p([]) == []
