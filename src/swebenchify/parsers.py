"""Test-log parser protocol and language-specific implementations.

This module is intentionally **standalone and dependency-light**: it imports
only the Python standard library so that the RH-org evaluator (Multi-SWE-bench)
can import the identical ``GoJSONParser`` without pulling in the rest of the
SWE-benchify pipeline.

Public surface
--------------
- ``ParseResult``      — TypedDict returned by every parser.
- ``TestLogParser``    — Protocol that parsers must satisfy.
- ``register()``       — Register a parser for a language string.
- ``get_parser()``     — Retrieve a registered parser (or ``None``).
- ``GoJSONParser``     — Parses ``go test -json`` NDJSON event streams.
- ``PytestVerboseParser`` — Parses ``pytest -v`` output for test outcomes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Go test ID normalisation
# ---------------------------------------------------------------------------

# Matches the first occurrence of a Go test function name following a "."
# or at the start of the string. Go test functions are named Test*, Benchmark*,
# or Example* by convention.
_TEST_FUNC_RE = re.compile(r"(?:^|\.)((?:Test|Benchmark|Example)\w*)")

# Packages whose tests should be excluded from F2P (integration / e2e).
# These are too slow, environment-dependent, or require a live cluster.
_E2E_PKG_RE = re.compile(r"/(?:e2e|integration)[/.]")

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ParseResult(TypedDict):
    """Mapping of test identifiers to their outcome, plus a compile flag."""

    tests: dict[str, str]  # test_id -> "passed" | "failed" | "skipped" | "error"
    compiled: bool          # False if the package failed to compile


class TestLogParser(Protocol):
    """Protocol that every language-specific test-log parser must satisfy."""

    def parse(self, raw_output: str) -> ParseResult:
        """Parse raw test output into a structured result.

        Args:
            raw_output: The complete stdout/stderr of the test run as a
                single string (may contain non-JSON lines).

        Returns:
            A :class:`ParseResult` with a ``tests`` dict and a ``compiled``
            flag.  If the package failed to compile, ``compiled`` is
            ``False`` and ``tests`` is empty.
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, TestLogParser] = {}


def register(language: str, parser: TestLogParser) -> None:
    """Register *parser* as the handler for *language*.

    Subsequent calls with the same *language* overwrite the previous entry.
    """
    _REGISTRY[language] = parser


def get_parser(language: str) -> TestLogParser | None:
    """Return the registered parser for *language*, or ``None``."""
    return _REGISTRY.get(language)


# ---------------------------------------------------------------------------
# Go test ID normalisation
# ---------------------------------------------------------------------------

def normalize_go_test_id(test_id: str) -> str:
    """Normalise a Go test ID to the bare test function name.

    Strips the Go module path / package prefix and collapses subtest
    suffixes (``/case1``) to the parent test function name, producing
    the same format that Multi-SWE-bench's ``go test -v`` regex parser
    emits (e.g. ``"TestFoo"``).

    Examples::

        "go.etcd.io/etcd/server/v3/etcdhttp.TestFoo/case1" → "TestFoo"
        "TestFoo/case1"                                     → "TestFoo"
        "go.etcd.io/etcd/pkg.TestBar"                       → "TestBar"
        "TestBaz"                                           → "TestBaz"
    """
    m = _TEST_FUNC_RE.search(test_id)
    name = m.group(1) if m else test_id
    return name.split("/")[0]


def is_e2e_test_id(test_id: str) -> bool:
    """Return ``True`` if *test_id* belongs to an e2e or integration package.

    These tests require a live cluster or network environment and cannot
    reliably run within the benchmark's Docker validation timeout.
    """
    return bool(_E2E_PKG_RE.search(test_id))


