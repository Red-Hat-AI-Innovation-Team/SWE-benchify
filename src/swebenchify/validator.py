"""Stage 4: Instance validation.

Dispatches a coding agent to validate each candidate instance by running
tests before and after applying the gold patch. See SPEC.md Section 5.5.
"""

from __future__ import annotations

# TODO: Implement instance validation
# - Prepare workspace with repo at base_commit, test patch, gold patch
# - Launch Claude Code session for validation
# - Read and validate validation_result.json
# - Compute FAIL_TO_PASS and PASS_TO_PASS
# - Support parallel validation up to concurrency limit
