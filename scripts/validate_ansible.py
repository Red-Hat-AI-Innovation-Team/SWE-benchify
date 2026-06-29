#!/usr/bin/env python3
"""Validate Ansible pytest-compatible candidates via local Docker.

Filters ansible__ansible-candidates.jsonl to the ~33 candidates with
pytest unit tests (test/units/*.py), creates an EnvironmentSpec, and
runs compute_f2p() locally for each candidate.

Usage:
    python scripts/validate_ansible.py [--dry-run] [--timeout 600] [--n-runs 1]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from swebenchify.grader import compute_f2p
from swebenchify.models import CandidateInstance, EnvironmentSpec, ValidationResult
from swebenchify.remote import build_task_instances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CANDIDATES_PATH = Path("output/ansible/ansible__ansible-candidates.jsonl")
OUTPUT_PATH = Path("output/ansible/ansible__ansible-task-instances.jsonl")

ANSIBLE_ENV_SPEC = EnvironmentSpec(
    language="python",
    language_version="3.13",
    package_manager="pip",
    install_cmd="pip install -e .",
    test_cmd="pytest",
    pre_install=[
        "pip install -r test/lib/ansible_test/_data/requirements/units.txt",
        "pip install -r test/units/requirements.txt",
    ],
    pip_packages=[],
    system_dependencies=[],
)


def _has_pytest_unit_tests(test_patch: str) -> bool:
    """True if test_patch modifies .py files under test/units/."""
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        if "test/units/" in line and ".py" in line:
            return True
    return False


def load_and_filter(path: Path) -> list[CandidateInstance]:
    candidates = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            c = CandidateInstance(**data)
            if not c.patch or not c.test_patch:
                continue
            if _has_pytest_unit_tests(c.test_patch):
                candidates.append(c)
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Ansible candidates via GHA")
    parser.add_argument("--dry-run", action="store_true", help="Filter and print stats only")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per test phase (seconds)")
    parser.add_argument("--n-runs", type=int, default=1, help="Number of validation runs for flake quarantine")
    parser.add_argument("--input", type=str, default=str(CANDIDATES_PATH))
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args(argv)

    candidates = load_and_filter(Path(args.input))
    logger.info("Filtered to %d pytest-compatible candidates", len(candidates))

    if not candidates:
        logger.warning("No pytest-compatible candidates found")
        return 1

    for c in candidates[:5]:
        logger.info("  %s", c.instance_id)
    if len(candidates) > 5:
        logger.info("  ... and %d more", len(candidates) - 5)

    if args.dry_run:
        logger.info("Dry run — not validating. Would validate %d candidates.", len(candidates))
        return 0

    logger.info("Validating %d candidates locally via Docker...", len(candidates))
    results: dict[str, ValidationResult] = {}

    for i, c in enumerate(candidates, 1):
        logger.info("[%d/%d] Validating %s ...", i, len(candidates), c.instance_id)
        try:
            result = compute_f2p(
                repo=c.repo,
                base_commit=c.base_commit,
                test_patch=c.test_patch or "",
                gold_patch=c.patch or "",
                env_spec=ANSIBLE_ENV_SPEC,
                timeout=args.timeout,
                n_runs=args.n_runs,
            )
        except Exception as exc:
            logger.error("  %s failed: %s", c.instance_id, exc)
            result = ValidationResult(status="error", error_message=str(exc))
        results[c.instance_id] = result
        logger.info("  %s -> %s (f2p=%d)", c.instance_id, result.status, len(result.FAIL_TO_PASS))

    valid = sum(1 for v in results.values() if v.status == "valid")
    invalid = sum(1 for v in results.values() if v.status == "invalid")
    errors = sum(1 for v in results.values() if v.status == "error")
    logger.info("Results: %d valid, %d invalid, %d errors (of %d)", valid, invalid, errors, len(results))

    instances = build_task_instances(candidates, results, ANSIBLE_ENV_SPEC)
    logger.info("Built %d task instances", len(instances))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for inst in instances:
            f.write(json.dumps(asdict(inst)) + "\n")
    logger.info("Wrote %d instances to %s", len(instances), output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
