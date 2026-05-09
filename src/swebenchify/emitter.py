"""Stage 6: JSONL emission.

Serializes validated, filtered instances to SWE-bench-compatible JSONL.
See SPEC.md Section 5.7.
"""

from __future__ import annotations

# TODO: Implement JSONL emission
# - Write one JSON object per line conforming to SWEbenchInstance schema
# - Per-repository output: {output_dir}/{repo_slug}-task-instances.jsonl
# - Combined output: {output_dir}/all-task-instances.jsonl
# - Optional: Upload to HuggingFace Datasets Hub
