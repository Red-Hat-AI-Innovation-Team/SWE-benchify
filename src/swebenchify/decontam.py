"""Decontamination overlap checker for emitted dataset instances.

At emission time, each TaskInstance is checked against one or more
reference sets (SWE-bench, rh-swe-bench) to flag instances whose
instance_id or gold patch already appears in a published benchmark.

This is a producer-side responsibility: the producer knows the gold patch
and instance IDs. Downstream consumers can then stratify or exclude
overlapping instances without re-running the pipeline.

Reference paths are specified as ``"source_name:path/to/file.jsonl"``
strings in ``config.decontam_reference_paths``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Diff-header lines to strip during normalisation
_DIFF_HEADER_RE = re.compile(
    r"^(diff --git|index |--- |\\+\\+\\+ |@@ |new file|deleted file|old mode|new mode)",
    re.MULTILINE,
)


class DecontaminationChecker:
    """Checks TaskInstance fields against one or more JSONL reference sets.

    Each reference is specified as ``"source_name:path"`` where *source_name*
    is returned in the overlap result (e.g. ``"swe-bench"``).

    The check is O(1) per instance — all reference data is loaded into
    in-memory sets on construction.
    """

    def __init__(self, reference_paths: list[str]) -> None:
        """
        Args:
            reference_paths: List of ``"source_name:path"`` strings.
                Each JSONL file is expected to have ``instance_id`` and
                ``patch`` fields per line.
        """
        # Maps source_name → (set of instance_ids, set of patch hashes)
        self._sources: dict[str, tuple[set[str], set[str]]] = {}
        for ref in reference_paths:
            self._load_reference(ref)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, instance_id: str, patch: str | None) -> tuple[bool, str | None]:
        """Check a single instance against all loaded reference sets.

        Args:
            instance_id: The ``instance_id`` field of the emitted instance.
            patch: The gold patch text.

        Returns:
            ``(overlap, source_name)`` where *source_name* is the label of
            the first reference set that matched, or ``None`` if no overlap.
        """
        patch_hash = self._hash_patch(patch or "")
        for source, (ids, hashes) in self._sources.items():
            if instance_id in ids or patch_hash in hashes:
                return True, source
        return False, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_reference(self, ref: str) -> None:
        """Parse ``"source_name:path"`` and load the JSONL into memory."""
        if ":" not in ref:
            logger.warning("Skipping malformed decontam reference (no colon): %r", ref)
            return
        source_name, path_str = ref.split(":", 1)
        path = Path(path_str)
        if not path.exists():
            logger.warning("Decontam reference file not found: %s", path)
            return

        ids: set[str] = set()
        hashes: set[str] = set()
        loaded = 0
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    iid = row.get("instance_id")
                    if iid:
                        ids.add(iid)
                    patch = row.get("patch") or row.get("model_patch")
                    if patch:
                        hashes.add(self._hash_patch(patch))
                    loaded += 1
        except OSError as exc:
            logger.error("Failed to load decontam reference %s: %s", path, exc)
            return

        self._sources[source_name] = (ids, hashes)
        logger.info(
            "Decontam: loaded %d instances from %s (%d unique patches)",
            loaded, source_name, len(hashes),
        )

    @staticmethod
    def _normalize_patch(patch: str) -> str:
        """Strip diff headers and normalise whitespace for stable comparison.

        Two patches that apply the same code change but differ only in
        file paths or index hashes will produce the same normalised form.
        """
        # Keep only +/- content lines; discard headers and @@ lines
        lines = []
        for line in patch.splitlines():
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                lines.append(line.rstrip())
        return "\n".join(lines)

    @classmethod
    def _hash_patch(cls, patch: str) -> str:
        normalised = cls._normalize_patch(patch)
        return hashlib.sha256(normalised.encode()).hexdigest()
