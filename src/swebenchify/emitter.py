"""Stage 6: JSONL emission.

Serializes validated, filtered instances to SWE-bench-compatible JSONL.
See docs/SPEC.md Section 5.7.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from swebenchify.harbor_emitter import emit_harbor_dataset as emit_harbor_dataset
from swebenchify.models import TaskInstance

logger = logging.getLogger(__name__)

_PRODUCT_MAP_PATH = Path(__file__).parent / "repo_products.json"


def load_product_map(path: str | Path | None = None) -> dict[str, str]:
    """Load the repo → product mapping from a JSON file.

    Args:
        path: Path to the JSON file. Defaults to the bundled
            ``repo_products.json`` in the package directory.

    Returns:
        Dict mapping ``"owner/repo"`` → product name string.
        Returns an empty dict if the file does not exist.
    """
    target = Path(path) if path is not None else _PRODUCT_MAP_PATH
    if not target.exists():
        logger.warning("Product map not found at %s; product column will be null", target)
        return {}
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load product map: %s", exc)
        return {}


def emit_dataset(
    instances: list[TaskInstance],
    output_dir: str,
    repo_slug: str | None = None,
) -> None:
    """Write instances to SWE-bench-compatible JSONL files.

    Writes:
    - {output_dir}/{repo_slug}-task-instances.jsonl (if repo_slug given)
    - {output_dir}/all-task-instances.jsonl (always, appended)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if repo_slug:
        repo_file = output_path / f"{repo_slug}-task-instances.jsonl"
        _write_jsonl(instances, repo_file)
        logger.info("Wrote %d instances to %s", len(instances), repo_file)

    all_file = output_path / "all-task-instances.jsonl"
    existing_ids: set[str] = set()
    if all_file.exists():
        with open(all_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing_ids.add(json.loads(line)["instance_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    new_instances = [i for i in instances if i.instance_id not in existing_ids]
    skipped = len(instances) - len(new_instances)
    if skipped:
        logger.info("Skipped %d duplicate instances already in %s", skipped, all_file)
    _write_jsonl(new_instances, all_file, append=True)
    logger.info("Appended %d instances to %s", len(new_instances), all_file)


def _write_jsonl(
    instances: list[TaskInstance], path: Path, append: bool = False
) -> None:
    mode = "a" if append else "w"
    with open(path, mode) as f:
        for inst in instances:
            f.write(json.dumps(asdict(inst)) + "\n")


def load_dataset(path: str) -> list[dict]:
    """Load a JSONL dataset file. Returns list of dicts."""
    instances: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances
