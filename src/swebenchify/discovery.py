"""Stage 3: Environment discovery.

Dispatches a coding agent to discover the build, install, and test setup
for each repository version. See SPEC.md Section 5.4.
"""

from __future__ import annotations

# TODO: Implement environment discovery
# - Prepare workspace with repo checked out at target commit
# - Launch Claude Code session for env discovery
# - Read and validate env_spec.json and version.json
# - Cache results by (repo, version)
# - Handle retries with amended prompts
