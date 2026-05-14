"""Stage 5: Quality filters.

Applies configurable deterministic filters to validated instances.
See SPEC.md Sections 4.4 and 5.6.
"""

from __future__ import annotations

import json
import logging
import re

from swebenchify.config import FilterConfig
from swebenchify.models import TaskInstance

logger = logging.getLogger(__name__)

_ADDED_DEF_RE = re.compile(r"^\+\s*(?:async\s+)?(?:def|class)\s+(\w+)")
_REMOVED_DEF_RE = re.compile(r"^-\s*(?:async\s+)?(?:def|class)\s+(\w+)")


def apply_filters(
    instances: list[TaskInstance], config: FilterConfig
) -> list[TaskInstance]:
    """Apply quality filters to validated instances. Returns filtered list."""
    filtered = []
    for inst in instances:
        reasons = get_filter_reasons(inst, config)
        if reasons:
            logger.debug(
                "Filtered %s: %s", inst.instance_id, ", ".join(reasons)
            )
        else:
            filtered.append(inst)
    logger.info(
        "Quality filter: %d/%d instances passed", len(filtered), len(instances)
    )
    return filtered


def get_filter_reasons(inst: TaskInstance, config: FilterConfig) -> list[str]:
    """Return list of reasons this instance should be filtered. Empty = passes."""
    reasons: list[str] = []

    # Min problem statement words
    word_count = len(inst.problem_statement.split())
    if word_count < config.min_problem_statement_words:
        reasons.append(f"problem_statement too short ({word_count} words)")

    # No bare URLs
    if config.no_urls_in_problem and re.search(
        r"https?://\S+", inst.problem_statement
    ):
        reasons.append("problem_statement contains URLs")

    # No commit SHAs
    if config.no_shas_in_problem and re.search(
        r"\b[0-9a-f]{7,40}\b", inst.problem_statement
    ):
        reasons.append("problem_statement contains commit SHAs")

    # Image-only problem statement
    if config.no_image_only_problem:
        stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", inst.problem_statement).strip()
        if not stripped:
            reasons.append("problem_statement contains only image markdown")

    # Patch size
    patch_lines = len(inst.patch.splitlines()) if inst.patch else 0
    if patch_lines > config.max_patch_lines:
        reasons.append(f"patch too large ({patch_lines} lines)")
    if patch_lines < config.min_patch_lines:
        reasons.append("patch is empty")

    # FAIL_TO_PASS
    try:
        f2p = json.loads(inst.FAIL_TO_PASS)
        if len(f2p) < config.min_fail_to_pass:
            reasons.append("no FAIL_TO_PASS tests")
    except (json.JSONDecodeError, TypeError):
        reasons.append("invalid FAIL_TO_PASS JSON")

    # Newly-created function/class exclusion (SWE-bench paper filter)
    if config.no_new_symbol_tests:
        new_reason = check_new_symbol_in_tests(inst.patch, inst.FAIL_TO_PASS)
        if new_reason:
            reasons.append(new_reason)

    return reasons


def check_import_attribute_error(test_log: str | None) -> str | None:
    """Check if pre-solution test log contains ImportError or AttributeError.

    These indicate dependency issues rather than real bugs, so instances
    with these errors should be discarded (SWE-bench paper filter).

    Args:
        test_log: Raw test output from running tests before applying the fix.

    Returns:
        A filter reason string, or None if no issue found.
    """
    if not test_log:
        return None
    for error_type in ("ImportError", "AttributeError"):
        if error_type in test_log:
            return f"pre-solution test log contains {error_type}"
    return None


def extract_new_symbols(patch: str | None) -> set[str]:
    """Extract function/class names first introduced in a gold patch.

    Parses unified diff for added (+) and removed (-) def/class lines.
    A symbol is "new" only if it appears in an added line but NOT in a
    removed line — this distinguishes truly new symbols from modified
    signatures of existing functions.

    Returns:
        Set of symbol names that are newly introduced (not modified).
    """
    if not patch:
        return set()
    added: set[str] = set()
    removed: set[str] = set()
    for line in patch.splitlines():
        add_match = _ADDED_DEF_RE.match(line)
        if add_match:
            added.add(add_match.group(1))
            continue
        rm_match = _REMOVED_DEF_RE.match(line)
        if rm_match:
            removed.add(rm_match.group(1))
    return added - removed


def _symbol_in_test_name(symbol: str, test_name: str) -> bool:
    """Check if a pytest test identifier references a symbol by name.

    Extracts the test function/class components from a pytest ID
    (e.g., 'tests/foo.py::TestBar::test_baz') and checks if any
    component ends with the symbol name. This handles conventions like
    'test_<symbol>' and 'Test<Symbol>' without false-positiving on
    short names that happen to appear as substrings.
    """
    parts = test_name.split("::")
    for part in parts:
        if part.endswith(symbol):
            return True
        if part == symbol:
            return True
    return False


def check_new_symbol_in_tests(
    patch: str, fail_to_pass_json: str
) -> str | None:
    """Check if FAIL_TO_PASS tests reference functions/classes first introduced
    in the gold patch.

    If a test name contains a symbol that is newly defined in the patch,
    the test is unsolvable without knowing the arbitrary name chosen by
    the author. Such instances should be excluded.

    Args:
        patch: The gold patch (unified diff).
        fail_to_pass_json: JSON-encoded list of FAIL_TO_PASS test names.

    Returns:
        A filter reason string, or None if no issue found.
    """
    new_symbols = extract_new_symbols(patch)
    if not new_symbols:
        return None

    try:
        f2p = json.loads(fail_to_pass_json)
    except (json.JSONDecodeError, TypeError):
        return None

    for test_name in f2p:
        for symbol in new_symbols:
            if _symbol_in_test_name(symbol, test_name):
                return (
                    f"FAIL_TO_PASS test '{test_name}' references "
                    f"newly-created symbol '{symbol}'"
                )
    return None
