#!/usr/bin/env python3
"""Run a single compute_f2p validation job.

Designed to be called by each GitHub Actions matrix job in the
remote-validate workflow. Reads one entry from a manifest JSONL file
and writes a ValidationResult JSON file.

Usage:
    python scripts/validate_one.py \
        --manifest .remote-validate/manifest.jsonl \
        --index 0 \
        --output result.json \
        [--n-runs 1] \
        [--timeout 300]
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import asdict

from swebenchify.grader import compute_f2p
from swebenchify.models import ValidationResult, deserialize_env_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a single validation job")
    parser.add_argument("--manifest", required=True, help="Path to manifest JSONL")
    parser.add_argument("--index", type=int, required=True, help="Line index in manifest")
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", required=True, help="Output result JSON path")
    args = parser.parse_args(argv)

    with open(args.manifest) as f:
        lines = [line.strip() for line in f if line.strip()]

    if args.index >= len(lines):
        print(f"Index {args.index} out of range (manifest has {len(lines)} entries)")
        return 1

    entry = json.loads(lines[args.index])
    instance_id = entry["instance_id"]
    print(f"Validating {instance_id} ...")

    env_spec_data = entry.get("env_spec") or {}
    env_spec = deserialize_env_spec(env_spec_data) if env_spec_data else None

    try:
        result = compute_f2p(
            repo=entry["repo"],
            base_commit=entry["base_commit"],
            test_patch=entry["test_patch"],
            gold_patch=entry["gold_patch"],
            env_spec=env_spec,
            timeout=args.timeout,
            n_runs=args.n_runs,
        )
    except Exception:
        result = ValidationResult(
            status="error",
            error_message=traceback.format_exc(),
        )

    output = {"instance_id": instance_id, "result": asdict(result)}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Done: {instance_id} -> {result.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
