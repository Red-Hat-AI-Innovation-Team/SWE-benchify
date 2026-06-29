"""Stage 5: Quality filters.

Applies configurable deterministic filters to validated instances.
See docs/SPEC.md Sections 4.4 and 5.6.
"""

from __future__ import annotations

import json
import logging
import re

from swebenchify.config import FilterConfig
from swebenchify.models import TaskInstance, ValidationResult

logger = logging.getLogger(__name__)

_ADDED_DEF_RE = re.compile(r"^\+\s*(?:async\s+)?(?:def|class)\s+(\w+)")
_REMOVED_DEF_RE = re.compile(r"^-\s*(?:async\s+)?(?:def|class)\s+(\w+)")

# Go exported function / type definitions in a unified diff
_GO_ADDED_FUNC_RE = re.compile(r"^\+\s*func\s+(\([^)]+\)\s+)?([A-Z]\w*)\s*\(")
_GO_REMOVED_FUNC_RE = re.compile(r"^-\s*func\s+(\([^)]+\)\s+)?([A-Z]\w*)\s*\(")
_GO_ADDED_TYPE_RE = re.compile(r"^\+\s*type\s+([A-Z]\w*)\s+")
_GO_REMOVED_TYPE_RE = re.compile(r"^-\s*type\s+([A-Z]\w*)\s+")


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
        reasons.append(f"patch too small ({patch_lines} lines, min {config.min_patch_lines})")

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


def get_go_filter_reasons(
    inst: TaskInstance,
    config: FilterConfig,
    validation_result: ValidationResult | None = None,
) -> list[str]:
    """Return Go-specific filter reasons for a TaskInstance.

    Runs both the standard filters (via get_filter_reasons) and Go-specific
    ones: build-error rejection and Go introduced-symbol check.

    Args:
        inst: The validated task instance.
        config: Filter configuration.
        validation_result: The ValidationResult for this instance, used to
            check the ``compiled`` flag. May be None (no build-error check).

    Returns:
        List of filter reason strings. Empty means the instance passes.
    """
    reasons = get_filter_reasons(inst, config)

    # Go build-error filter: pre-fix compile failure is not a real test task
    if validation_result is not None and not validation_result.compiled:
        reasons.append("pre-fix build failed (compiled=False)")

    # Go introduced-symbol filter (exported func/type)
    if config.no_new_symbol_tests:
        go_reason = check_go_introduced_symbol(inst.patch, inst.FAIL_TO_PASS)
        if go_reason:
            reasons.append(go_reason)

    return reasons


def apply_go_filters(
    instances: list[TaskInstance],
    config: FilterConfig,
    validation_results: dict[str, ValidationResult] | None = None,
) -> list[TaskInstance]:
    """Apply all filters (standard + Go-specific) to Go-language instances.

    Args:
        instances: Validated TaskInstance list.
        config: Filter configuration.
        validation_results: Mapping from instance_id to ValidationResult,
            used for the compiled-flag check. May be None.

    Returns:
        Filtered list of TaskInstance objects.
    """
    filtered = []
    vr_map = validation_results or {}
    for inst in instances:
        vr = vr_map.get(inst.instance_id)
        reasons = get_go_filter_reasons(inst, config, validation_result=vr)
        if reasons:
            logger.debug(
                "Filtered Go instance %s: %s", inst.instance_id, ", ".join(reasons)
            )
        else:
            filtered.append(inst)
    logger.info(
        "Go quality filter: %d/%d instances passed", len(filtered), len(instances)
    )
    return filtered


def extract_new_go_symbols(patch: str | None) -> set[str]:
    """Extract exported Go function/type names first introduced in a gold patch.

    A symbol is "new" only if it appears in an added line but NOT in a
    removed line — this distinguishes truly new exports from renames of
    existing ones.

    Returns:
        Set of exported Go symbol names newly introduced by the patch.
    """
    if not patch:
        return set()
    added: set[str] = set()
    removed: set[str] = set()
    for line in patch.splitlines():
        func_add = _GO_ADDED_FUNC_RE.match(line)
        if func_add:
            added.add(func_add.group(2))
            continue
        func_rm = _GO_REMOVED_FUNC_RE.match(line)
        if func_rm:
            removed.add(func_rm.group(2))
            continue
        type_add = _GO_ADDED_TYPE_RE.match(line)
        if type_add:
            added.add(type_add.group(1))
            continue
        type_rm = _GO_REMOVED_TYPE_RE.match(line)
        if type_rm:
            removed.add(type_rm.group(1))
    return added - removed


def check_go_introduced_symbol(
    patch: str | None, fail_to_pass_json: str
) -> str | None:
    """Check if FAIL_TO_PASS tests reference exported Go symbols first introduced
    in the gold patch (Go analogue of check_new_symbol_in_tests).

    Go test identifiers use the form ``TestFunctionName`` or
    ``TestFunctionName/subtest``; an exported function ``NewFoo`` would
    appear in a test named ``TestNewFoo`` or similar.

    Args:
        patch: The gold patch (unified diff).
        fail_to_pass_json: JSON-encoded list of FAIL_TO_PASS test names.

    Returns:
        A filter reason string, or None if no issue found.
    """
    new_symbols = extract_new_go_symbols(patch)
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
                    f"newly-introduced Go symbol '{symbol}'"
                )
    return None


def check_import_attribute_error(test_log: str | None) -> str | None:
    """Check if pre-solution test log contains ImportError or AttributeError.

    These indicate dependency issues rather than real bugs, so instances
    with these errors should be discarded (SWE-bench paper filter).

    Not yet integrated into get_filter_reasons() because TaskInstance
    does not store pre-solution test logs. To wire this in:
    TODO: add a pre_solution_log field to TaskInstance, a FilterConfig
    flag, and call this from get_filter_reasons(). Until then, call
    this directly from the validation stage when logs are available.

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
    (e.g., 'tests/foo.py::TestBar::test_baz[param]') and checks if
    any component ends with the symbol name. Strips parametrize
    suffixes ([...]) before matching. This handles conventions like
    'test_<symbol>' and 'Test<Symbol>' without false-positiving on
    short names that happen to appear as substrings.
    """
    parts = test_name.split("::")
    for part in parts:
        bare = part.split("[")[0]
        if bare.endswith(symbol) or bare == symbol:
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
