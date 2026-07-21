#!/usr/bin/env python3
"""Validate an enriched instance and package it as a Harbor task.

Runs tests natively (no Docker required) to compute FAIL_TO_PASS and
PASS_TO_PASS, then generates the Harbor task directory structure.

Designed to run in a cluster pod where the language toolchain (Go, etc.)
is already installed, or locally for testing.

Usage:
    # With an already-cloned repo:
    python scripts/validate_and_prepare.py \
        --input enriched-instance.jsonl \
        --output /output \
        --repo-dir /tmp/repo

    # Clone the repo automatically:
    python scripts/validate_and_prepare.py \
        --input enriched-instance.jsonl \
        --output /output \
        --repo-url grpc/grpc-go
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swebenchify.harbor_emitter import (  # noqa: E402
    _build_go_test_command,
    emit_harbor_dataset,
)
from swebenchify.models import TaskInstance  # noqa: E402


def _parse_go_test_results(output: str) -> dict[str, str]:
    """Parse Go test verbose output into {test_name: 'passed'|'failed'}.

    Also detects panics — when a test panics, Go doesn't emit ``--- FAIL:``
    but the overall package fails with ``FAIL\\tpkg``.  We attribute the panic
    to the last ``=== RUN`` test name seen.
    """
    results = {}
    last_run = None
    has_panic = False
    for line in output.splitlines():
        m = re.search(r"--- (PASS|FAIL): (\S+)", line)
        if m:
            results[m.group(2)] = "passed" if m.group(1) == "PASS" else "failed"
            continue
        run_m = re.match(r"=== RUN\s+(\S+)", line)
        if run_m:
            last_run = run_m.group(1)
        if "panic:" in line or "runtime error:" in line:
            has_panic = True
    if has_panic and last_run and last_run not in results:
        results[last_run] = "failed"
    return results


def _run(cmd: list[str], cwd: str | Path | None = None,
         timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout,
    )


def _clone_repo(repo_url: str, base_commit: str, dest: Path,
                timeout: int = 300) -> None:
    """Clone a GitHub repo at a specific commit."""
    url = f"https://github.com/{repo_url}.git"
    r = _run(["git", "clone", "--depth", "50", url, str(dest)], timeout=timeout)
    if r.returncode != 0:
        r = _run(["git", "clone", url, str(dest)], timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"git clone failed: {r.stderr[-500:]}")

    r = _run(["git", "checkout", base_commit], cwd=dest)
    if r.returncode != 0:
        # Shallow clone may not have this commit — fetch it
        _run(["git", "fetch", "--unshallow"], cwd=dest, timeout=timeout)
        r = _run(["git", "checkout", base_commit], cwd=dest)
        if r.returncode != 0:
            _run(["git", "fetch", "origin", base_commit], cwd=dest, timeout=120)
            r = _run(["git", "checkout", base_commit], cwd=dest)
            if r.returncode != 0:
                raise RuntimeError(
                    f"git checkout {base_commit} failed: {r.stderr[-500:]}"
                )

    _run(["git", "config", "--global", "--add", "safe.directory", str(dest)],
         cwd=dest)


def _fix_repo_field(raw: str) -> str:
    """Convert local path like 'data/yield-sweep-22/clones/grpc__grpc-go' to 'grpc/grpc-go'."""
    if "/" not in raw or raw.count("/") == 1:
        return raw
    slug = raw.rstrip("/").split("/")[-1]
    parts = slug.split("__", 1)
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return raw


def _fix_instance_id(raw: str, repo: str) -> str:
    """Fix local-path instance IDs to use the repo slug."""
    if raw.startswith("data__") or raw.startswith("local__"):
        m = re.search(r"-(\d+)$", raw)
        num = m.group(1) if m else "0"
        slug = repo.replace("/", "__")
        return f"{slug}-{num}"
    return raw


def validate_instance(
    instance: dict,
    repo_dir: Path,
    language: str = "go",
    test_timeout: int = 300,
    bug_baked_in: bool = False,
) -> dict:
    """Validate a single enriched instance by running tests natively.

    When bug_baked_in=True (synthetic instances), the repo at base_commit
    already contains the bug — skip the reverse-apply step.

    Returns a result dict with status, FAIL_TO_PASS, PASS_TO_PASS, PASS_TO_FAIL.
    """
    instance_id = instance.get("instance_id", "unknown")
    patch = instance.get("patch", "")
    test_patch = instance.get("test_patch", "")

    if not patch.strip():
        return {"instance_id": instance_id, "status": "error",
                "error": "Empty gold patch"}

    if language == "go":
        test_command = _build_go_test_command(test_patch)
    else:
        return {"instance_id": instance_id, "status": "error",
                "error": f"Unsupported language: {language}"}

    _run(["git", "config", "--global", "--add", "safe.directory",
          str(repo_dir)], cwd=repo_dir)

    if language == "go":
        print("  Installing Go dependencies...", flush=True)
        _run(["go", "mod", "download"], cwd=repo_dir, timeout=120)

    # Phase 1: Introduce the bug (if not already present)
    if bug_baked_in:
        print("  Bug already baked in at base_commit (synthetic instance)",
              flush=True)
    else:
        print("  Reverse-applying gold patch...", flush=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch",
                                         delete=False) as f:
            f.write(patch)
            patch_file = f.name
        r = _run(["git", "apply", "--reverse", patch_file], cwd=repo_dir)
        if r.returncode != 0:
            r = _run(["git", "apply", "--reverse", "--3way", patch_file],
                      cwd=repo_dir)
        os.unlink(patch_file)
        if r.returncode != 0:
            return {"instance_id": instance_id, "status": "error",
                    "error": f"Reverse gold patch failed: {r.stderr[-300:]}"}

    # Apply test patch if present
    if test_patch.strip():
        print("  Applying test patch...", flush=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch",
                                         delete=False) as f:
            f.write(test_patch)
            tp_file = f.name
        r = _run(["git", "apply", tp_file], cwd=repo_dir)
        if r.returncode != 0:
            _run(["git", "apply", "--3way", tp_file], cwd=repo_dir)
        os.unlink(tp_file)

    # Phase 2: Run tests (pre-fix — bug is present)
    print(f"  Running pre-fix tests: {test_command}", flush=True)
    r = _run(["bash", "-c", f"cd {repo_dir} && {test_command}"],
             timeout=test_timeout)
    pre_output = (r.stdout or "") + (r.stderr or "")
    pre_results = _parse_go_test_results(pre_output)
    print(f"  Pre-fix: {len(pre_results)} tests parsed "
          f"({sum(1 for v in pre_results.values() if v == 'failed')} failed, "
          f"{sum(1 for v in pre_results.values() if v == 'passed')} passed)",
          flush=True)

    # Phase 3: Apply gold patch (fix the bug)
    print("  Applying gold patch...", flush=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch",
                                     delete=False) as f:
        f.write(patch)
        patch_file = f.name
    r = _run(["git", "apply", patch_file], cwd=repo_dir)
    if r.returncode != 0:
        r = _run(["git", "apply", "--3way", patch_file], cwd=repo_dir)
        if r.returncode != 0:
            os.unlink(patch_file)
            return {"instance_id": instance_id, "status": "error",
                    "error": f"Gold patch failed: {r.stderr[-300:]}"}
    os.unlink(patch_file)

    # Phase 4: Run tests (post-fix — bug is fixed)
    print(f"  Running post-fix tests: {test_command}", flush=True)
    r = _run(["bash", "-c", f"cd {repo_dir} && {test_command}"],
             timeout=test_timeout)
    post_output = (r.stdout or "") + (r.stderr or "")
    post_results = _parse_go_test_results(post_output)
    print(f"  Post-fix: {len(post_results)} tests parsed "
          f"({sum(1 for v in post_results.values() if v == 'failed')} failed, "
          f"{sum(1 for v in post_results.values() if v == 'passed')} passed)",
          flush=True)

    # Phase 5: Compute F2P / P2P / P2F
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate enriched instance and generate Harbor task"
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to enriched JSONL (single instance)")
    parser.add_argument("--output", "-o", required=True,
                        help="Output directory for Harbor task")
    parser.add_argument("--repo-dir", default=None,
                        help="Path to already-cloned repo")
    parser.add_argument("--repo-url", default=None,
                        help="GitHub repo (owner/name) to clone")
    parser.add_argument("--language", default=None,
                        help="Language (default: from _pipeline.language or 'go')")
    parser.add_argument("--test-timeout", type=int, default=300,
                        help="Timeout for each test run in seconds")
    parser.add_argument("--clone-timeout", type=int, default=300,
                        help="Timeout for git clone in seconds")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    lines = [line.strip() for line in input_path.read_text().splitlines() if line.strip()]
    if not lines:
        print("Error: empty input file", file=sys.stderr)
        sys.exit(1)

    instance = json.loads(lines[0])
    pipeline = instance.get("_pipeline", {})
    language = args.language or pipeline.get("language", "go")

    repo = _fix_repo_field(instance.get("repo", ""))
    instance["repo"] = repo
    instance["instance_id"] = _fix_instance_id(
        instance.get("instance_id", ""), repo
    )
    instance_id = instance["instance_id"]

    print(f"Validating {instance_id} ({repo}, {language})", flush=True)

    # Determine repo directory
    if args.repo_dir:
        source_repo = Path(args.repo_dir)
        if not source_repo.exists():
            print(f"Error: repo dir {source_repo} not found", file=sys.stderr)
            sys.exit(1)
        # Copy to a temp directory so we don't modify the source
        repo_dir = Path(tempfile.mkdtemp(prefix="val-repo-"))
        print(f"  Copying repo to {repo_dir}...", flush=True)
        shutil.copytree(source_repo, repo_dir, dirs_exist_ok=True)
        # Checkout the base commit
        _run(["git", "checkout", instance["base_commit"]], cwd=repo_dir)
    elif args.repo_url or "/" in repo:
        repo_url = args.repo_url or repo
        repo_dir = Path("/tmp/testbed")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        print(f"  Cloning {repo_url}...", flush=True)
        try:
            _clone_repo(repo_url, instance["base_commit"], repo_dir,
                        timeout=args.clone_timeout)
        except RuntimeError as e:
            status = {"instance_id": instance_id, "status": "error",
                      "error": str(e)}
            print(f"RESULT: {json.dumps(status)}")
            sys.exit(1)
    else:
        print("Error: provide --repo-dir or --repo-url", file=sys.stderr)
        sys.exit(1)

    # Synthetic instances have the bug baked in at base_commit
    bug_baked_in = instance.get("provenance") == "synthetic"

    # Run validation
    result = validate_instance(
        instance, repo_dir, language=language,
        test_timeout=args.test_timeout,
        bug_baked_in=bug_baked_in,
    )

    print(f"\nValidation result: {result['status']}", flush=True)
    print(f"  F2P: {result.get('FAIL_TO_PASS', [])}", flush=True)
    print(f"  P2P: {len(result.get('PASS_TO_PASS', []))} tests", flush=True)
    if result.get("PASS_TO_FAIL"):
        print(f"  P2F: {result['PASS_TO_FAIL']}", flush=True)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write validation result
    status_path = output_dir / "validation-result.json"
    status_path.write_text(json.dumps(result, indent=2) + "\n")

    if result["status"] != "valid":
        print(f"RESULT: {json.dumps(result)}")
        if result["status"] == "error":
            sys.exit(1)
        sys.exit(0)

    # Populate F2P/P2P on the instance and generate Harbor task
    instance["FAIL_TO_PASS"] = json.dumps(result["FAIL_TO_PASS"])
    instance["PASS_TO_PASS"] = json.dumps(result["PASS_TO_PASS"])
    instance["repo_language"] = language
    if "version" not in instance or not instance.get("version"):
        instance["version"] = "unknown"

    # Remove internal fields that aren't part of TaskInstance
    import dataclasses
    task_fields = {f.name for f in dataclasses.fields(TaskInstance)}
    filtered = {k: v for k, v in instance.items() if k in task_fields}
    for field in ["hints_text", "created_at"]:
        if field not in filtered:
            filtered[field] = ""

    try:
        task_instance = TaskInstance(**filtered)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Failed to create TaskInstance: {e}"
        print(f"RESULT: {json.dumps(result)}")
        sys.exit(1)

    print(f"\nGenerating Harbor task in {output_dir}...", flush=True)
    emit_harbor_dataset([task_instance], str(output_dir))

    # Verify the generated task has config.json with F2P/P2P
    harbor_dir = output_dir / "harbor-tasks"
    config_path = harbor_dir / instance_id / "tests" / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
        f2p = config.get("FAIL_TO_PASS", "[]")
        if isinstance(f2p, str):
            f2p = json.loads(f2p)
        print(f"  Harbor task generated with {len(f2p)} F2P tests", flush=True)

    result["harbor_task_dir"] = str(harbor_dir / instance_id)
    print(f"RESULT: {json.dumps(result)}")


if __name__ == "__main__":
    main()
