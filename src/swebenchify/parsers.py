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
- ``PythonPassthroughParser`` — Placeholder; returns empty results (Python
  validation still uses agent-based interpretation).
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, TypedDict

logger = logging.getLogger(__name__)

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
# PythonPassthroughParser
# ---------------------------------------------------------------------------

class PythonPassthroughParser:
    """Placeholder parser for Python instances.

    Python validation still uses agent-based interpretation (the agent
    writes a ``validation_result.json`` directly).  This parser satisfies
    the ``TestLogParser`` protocol but always returns empty results — it
    should never be called in the normal Python validation path.
    """

    def parse(self, raw_output: str) -> ParseResult:
        return ParseResult(tests={}, compiled=True)


# ---------------------------------------------------------------------------
# Auto-register built-in parsers on import
# ---------------------------------------------------------------------------

register("go", GoJSONParser())
register("python", PythonPassthroughParser())
