"""Stage 1: PR collection.

Fetches merged pull requests with linked issues from the GitHub API.
See SPEC.md Section 5.2.
"""

from __future__ import annotations

# TODO: Implement PR collection
# - Fetch all closed, merged PRs from GitHub REST API
# - Extract referenced issue numbers using keyword patterns
# - Handle rate limiting with exponential backoff
# - Support resumption by skipping already-processed PRs
