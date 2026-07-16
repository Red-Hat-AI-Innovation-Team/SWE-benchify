#!/usr/bin/env python3
"""Compute FAIL_TO_PASS and PASS_TO_PASS for Harbor task directories.

Runs each task's tests in its Docker image twice: once with the bug present
(pre-fix) and once after applying the gold patch (post-fix). Tests that flip
from fail to pass are FAIL_TO_PASS; tests that stay passing are PASS_TO_PASS.

Instances where the gold patch causes regressions (PASS_TO_FAIL) are flagged
for removal.

Usage:
    python scripts/compute_test_lists.py --tasks-dir data/harbor-synthetic-go/harbor-tasks
    python scripts/compute_test_lists.py --tasks-dir data/harbor-synthetic-go/harbor-tasks --task grpc__grpc-go-90276
    python scripts/compute_test_lists.py --tasks-dir data/harbor-synthetic-go/harbor-tasks --oracle
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOCKER = os.environ.get("DOCKER_PATH", "docker")
PHASE_SEP = "===SWEBENCHIFY_PHASE_SEPARATOR==="


def _docker_available() -> bool:
    try:
        r = subprocess.run([DOCKER, "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _parse_task_toml(task_dir: Path) -> dict:
    """Extract docker_image and test command info from task.toml."""
    toml_path = task_dir / "task.toml"
    content = toml_path.read_text()
    result = {}
    m = re.search(r'docker_image\s*=\s*"([^"]+)"', content)
    if m:
        result["docker_image"] = m.group(1)
    m = re.search(r'instance_id\s*=\s*"([^"]+)"', content)
    if m:
        result["instance_id"] = m.group(1)
    m = re.search(r'repo\s*=\s*"([^"]+)"', content)
    if m:
        result["repo"] = m.group(1)
    return result


def _extract_test_command(test_sh: str) -> str:
    """Extract the test command from test.sh content.

    Looks for the command between 'Start Test Output' and the log file redirect.
    """
    for line in test_sh.splitlines():
        line = line.strip()
        if line.startswith("$") or line.startswith("(cd "):
            cleaned = line.replace("$$", "$")
            if "LOG_FILE" in cleaned:
                cleaned = re.sub(r'\s*>\s*"\$LOG_FILE".*', "", cleaned)
            if "go test" in cleaned or "pytest" in cleaned or "cargo test" in cleaned:
                return cleaned
    return "go test -v -count=1 ./..."


def _make_f2p_script(test_command: str) -> str:
    """Generate a script that runs tests pre-fix and post-fix."""
    return f"""set -uxo pipefail
cd /testbed
git config --global --add safe.directory /testbed

echo '{PHASE_SEP}_PRE'
{test_command} 2>&1 || true

