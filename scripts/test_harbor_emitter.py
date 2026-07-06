#!/usr/bin/env python3
"""Verify the Harbor emitter with real Go TaskInstance data.

Loads Go instances from output/go-v1/all-task-instances.jsonl,
runs them through emit_harbor_dataset(), and validates the output.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

# tomllib is stdlib in 3.11+; fall back to tomli
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# Ensure the project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swebenchify.harbor_emitter import emit_harbor_dataset
from swebenchify.models import TaskInstance


JSONL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "output", "go-v1", "all-task-instances.jsonl"
)

EXPECTED_FILES = [
    "instruction.md",
    "task.toml",
    "environment/Dockerfile",
    "solution/solve.sh",
    "tests/test.sh",
    "tests/config.json",
    "tests/test.patch",
]


def load_instances(path: str) -> list[TaskInstance]:
    instances: list[TaskInstance] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            # Filter to fields the TaskInstance constructor accepts
            import dataclasses

            valid_fields = {field.name for field in dataclasses.fields(TaskInstance)}
            filtered = {k: v for k, v in raw.items() if k in valid_fields}
            instances.append(TaskInstance(**filtered))
    return instances


def validate_task_dir(task_dir: str, instance_id: str) -> list[str]:
    """Validate a single task directory. Returns list of error messages."""
    errors: list[str] = []

    # Check all expected files exist
    for rel_path in EXPECTED_FILES:
        full = os.path.join(task_dir, rel_path)
        if not os.path.isfile(full):
            errors.append(f"  MISSING: {rel_path}")

    # Validate task.toml is valid TOML
    toml_path = os.path.join(task_dir, "task.toml")
    if os.path.isfile(toml_path):
        try:
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)
            if "task" not in toml_data:
                errors.append("  task.toml: missing [task] section")
        except Exception as e:
            errors.append(f"  task.toml: INVALID TOML — {e}")

    # Validate test.sh
    test_sh_path = os.path.join(task_dir, "tests", "test.sh")
    if os.path.isfile(test_sh_path):
        content = open(test_sh_path).read()
        if "go test" not in content:
            errors.append("  test.sh: missing 'go test' command")
        if "/logs/verifier/reward.txt" not in content:
            errors.append("  test.sh: missing reward.txt write")
        if not os.access(test_sh_path, os.X_OK):
            errors.append("  test.sh: not executable")

    # Validate solve.sh contains patch content
    solve_sh_path = os.path.join(task_dir, "solution", "solve.sh")
    if os.path.isfile(solve_sh_path):
        content = open(solve_sh_path).read()
        if "diff" not in content and "patch" not in content.lower() and "---" not in content:
            errors.append("  solve.sh: doesn't appear to contain a patch")
        if not os.access(solve_sh_path, os.X_OK):
            errors.append("  solve.sh: not executable")

    # Validate Dockerfile
    dockerfile_path = os.path.join(task_dir, "environment", "Dockerfile")
    if os.path.isfile(dockerfile_path):
        content = open(dockerfile_path).read()
        if "golang" not in content.lower():
            errors.append("  Dockerfile: missing golang base image reference")

    # Validate config.json
    config_path = os.path.join(task_dir, "tests", "config.json")
    if os.path.isfile(config_path):
        try:
            config = json.loads(open(config_path).read())
            if "FAIL_TO_PASS" not in config:
                errors.append("  config.json: missing FAIL_TO_PASS")
            if "PASS_TO_PASS" not in config:
                errors.append("  config.json: missing PASS_TO_PASS")
        except json.JSONDecodeError as e:
            errors.append(f"  config.json: INVALID JSON — {e}")

    # Validate test.patch
    test_patch_path = os.path.join(task_dir, "tests", "test.patch")
    if os.path.isfile(test_patch_path):
        content = open(test_patch_path).read()
        if not content.strip():
            errors.append("  test.patch: empty file")

    return errors


def main() -> None:
    print("=" * 70)
    print("Harbor Emitter Verification — Real Go Data")
    print("=" * 70)

    # Step 1: Load instances
    if not os.path.isfile(JSONL_PATH):
        print(f"\nERROR: JSONL file not found: {JSONL_PATH}")
        sys.exit(1)

    instances = load_instances(JSONL_PATH)
    print(f"\nLoaded {len(instances)} TaskInstances from {JSONL_PATH}")
    for inst in instances:
        f2p = json.loads(inst.FAIL_TO_PASS) if inst.FAIL_TO_PASS else []
        p2p = json.loads(inst.PASS_TO_PASS) if inst.PASS_TO_PASS else []
        print(f"  - {inst.instance_id} (repo={inst.repo}, lang={inst.repo_language}, "
              f"F2P={len(f2p)}, P2P={len(p2p)})")

    # Step 2: Run through emit_harbor_dataset
    output_dir = os.path.join(
        os.path.dirname(__file__), "..", "output", "harbor-verify"
    )
    # Clean previous run
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)

    print(f"\nRunning emit_harbor_dataset() → {output_dir}")
    emit_harbor_dataset(instances, output_dir)

    harbor_dir = os.path.join(output_dir, "harbor-tasks")
    if not os.path.isdir(harbor_dir):
        print("ERROR: harbor-tasks directory was not created!")
        sys.exit(1)

    # Step 3: Validate each task directory
    print(f"\n{'=' * 70}")
    print("Validation Results")
    print("=" * 70)

    task_dirs = sorted(os.listdir(harbor_dir))
    # Filter out registry/dataset files
    task_dirs = [d for d in task_dirs if os.path.isdir(os.path.join(harbor_dir, d))]

    total_errors = 0
    for dirname in task_dirs:
        task_path = os.path.join(harbor_dir, dirname)
        errors = validate_task_dir(task_path, dirname)
        if errors:
            print(f"\n[FAIL] {dirname}")
            for err in errors:
                print(err)
            total_errors += len(errors)
        else:
            print(f"[PASS] {dirname}")

    # Step 4: Check supplementary files
    print(f"\n{'=' * 70}")
    print("Supplementary Files")
    print("=" * 70)

    registry_path = os.path.join(harbor_dir, "registry.json")
    if os.path.isfile(registry_path):
        reg = json.loads(open(registry_path).read())
        print(f"  registry.json: {len(reg)} entries")
    else:
        print("  registry.json: MISSING")
        total_errors += 1

    dataset_path = os.path.join(harbor_dir, "dataset.toml")
    if os.path.isfile(dataset_path):
        with open(dataset_path, "rb") as f:
            ds = tomllib.load(f)
        ds_info = ds.get("dataset", {})
        print(f"  dataset.toml: task_count={ds_info.get('task_count')}, "
              f"languages={ds_info.get('languages')}, repos={ds_info.get('repos')}")
    else:
        print("  dataset.toml: MISSING")
        total_errors += 1

    # Step 5: Print directory tree
    print(f"\n{'=' * 70}")
    print("Generated Directory Tree")
    print("=" * 70)
    for dirname in task_dirs:
        task_path = os.path.join(harbor_dir, dirname)
        print(f"\n  {dirname}/")
        for root, dirs, files in sorted(os.walk(task_path)):
            level = root.replace(task_path, "").count(os.sep)
            indent = "    " + "  " * level
            subdir = os.path.basename(root)
            if level > 0:
                print(f"{indent}{subdir}/")
            for fname in sorted(files):
                fpath = os.path.join(root, fname)
                size = os.path.getsize(fpath)
                print(f"{indent}  {fname} ({size:,} bytes)")

    # Step 6: Show sample content from one task
    if task_dirs:
        sample = task_dirs[0]
        sample_path = os.path.join(harbor_dir, sample)
        print(f"\n{'=' * 70}")
        print(f"Sample Content — {sample}")
        print("=" * 70)

        for fname in ["task.toml", "tests/test.sh"]:
            fpath = os.path.join(sample_path, fname)
            if os.path.isfile(fpath):
                print(f"\n--- {fname} ---")
                content = open(fpath).read()
                # Truncate long files
                if len(content) > 2000:
                    print(content[:2000])
                    print(f"  ... ({len(content)} bytes total, truncated)")
                else:
                    print(content)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"  Instances loaded:  {len(instances)}")
    print(f"  Task dirs created: {len(task_dirs)}")
    print(f"  Validation errors: {total_errors}")
    if total_errors == 0:
        print("\n  ALL CHECKS PASSED")
    else:
        print(f"\n  {total_errors} ERROR(S) FOUND")
        sys.exit(1)


if __name__ == "__main__":
    main()
