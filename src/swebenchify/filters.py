"""Stage 5: Quality filters.

Applies configurable deterministic filters to validated instances.
See SPEC.md Section 5.6.
"""

from __future__ import annotations

import json
import logging
import re

from swebenchify.config import FilterConfig
from swebenchify.models import TaskInstance

logger = logging.getLogger(__name__)


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

    return reasons