echo '{PHASE_SEP}_POST'
git apply --3way /tmp/gold.patch 2>&1 || git apply /tmp/gold.patch 2>&1 || {{ echo GOLD_PATCH_FAILED; exit 0; }}
{test_command} 2>&1 || true
"""


def _parse_go_test_results(output: str) -> dict[str, str]:
    """Parse Go test verbose output into {test_name: 'passed'|'failed'}."""
    results = {}
    for line in output.splitlines():
        m = re.match(r"--- (PASS|FAIL): (\S+)", line)
        if m:
            results[m.group(2)] = "passed" if m.group(1) == "PASS" else "failed"
    return results


def _extract_section(text: str, start: str, end: str | None) -> str:
    """Extract text between two markers."""
    idx = text.find(start)
    if idx == -1:
        return ""
    idx += len(start)
    if end:
        end_idx = text.find(end, idx)
        if end_idx != -1:
            return text[idx:end_idx]
    return text[idx:]


def compute_test_lists(task_dir: Path, timeout: int = 600) -> dict:
    """Compute F2P/P2P for a single Harbor task.

    Returns a dict with keys: instance_id, FAIL_TO_PASS, PASS_TO_PASS,
    PASS_TO_FAIL, status, error.
    """
    task_info = _parse_task_toml(task_dir)
    instance_id = task_info.get("instance_id", task_dir.name)
    docker_image = task_info.get("docker_image")

    if not docker_image:
        return {
            "instance_id": instance_id,
            "status": "error",
            "error": "No docker_image in task.toml",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "PASS_TO_FAIL": [],
        }

    test_sh_path = task_dir / "tests" / "test.sh"
    gold_patch_path = task_dir / "solution" / "patch.diff"
    test_patch_path = task_dir / "tests" / "test.patch"

    if not test_sh_path.exists():
        return {
            "instance_id": instance_id,
            "status": "error",
            "error": "Missing tests/test.sh",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "PASS_TO_FAIL": [],
        }

    test_command = _extract_test_command(test_sh_path.read_text())
    gold_patch = gold_patch_path.read_text() if gold_patch_path.exists() else ""
    test_patch = test_patch_path.read_text() if test_patch_path.exists() else ""

    if not gold_patch.strip():
        return {
            "instance_id": instance_id,
            "status": "error",
            "error": "Empty gold patch",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "PASS_TO_FAIL": [],
        }

    script = _make_f2p_script(test_command)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        script_path = tmp / "run.sh"
        script_path.write_text(script)
        gold_path = tmp / "gold.patch"
        gold_path.write_text(gold_patch)
        test_p = tmp / "test.patch"
        test_p.write_text(test_patch)

        # Run in Docker: mount the script and patches, apply test patch first
        # The test.patch needs to be applied before running pre-fix tests
        # (the test patch adds tests that catch the bug)
        apply_test_patch = ""
        if test_patch.strip():
            apply_test_patch = (
                "git apply --3way /tmp/test.patch 2>&1 || "
                "git apply /tmp/test.patch 2>&1 || true; "
            )

        cmd = [
            DOCKER, "run", "--rm",
            "-v", f"{script_path}:/tmp/run.sh:ro",
            "-v", f"{gold_path}:/tmp/gold.patch:ro",
            "-v", f"{test_p}:/tmp/test.patch:ro",
            docker_image,
            "bash", "-c",
            f"cd /testbed && git config --global --add safe.directory /testbed && "
            f"{apply_test_patch}"
            f"bash /tmp/run.sh",
        ]

        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            raw_output = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return {
                "instance_id": instance_id,
                "status": "error",
                "error": f"Docker run timed out after {timeout}s",
                "FAIL_TO_PASS": [],
                "PASS_TO_PASS": [],
                "PASS_TO_FAIL": [],
            }

    if "GOLD_PATCH_FAILED" in raw_output:
        return {
            "instance_id": instance_id,
            "status": "error",
            "error": "Gold patch failed to apply",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "PASS_TO_FAIL": [],
        }

    pre_output = _extract_section(raw_output, f"{PHASE_SEP}_PRE", f"{PHASE_SEP}_POST")
    post_output = _extract_section(raw_output, f"{PHASE_SEP}_POST", None)

    pre_results = _parse_go_test_results(pre_output)
    post_results = _parse_go_test_results(post_output)

    if not pre_results and not post_results:
        return {
            "instance_id": instance_id,
            "status": "error",
            "error": "No test results parsed from output",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "PASS_TO_FAIL": [],
            "raw_output": raw_output[-2000:],
        }

    pre_failed = {t for t, s in pre_results.items() if s == "failed"}
    pre_passed = {t for t, s in pre_results.items() if s == "passed"}
    post_passed = {t for t, s in post_results.items() if s == "passed"}
    post_failed = {t for t, s in post_results.items() if s == "failed"}

    fail_to_pass = sorted(pre_failed & post_passed)
    pass_to_pass = sorted(pre_passed & post_passed)
    pass_to_fail = sorted(pre_passed & post_failed)

    status = "valid" if fail_to_pass else "invalid"
    if pass_to_fail:
        status = "regression"

    return {
        "instance_id": instance_id,
        "status": status,
        "FAIL_TO_PASS": fail_to_pass,
        "PASS_TO_PASS": pass_to_pass,
        "PASS_TO_FAIL": pass_to_fail,
    }


def update_config_json(task_dir: Path, f2p: list[str], p2p: list[str]) -> None:
    """Write updated FAIL_TO_PASS and PASS_TO_PASS to config.json."""
    config_path = task_dir / "tests" / "config.json"
    config = json.loads(config_path.read_text())
    config["FAIL_TO_PASS"] = json.dumps(f2p)
    config["PASS_TO_PASS"] = json.dumps(p2p)
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute FAIL_TO_PASS / PASS_TO_PASS for Harbor tasks"
    )
    parser.add_argument("--tasks-dir", required=True, help="Harbor tasks directory")
    parser.add_argument("--task", default=None, help="Run for a single task (instance_id)")
    parser.add_argument("--timeout", type=int, default=600, help="Docker timeout per task (seconds)")
    parser.add_argument("--update", action="store_true", help="Write results to config.json")
    parser.add_argument("--oracle", action="store_true",
                        help="Verify that applying gold patch yields reward=1")
    args = parser.parse_args()

    if not _docker_available():
        print("Error: Docker is not available", file=sys.stderr)
        sys.exit(1)

    tasks_dir = Path(args.tasks_dir)
    if not tasks_dir.exists():
        print(f"Error: {tasks_dir} not found", file=sys.stderr)
        sys.exit(1)

    if args.task:
        task_dirs = [tasks_dir / args.task]
        if not task_dirs[0].exists():
            print(f"Error: task {args.task} not found in {tasks_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        task_dirs = sorted(
            d for d in tasks_dir.iterdir()
            if d.is_dir() and (d / "task.toml").exists()
        )

    print(f"Processing {len(task_dirs)} tasks...\n")

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name}...", end=" ", flush=True)
        result = compute_test_lists(task_dir, timeout=args.timeout)
        results.append(result)

        status = result["status"]
        f2p = result["FAIL_TO_PASS"]
        p2p = result["PASS_TO_PASS"]
        p2f = result["PASS_TO_FAIL"]

        if status == "valid":
            print(f"OK (F2P={len(f2p)}, P2P={len(p2p)})")
            if args.update:
                update_config_json(task_dir, f2p, p2p)
        elif status == "regression":
            print(f"REGRESSION (F2P={len(f2p)}, P2P={len(p2p)}, P2F={len(p2f)})")
            print(f"  -> P2F tests: {p2f}")
            if args.update:
                update_config_json(task_dir, f2p, p2p)
        elif status == "invalid":
            print("INVALID (no F2P tests)")
        else:
            print(f"ERROR: {result.get('error', 'unknown')}")

    print(f"\n{'='*60}")
    valid = [r for r in results if r["status"] == "valid"]
    regression = [r for r in results if r["status"] == "regression"]
    invalid = [r for r in results if r["status"] == "invalid"]
    error = [r for r in results if r["status"] == "error"]

    print(f"Valid:      {len(valid)}")
    print(f"Regression: {len(regression)} (gold patch breaks tests — DROP these)")
    print(f"Invalid:    {len(invalid)} (no F2P tests)")
    print(f"Error:      {len(error)}")

    if regression:
        print("\nInstances to drop:")
        for r in regression:
            print(f"  {r['instance_id']}: P2F={r['PASS_TO_FAIL']}")

    if args.update:
        print(f"\nUpdated config.json for {len(valid) + len(regression)} tasks")

    report_path = tasks_dir / "test-lists-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
