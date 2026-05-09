"""Workspace manager.

Maintains bare clones, creates per-commit worktrees, and manages
workspace lifecycle. See SPEC.md Section 8.
"""

from __future__ import annotations

# TODO: Implement workspace manager
# - Maintain a bare clone per repository
# - Create per-commit worktrees for agent sessions
# - Cache environment specs by repository version
# - Clean up completed workspaces
# - Enforce safety invariants (sanitized paths, workspace root containment)