def normalize_go_f2p(test_ids: list[str]) -> list[str]:
    """Normalise, filter, and deduplicate a list of Go test IDs.

    Applies :func:`normalize_go_test_id` to every entry, removes tests
    from e2e / integration packages (via :func:`is_e2e_test_id`), and
    returns a sorted, deduplicated list of bare test function names.

    The result matches the format Multi-SWE-bench's grader expects when
    it uses ``go test -v`` + regex parsing.

    Args:
        test_ids: Raw test IDs from ``GoJSONParser`` (package-qualified,
            may include subtest suffixes).

    Returns:
        Sorted list of normalised test names, e2e tests excluded.
    """
    seen: set[str] = set()
    result: list[str] = []
    for tid in test_ids:
        if is_e2e_test_id(tid):
            continue
        normalised = normalize_go_test_id(tid)
        if normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return sorted(result)


# ---------------------------------------------------------------------------
# GoJSONParser
# ---------------------------------------------------------------------------

class GoJSONParser:
    """Parse the NDJSON event stream produced by ``go test -json``.

    ``go test -json`` emits one JSON object per line.  Each object has at
    minimum an ``Action`` field.  Test-level events additionally carry a
    ``Test`` field and a ``Package`` field.

    Key invariants:
    - A test is identified by ``"{Package}.{Test}"`` (slashes preserved for
      subtests, e.g. ``"github.com/foo/bar.TestFoo/case1"``).
    - A package-level ``Action: "fail"`` with *no* ``Test`` events having
      run at all signals a compile / link error (``compiled=False``).
    - Events from parallel packages arrive interleaved; the parser buffers
      state per ``(Package, Test)`` key.
    """

    def parse(self, raw_output: str) -> ParseResult:  # noqa: C901
        if not raw_output or not raw_output.strip():
            return ParseResult(tests={}, compiled=False)

        # Per-(Package, Test) terminal status
        test_status: dict[str, str] = {}
        # Track whether any test event was emitted per package
        package_had_tests: dict[str, bool] = {}
        # Track package-level outcome
        package_failed: set[str] = set()

        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # build output or other non-JSON line — skip
                continue

            action = event.get("Action", "")
            package = event.get("Package", "")
            test = event.get("Test")  # absent for package-level events

            if not action:
                continue

            if test:
                # Test-level event
                key = f"{package}.{test}" if package else test
                package_had_tests[package] = True
                if action == "pass":
                    test_status[key] = "passed"
                elif action == "fail":
                    test_status[key] = "failed"
                elif action == "skip":
                    test_status[key] = "skipped"
                # "run" and "output" events don't update the terminal status
            else:
                # Package-level event
                if package not in package_had_tests:
                    package_had_tests[package] = False
                if action == "fail":
                    package_failed.add(package)

        # Determine compiled flag: if any package failed with zero test
        # events, we have a build error.
        compiled = True
        for pkg in package_failed:
            if not package_had_tests.get(pkg, False):
                compiled = False
                break

        return ParseResult(tests=test_status, compiled=compiled)


# ---------------------------------------------------------------------------
# PytestVerboseParser
# ---------------------------------------------------------------------------

# Matches pytest -v output lines: "path/test.py::Class::method STATUS"
# Also handles parametrized tests (test[param]) and percentage (PASSED [50%])
_PYTEST_LINE_RE = re.compile(
    r"^(\S*::(?:\S+))\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)",
    re.MULTILINE,
)

_COLLECT_ERROR_RE = re.compile(
    r"(?:ERROR collecting|ModuleNotFoundError|ImportError|SyntaxError)"
)


class PytestVerboseParser:
    """Parse ``pytest -v`` output into structured test results.

    Handles standard verbose output (one line per test), parametrized
    tests, and detects collection/import errors as compile failures.
    """

    def parse(self, raw_output: str) -> ParseResult:
        if not raw_output or not raw_output.strip():
            return ParseResult(tests={}, compiled=False)

        test_status: dict[str, str] = {}

        for match in _PYTEST_LINE_RE.finditer(raw_output):
            test_id = match.group(1)
            status_word = match.group(2)
            if status_word in ("PASSED", "XPASS"):
                status = "passed"
            elif status_word in ("FAILED", "ERROR", "XFAIL"):
                status = "failed"
            elif status_word == "SKIPPED":
                status = "skipped"
            else:
                status = "failed"
            # For duplicate test IDs (subtests), "failed" takes priority
            if test_id not in test_status or status == "failed":
                test_status[test_id] = status

        compiled = True
        if not test_status and _COLLECT_ERROR_RE.search(raw_output):
            compiled = False

        return ParseResult(tests=test_status, compiled=compiled)


