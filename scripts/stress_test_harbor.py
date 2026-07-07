#!/usr/bin/env python3
"""Comprehensive stress test of the Harbor emitter across multiple languages and repos.

Loads TaskInstance data from all available JSONL files, runs emit_harbor_dataset()
on a representative sample, validates every generated task directory, and optionally
runs Harbor oracle on a subset.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import shutil
import subprocess
import sys
import time

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swebenchify.harbor_emitter import emit_harbor_dataset
from swebenchify.models import TaskInstance

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(ROOT, "output", "harbor-stress-test")
HARBOR_BIN = os.path.expanduser("~/.local/bin/harbor")

JSONL_SOURCES = {
    "go-v1": os.path.join(ROOT, "output", "go-v1", "all-task-instances.jsonl"),
    "rh-v1": os.path.join(ROOT, "output", "rh-v1", "all-task-instances.jsonl"),
    "ansible": os.path.join(ROOT, "output", "ansible", "ansible__ansible-task-instances.jsonl"),
    "swebenchify-dataset": os.path.join(ROOT, "output", "swebenchify-dataset.jsonl"),
}

PYTHON_REPOS = {"pallets/flask", "psf/requests", "ansible/ansible",
                "ansible/ansible-lint", "ansible/molecule"}

EXPECTED_FILES = [
    "instruction.md",
    "task.toml",
    "environment/Dockerfile",
    "solution/solve.sh",
    "tests/test.sh",
    "tests/config.json",
    "tests/test.patch",
]

VALID_FIELDS = {f.name for f in dataclasses.fields(TaskInstance)}


def load_instances(path: str, source_name: str) -> list[TaskInstance]:
    instances: list[TaskInstance] = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            filtered = {k: v for k, v in raw.items() if k in VALID_FIELDS}

            if not filtered.get("repo_language"):
                repo = filtered.get("repo", "")
                if repo in PYTHON_REPOS or any(repo.startswith(p + "/") for p in
                                                ["pallets", "psf", "ansible"]):
                    filtered["repo_language"] = "python"

            try:
                instances.append(TaskInstance(**filtered))
            except TypeError as e:
                print(f"  WARN: {source_name} line {lineno}: {e}")
    return instances


def sample_instances(
    all_instances: dict[str, list[TaskInstance]],
) -> list[TaskInstance]:
    """Select a representative sample across languages and repos."""
    selected: list[TaskInstance] = []
    seen_ids: set[str] = set()

    def add(instances: list[TaskInstance], max_n: int | None = None,
            filter_repo: str | None = None, filter_lang: str | None = None) -> int:
        pool = instances
        if filter_repo:
            pool = [i for i in pool if i.repo == filter_repo]
        if filter_lang:
            pool = [i for i in pool if (i.repo_language or "unknown") == filter_lang]
        count = 0
        for inst in pool:
            if max_n is not None and count >= max_n:
                break
            if inst.instance_id not in seen_ids:
                selected.append(inst)
                seen_ids.add(inst.instance_id)
                count += 1
        return count

    # All 4 Go instances from go-v1
    add(all_instances["go-v1"])

    # 10 Go instances from rh-v1: kubernetes + grpc-go
    rh = all_instances["rh-v1"]
    add(rh, max_n=5, filter_repo="kubernetes/kubernetes")
    add(rh, max_n=5, filter_repo="grpc/grpc-go")

    # 10 Python instances from swebenchify-dataset: flask + requests
    swe = all_instances["swebenchify-dataset"]
    add(swe, max_n=5, filter_repo="pallets/flask")
    add(swe, max_n=5, filter_repo="psf/requests")

    # 5 Python instances from ansible
    add(all_instances["ansible"], max_n=5)

    return selected


def validate_task_dir(task_dir: str, language: str) -> list[str]:
    """Validate a single task directory. Returns list of error messages."""
    errors: list[str] = []

    for rel_path in EXPECTED_FILES:
        full = os.path.join(task_dir, rel_path)
        if not os.path.isfile(full):
            errors.append(f"MISSING: {rel_path}")

    # task.toml
    toml_path = os.path.join(task_dir, "task.toml")
    if os.path.isfile(toml_path):
        try:
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)
            if "task" not in toml_data:
                errors.append("task.toml: missing [task] section")
        except Exception as e:
            errors.append(f"task.toml: INVALID TOML — {e}")

    # test.sh
    test_sh_path = os.path.join(task_dir, "tests", "test.sh")
    if os.path.isfile(test_sh_path):
        content = open(test_sh_path).read()
        if not content.startswith("#!/"):
            errors.append("test.sh: missing shebang")
        if "/logs/verifier/reward.txt" not in content:
            errors.append("test.sh: missing reward.txt write")
        if not os.access(test_sh_path, os.X_OK):
            errors.append("test.sh: not executable")

        if language == "go" and "go test" not in content:
            errors.append("test.sh: Go instance missing 'go test' command")
        if language == "python" and "pytest" not in content:
            errors.append("test.sh: Python instance missing 'pytest' command")

    # solve.sh
    solve_sh_path = os.path.join(task_dir, "solution", "solve.sh")
    if os.path.isfile(solve_sh_path):
        content = open(solve_sh_path).read()
        if "git apply" not in content:
            errors.append("solve.sh: missing 'git apply' (uses patch instead?)")
        if not os.access(solve_sh_path, os.X_OK):
            errors.append("solve.sh: not executable")

    # Dockerfile
    dockerfile_path = os.path.join(task_dir, "environment", "Dockerfile")
    if os.path.isfile(dockerfile_path):
        content = open(dockerfile_path).read()
        if language == "go" and "golang" not in content.lower():
            errors.append("Dockerfile: Go instance missing golang base image")
        if language == "python" and "python" not in content.lower():
            errors.append("Dockerfile: Python instance missing python base image")

    # config.json
    config_path = os.path.join(task_dir, "tests", "config.json")
    if os.path.isfile(config_path):
        try:
            config = json.loads(open(config_path).read())
            if "FAIL_TO_PASS" not in config:
                errors.append("config.json: missing FAIL_TO_PASS")
            if "PASS_TO_PASS" not in config:
                errors.append("config.json: missing PASS_TO_PASS")
        except json.JSONDecodeError as e:
            errors.append(f"config.json: INVALID JSON — {e}")

    # test.patch
    test_patch_path = os.path.join(task_dir, "tests", "test.patch")
    if os.path.isfile(test_patch_path):
        content = open(test_patch_path).read()
        if not content.strip():
            errors.append("test.patch: empty file")

    return errors


def run_harbor_oracle(task_dir: str, instance_id: str, jobs_dir: str) -> dict:
    """Run harbor oracle on a task directory, return result dict."""
    result = {"instance_id": instance_id, "status": "skipped", "reward": None, "error": None}

    if not os.path.isfile(HARBOR_BIN):
        result["status"] = "skipped"
        result["error"] = f"harbor binary not found at {HARBOR_BIN}"
        return result

    try:
        proc = subprocess.run(
            [HARBOR_BIN, "run", "-p", task_dir, "-a", "oracle", "-o", jobs_dir],
            capture_output=True, text=True, timeout=600,
        )
        result["exit_code"] = proc.returncode
        result["stdout_tail"] = proc.stdout[-500:] if proc.stdout else ""
        result["stderr_tail"] = proc.stderr[-500:] if proc.stderr else ""

        # Harbor writes results to jobs_dir/<timestamp>/<instance>__<hash>/result.json
        # Find the most recent job directory and look for trial results
        if os.path.isdir(jobs_dir):
            job_dirs = sorted(
                (d for d in os.listdir(jobs_dir)
                 if os.path.isdir(os.path.join(jobs_dir, d))),
                reverse=True,
            )
            for job_dir_name in job_dirs:
                job_path = os.path.join(jobs_dir, job_dir_name)
                for entry in os.listdir(job_path):
                    if entry.startswith(instance_id) and os.path.isdir(
                        os.path.join(job_path, entry)
                    ):
                        trial_result = os.path.join(job_path, entry, "result.json")
                        if os.path.isfile(trial_result):
                            data = json.loads(open(trial_result).read())
                            exc = data.get("exception_info")
                            if exc:
                                result["status"] = "docker_error"
                                msg = exc.get("exception_message", "")
                                if "git: not found" in msg:
                                    result["error"] = "Dockerfile build failed: git not in base image"
                                else:
                                    result["error"] = msg[:200]
                            elif data.get("verifier_result"):
                                vr = data["verifier_result"]
                                rewards = vr.get("rewards", {})
                                reward = rewards.get("reward", vr.get("reward"))
                                result["reward"] = reward
                                result["status"] = "pass" if reward == 1 or reward == 1.0 else "fail"
                            else:
                                result["status"] = "no_verifier"
                                result["error"] = "trial completed but no verifier result"
                            return result

        result["status"] = "no_result"
        result["error"] = "result.json not found in jobs dir after harbor run"

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = "harbor oracle timed out (600s)"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def main() -> None:
    random.seed(42)
    start_time = time.time()

    print("=" * 72)
    print("Harbor Emitter Stress Test — Multi-Language, Multi-Repo")
    print("=" * 72)

    # ── Step 1: Load all JSONL sources ──────────────────────────────────
    print("\n── Step 1: Loading TaskInstance data ──")
    all_instances: dict[str, list[TaskInstance]] = {}
    total_loaded = 0

    for source_name, path in JSONL_SOURCES.items():
        if not os.path.isfile(path):
            print(f"  SKIP {source_name}: file not found at {path}")
            all_instances[source_name] = []
            continue
        instances = load_instances(path, source_name)
        all_instances[source_name] = instances
        total_loaded += len(instances)

        langs: dict[str, int] = {}
        repos: dict[str, int] = {}
        for inst in instances:
            lang = inst.repo_language or "unknown"
            langs[lang] = langs.get(lang, 0) + 1
            repos[inst.repo] = repos.get(inst.repo, 0) + 1

        print(f"  {source_name}: {len(instances)} instances")
        print(f"    Languages: {langs}")
        print(f"    Repos: {repos}")

    print(f"\n  Total loaded: {total_loaded}")

    # ── Step 2: Sample representative instances ─────────────────────────
    print("\n── Step 2: Sampling representative instances ──")
    sample = sample_instances(all_instances)

    sample_langs: dict[str, int] = {}
    sample_repos: dict[str, int] = {}
    for inst in sample:
        lang = inst.repo_language or "unknown"
        sample_langs[lang] = sample_langs.get(lang, 0) + 1
        sample_repos[inst.repo] = sample_repos.get(inst.repo, 0) + 1

    print(f"  Selected {len(sample)} instances:")
    print(f"    Languages: {sample_langs}")
    print(f"    Repos: {sample_repos}")
    for inst in sample:
        print(f"    - {inst.instance_id} ({inst.repo_language})")

    # ── Step 3: Run emit_harbor_dataset() ───────────────────────────────
    print("\n── Step 3: Running emit_harbor_dataset() ──")
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)

    t0 = time.time()
    emit_harbor_dataset(sample, OUTPUT_DIR)
    emit_time = time.time() - t0
    print(f"  Emitted in {emit_time:.2f}s")

    harbor_dir = os.path.join(OUTPUT_DIR, "harbor-tasks")
    if not os.path.isdir(harbor_dir):
        print("  ERROR: harbor-tasks directory not created!")
        sys.exit(1)

    task_dirs = sorted(
        d for d in os.listdir(harbor_dir)
        if os.path.isdir(os.path.join(harbor_dir, d))
    )
    print(f"  Task directories created: {len(task_dirs)}")

    # ── Step 4: Validate every generated task ───────────────────────────
    print("\n── Step 4: Validating generated task directories ──")
    instance_map = {inst.instance_id: inst for inst in sample}

    pass_count = 0
    fail_count = 0
    all_errors: dict[str, list[str]] = {}

    for dirname in task_dirs:
        task_path = os.path.join(harbor_dir, dirname)
        inst = instance_map.get(dirname)
        language = (inst.repo_language or "unknown") if inst else "unknown"

        errors = validate_task_dir(task_path, language)
        if errors:
            fail_count += 1
            all_errors[dirname] = errors
            print(f"  [FAIL] {dirname}")
            for err in errors:
                print(f"         {err}")
        else:
            pass_count += 1
            print(f"  [PASS] {dirname}")

    # Validate supplementary files
    supp_errors = 0
    registry_path = os.path.join(harbor_dir, "registry.json")
    if os.path.isfile(registry_path):
        reg = json.loads(open(registry_path).read())
        print(f"\n  registry.json: {len(reg)} entries — OK")
    else:
        print("\n  registry.json: MISSING")
        supp_errors += 1

    dataset_path = os.path.join(harbor_dir, "dataset.toml")
    if os.path.isfile(dataset_path):
        with open(dataset_path, "rb") as f:
            ds = tomllib.load(f)
        ds_info = ds.get("dataset", {})
        print(f"  dataset.toml: task_count={ds_info.get('task_count')}, "
              f"languages={ds_info.get('languages')}, repos={ds_info.get('repos')} — OK")
    else:
        print("  dataset.toml: MISSING")
        supp_errors += 1

    # ── Step 5: Harbor oracle on subset ─────────────────────────────────
    print("\n── Step 5: Harbor oracle runs ──")

    oracle_targets = []
    # 1 Go (etcd)
    for inst in sample:
        if inst.repo == "etcd-io/etcd":
            oracle_targets.append(inst)
            break
    # 1 Go (kubernetes)
    for inst in sample:
        if inst.repo == "kubernetes/kubernetes":
            oracle_targets.append(inst)
            break
    # 1 Python (flask or requests)
    for inst in sample:
        if inst.repo in ("pallets/flask", "psf/requests"):
            oracle_targets.append(inst)
            break

    oracle_jobs_dir = os.path.join(OUTPUT_DIR, "harbor-oracle-jobs")

    if not os.path.isfile(HARBOR_BIN):
        print(f"  Harbor binary not found at {HARBOR_BIN} — skipping oracle runs")
        oracle_results = []
    else:
        oracle_results = []
        for inst in oracle_targets:
            task_path = os.path.join(harbor_dir, inst.instance_id)
            print(f"  Running oracle: {inst.instance_id} ({inst.repo}, {inst.repo_language})...")
            result = run_harbor_oracle(task_path, inst.instance_id, oracle_jobs_dir)
            oracle_results.append(result)
            status_icon = {"pass": "OK", "fail": "FAIL", "error": "ERR",
                           "timeout": "TIMEOUT", "skipped": "SKIP",
                           "no_result": "NO_RESULT"}.get(result["status"], "?")
            reward_str = f"reward={result['reward']}" if result['reward'] is not None else ""
            error_str = f" ({result['error']})" if result.get("error") else ""
            print(f"    [{status_icon}] {reward_str}{error_str}")

    # ── Step 6: Summary ─────────────────────────────────────────────────
    elapsed = time.time() - start_time

    print(f"\n{'=' * 72}")
    print("SUMMARY")
    print("=" * 72)

    print("\n  Data sources:")
    for source_name, instances in all_instances.items():
        print(f"    {source_name}: {len(instances)} instances loaded")
    print(f"    Total: {total_loaded} instances across {len(all_instances)} files")

    print("\n  Sample:")
    print(f"    Selected: {len(sample)} instances")
    for lang, count in sorted(sample_langs.items()):
        print(f"      {lang}: {count}")

    print("\n  Emission:")
    print(f"    Task dirs created: {len(task_dirs)}")
    print(f"    Time: {emit_time:.2f}s")

    print("\n  Validation:")
    print(f"    Passed: {pass_count}")
    print(f"    Failed: {fail_count}")
    print(f"    Supplementary file errors: {supp_errors}")

    if oracle_results:
        print("\n  Harbor Oracle:")
        for r in oracle_results:
            print(f"    {r['instance_id']}: {r['status']} (reward={r['reward']})")

    total_errors = fail_count + supp_errors
    print(f"\n  Total time: {elapsed:.1f}s")

    if total_errors == 0:
        print("\n  ALL CHECKS PASSED")
    else:
        print(f"\n  {total_errors} FAILURE(S) — see details above")
        sys.exit(1)


if __name__ == "__main__":
    main()