# ---------------------------------------------------------------------------
# MavenSurefireParser
# ---------------------------------------------------------------------------

# Matches per-class summary lines from Maven Surefire:
#   [INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.5 s -- in com.pkg.Test
#   [ERROR] Tests run: 3, Failures: 1, ... <<< FAILURE! -- in com.pkg.Test
_MAVEN_CLASS_SUMMARY_RE = re.compile(
    r"Tests run:\s*(\d+),\s*"
    r"Failures:\s*(\d+),\s*"
    r"Errors:\s*(\d+),\s*"
    r"Skipped:\s*(\d+)"
    r".*?--\s+in\s+([\w.$]+)",
    re.MULTILINE,
)

_MAVEN_BUILD_FAILURE_RE = re.compile(
    r"BUILD FAILURE|COMPILATION ERROR",
)


class MavenSurefireParser:
    """Parse Maven Surefire text output into class-level test results.

    Produces class-level test IDs (e.g. ``com.pkg.SomeTest``).
    """

    def parse(self, raw_output: str) -> ParseResult:
        if not raw_output or not raw_output.strip():
            return ParseResult(tests={}, compiled=False)

        test_status: dict[str, str] = {}
        for match in _MAVEN_CLASS_SUMMARY_RE.finditer(raw_output):
            total = int(match.group(1))
            failures = int(match.group(2))
            errors = int(match.group(3))
            skipped = int(match.group(4))
            class_name = match.group(5)

            if failures > 0 or errors > 0:
                test_status[class_name] = "failed"
            elif skipped == total:
                test_status[class_name] = "skipped"
            else:
                test_status[class_name] = "passed"

        compiled = True
        if not test_status:
            if _MAVEN_BUILD_FAILURE_RE.search(raw_output):
                compiled = False
            else:
                compiled = False

        return ParseResult(tests=test_status, compiled=compiled)


# ---------------------------------------------------------------------------
# Rust test output parsing
# ---------------------------------------------------------------------------

_RUST_TEST_RE = re.compile(r'^test\s+(\S+)\s+\.\.\.\s+(ok|FAILED|ignored)')
_RUST_COMPILE_ERROR_RE = re.compile(r'^error\[E\d{4}\]')


class RustTestParser:
    """Parse cargo test plain text output.

    Cargo test output format:
        test module::test_name ... ok
        test module::test_name ... FAILED
        test module::test_name ... ignored

    Compile errors are detected by 'error[EXXXX]' lines.
    """

    def parse(self, raw_output: str) -> ParseResult:
        if not raw_output or not raw_output.strip():
            return ParseResult(tests={}, compiled=False)

        tests: dict[str, str] = {}
        compiled = True

        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue

            if _RUST_COMPILE_ERROR_RE.match(line):
                compiled = False
                continue

            m = _RUST_TEST_RE.match(line)
            if m:
                test_name = m.group(1)
                outcome = m.group(2)
                if outcome == 'ok':
                    tests[test_name] = 'passed'
                elif outcome == 'FAILED':
                    tests[test_name] = 'failed'
                elif outcome == 'ignored':
                    tests[test_name] = 'skipped'

        if not compiled:
            return ParseResult(tests={}, compiled=False)

        return ParseResult(tests=tests, compiled=compiled)


def normalize_rust_test_id(test_id: str) -> str:
    """Normalise a Rust test ID. Rust IDs are module::test_name."""
    return test_id


def normalize_rust_f2p(test_ids: list[str]) -> list[str]:
    """Normalise, deduplicate, and sort a list of Rust test IDs."""
    seen: set[str] = set()
    result: list[str] = []
    for tid in test_ids:
        normalised = normalize_rust_test_id(tid)
        if normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return sorted(result)


# ---------------------------------------------------------------------------
# Auto-register built-in parsers on import
# ---------------------------------------------------------------------------

register("go", GoJSONParser())
register("python", PytestVerboseParser())
register("java", MavenSurefireParser())
register("rust", RustTestParser())
