"""Remote validation via GitHub Actions.

Dispatches compute_f2p() jobs to GHA runners for parallel execution,
avoiding local Docker resource constraints. Handles manifest export,
workflow triggering, polling, result collection, and cleanup.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from swebenchify.models import (
    CandidateInstance,
    GoEnvironmentSpec,
    TaskInstance,
    ValidationResult,
)

logger = logging.getLogger(__name__)

WORKFLOW_FILE = "remote-validate.yml"
MANIFEST_REL_PATH = ".remote-validate/manifest.jsonl"
MAX_MANIFEST_MB = 90
MAX_MATRIX_SIZE = 256
POLL_INTERVAL = 30
MAX_POLL_DURATION = 7200


def export_manifest(
    candidates: list[CandidateInstance],
    env_spec: GoEnvironmentSpec | None,
    output_path: Path,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w") as f:
        for c in candidates:
            if not c.patch or not c.test_patch:
                continue
            entry = {
                "instance_id": c.instance_id,
                "repo": c.repo,
                "base_commit": c.base_commit,
                "test_patch": c.test_patch,
                "gold_patch": c.patch,
                "env_spec": asdict(env_spec) if env_spec else None,
            }
            f.write(json.dumps(entry) + "\n")
            count += 1
    return count


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    logger.debug("Running: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        logger.error("Command failed: %s\nstderr: %s", " ".join(cmd), exc.stderr)
        raise


def _run_git(*args: str) -> str:
    result = _run(["git", *args])
    return result.stdout.strip()


def dispatch(
    manifest_path: Path,
    *,
    n_runs: int = 1,
    timeout: int = 300,
) -> tuple[str, str]:
    """Push manifest to ephemeral branch and trigger the workflow.

    Uses git plumbing to avoid touching the local working tree.
    Returns (batch_id, run_id).
    """
    batch_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    branch = f"remote-validate/{batch_id}"

    manifest_data = manifest_path.read_text()
    result = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=manifest_data, capture_output=True, text=True, check=True,
    )
    blob_sha = result.stdout.strip()

    head_tree = _run_git("rev-parse", "HEAD^{tree}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as tmp:
        tmp.write(f"100644 blob {blob_sha}\t{MANIFEST_REL_PATH}\n")
        tmp.flush()

        index_file = tempfile.mktemp(prefix="git-remote-validate-")
        env = {"GIT_INDEX_FILE": index_file}

        try:
            _run(["git", "read-tree", head_tree], env={**_get_env(), **env})
            _run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{blob_sha},{MANIFEST_REL_PATH}"],
                env={**_get_env(), **env},
            )
            new_tree = _run(["git", "write-tree"], env={**_get_env(), **env}).stdout.strip()
        finally:
            Path(index_file).unlink(missing_ok=True)

    head_sha = _run_git("rev-parse", "HEAD")
    commit_sha = _run_git(
        "commit-tree", new_tree, "-p", head_sha,
        "-m", f"remote-validate: batch {batch_id}",
    )

    _run_git("push", "origin", f"{commit_sha}:refs/heads/{branch}")
    logger.info("Pushed ephemeral branch %s", branch)

    _run([
        "gh", "workflow", "run", WORKFLOW_FILE,
        "--ref", branch,
        "-f", f"batch_id={batch_id}",
        "-f", f"n_runs={n_runs}",
        "-f", f"timeout={timeout}",
    ])
    logger.info("Triggered workflow for batch %s", batch_id)

    time.sleep(5)
    run_id = _get_latest_run_id(branch)

    return batch_id, run_id


def _get_env() -> dict[str, str]:
    import os
    return dict(os.environ)


def _get_latest_run_id(branch: str) -> str:
    for attempt in range(6):
        result = _run([
            "gh", "run", "list",
            "--workflow", WORKFLOW_FILE,
            "--branch", branch,
            "--limit", "1",
            "--json", "databaseId",
        ])
        runs = json.loads(result.stdout)
        if runs:
            return str(runs[0]["databaseId"])
        time.sleep(5)
    raise RuntimeError(f"Could not find workflow run for branch {branch}")


def poll(
    run_id: str,
    *,
    interval: int = POLL_INTERVAL,
    max_wait: int = MAX_POLL_DURATION,
) -> str:
    """Poll until the workflow run completes. Returns final status."""
    start = time.time()
    last_status = ""

    while time.time() - start < max_wait:
        result = _run([
            "gh", "run", "view", run_id,
            "--json", "status,conclusion,jobs",
        ])
        data = json.loads(result.stdout)
        status = data.get("status", "")
        conclusion = data.get("conclusion", "")

        if status != last_status:
            jobs = data.get("jobs", [])
            completed = sum(1 for j in jobs if j.get("status") == "completed")
            total = len(jobs)
            elapsed = int(time.time() - start)
            logger.info(
                "Run %s: status=%s jobs=%d/%d elapsed=%ds",
                run_id, status, completed, total, elapsed,
            )
            last_status = status

        if status == "completed":
            logger.info("Run %s completed: %s", run_id, conclusion)
            return conclusion or "completed"

        time.sleep(interval)

    logger.warning("Run %s timed out after %ds", run_id, max_wait)
    return "timed_out"


def collect_results(
    run_id: str,
    output_dir: Path,
) -> dict[str, ValidationResult]:
    """Download all result artifacts and parse into ValidationResults."""
    output_dir.mkdir(parents=True, exist_ok=True)

    _run([
        "gh", "run", "download", run_id,
        "--dir", str(output_dir),
        "--pattern", "result-*",
    ])

    results: dict[str, ValidationResult] = {}
    for artifact_dir in sorted(output_dir.iterdir()):
        if not artifact_dir.is_dir() or not artifact_dir.name.startswith("result-"):
            continue
        result_file = artifact_dir / "result.json"
        if not result_file.exists():
            continue
        try:
            data = json.loads(result_file.read_text())
            instance_id = data["instance_id"]
            r = data["result"]
            results[instance_id] = ValidationResult(
                status=r.get("status", "error"),
                FAIL_TO_PASS=r.get("FAIL_TO_PASS", []),
                PASS_TO_PASS=r.get("PASS_TO_PASS", []),
                error_message=r.get("error_message"),
                compiled=r.get("compiled", True),
                n_runs=r.get("n_runs", 1),
                flake_count=r.get("flake_count", 0),
                quarantined_tests=r.get("quarantined_tests", []),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse %s: %s", result_file, exc)

    return results


def cleanup(batch_id: str) -> None:
    """Delete the ephemeral remote branch."""
    branch = f"remote-validate/{batch_id}"
    try:
        _run_git("push", "origin", "--delete", branch)
        logger.info("Deleted remote branch %s", branch)
    except subprocess.CalledProcessError:
        logger.warning("Failed to delete remote branch %s", branch)


def _split_batches(
    candidates: list[CandidateInstance],
    env_spec: GoEnvironmentSpec | None,
) -> list[list[CandidateInstance]]:
    """Split candidates into batches that fit under GitHub's 100MB file limit."""
    max_bytes = MAX_MANIFEST_MB * 1024 * 1024
    env_dict = asdict(env_spec) if env_spec else None
    batches: list[list[CandidateInstance]] = []
    current: list[CandidateInstance] = []
    current_size = 0

    for c in candidates:
        entry_size = len(json.dumps({
            "instance_id": c.instance_id,
            "repo": c.repo,
            "base_commit": c.base_commit,
            "test_patch": c.test_patch,
            "gold_patch": c.patch,
            "env_spec": env_dict,
        }).encode())
        if current and (current_size + entry_size > max_bytes or len(current) >= MAX_MATRIX_SIZE):
            batches.append(current)
            current = []
            current_size = 0
        current.append(c)
        current_size += entry_size + 1

    if current:
        batches.append(current)
    return batches


def remote_validate(
    candidates: list[CandidateInstance],
    env_spec: GoEnvironmentSpec | None,
    *,
    n_runs: int = 1,
    timeout: int = 300,
) -> dict[str, ValidationResult]:
    """End-to-end remote validation orchestrator.

    Exports manifest, triggers GHA, polls for completion, downloads
    results, cleans up, and returns results keyed by instance_id.
    """
    viable = [c for c in candidates if c.patch and c.test_patch]
    if not viable:
        logger.info("No viable candidates to validate")
        return {}

    batches = _split_batches(viable, env_spec)

    all_results: dict[str, ValidationResult] = {}

    for batch_idx, batch in enumerate(batches):
        logger.info(
            "Batch %d/%d: %d candidates", batch_idx + 1, len(batches), len(batch)
        )

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.jsonl"
            count = export_manifest(batch, env_spec, manifest_path)
            logger.info("Exported %d entries to manifest", count)

            batch_id, run_id = dispatch(
                manifest_path, n_runs=n_runs, timeout=timeout
            )
            logger.info("Dispatched: batch_id=%s run_id=%s", batch_id, run_id)

            print(f"Workflow run: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions/runs/{run_id}")

            status = poll(run_id)

            results_dir = Path(tmp) / "results"
            batch_results = collect_results(run_id, results_dir)
            all_results.update(batch_results)

            valid = sum(1 for v in batch_results.values() if v.status == "valid")
            logger.info(
                "Batch %d results: %d/%d valid (workflow status: %s)",
                batch_idx + 1, valid, len(batch_results), status,
            )

            cleanup(batch_id)

    valid_total = sum(1 for v in all_results.values() if v.status == "valid")
    logger.info("Remote validation complete: %d/%d valid", valid_total, len(all_results))

    return all_results


def build_task_instances(
    candidates: list[CandidateInstance],
    results: dict[str, ValidationResult],
    env_spec: GoEnvironmentSpec | None,
) -> list[TaskInstance]:
    """Build TaskInstance objects from validated candidates.

    Pairs each valid ValidationResult with its candidate to produce
    TaskInstances ready for filtering and emission.
    """
    from io import StringIO

    try:
        from unidiff import PatchSet
    except ImportError:
        PatchSet = None

    spec_hash = env_spec.env_spec_hash if isinstance(env_spec, GoEnvironmentSpec) else None
    repo_language = env_spec.language if env_spec else None

    if isinstance(env_spec, GoEnvironmentSpec) and env_spec.go_version:
        version = f"{env_spec.go_version}-{spec_hash[:8]}" if spec_hash else env_spec.go_version
    else:
        version = "unknown"

    instances: list[TaskInstance] = []
    for candidate in candidates:
        vr = results.get(candidate.instance_id)
        if not vr or vr.status != "valid":
            continue

        patch_str = candidate.patch or ""
        patch_lines = len(patch_str.splitlines())
        files_touched = 0
        if PatchSet:
            try:
                files_touched = len(PatchSet(StringIO(patch_str)))
            except Exception:
                pass

        instances.append(
            TaskInstance(
                repo=candidate.repo,
                instance_id=candidate.instance_id,
                base_commit=candidate.base_commit,
                patch=candidate.patch,
                test_patch=candidate.test_patch,
                problem_statement=candidate.problem_statement or "",
                hints_text=candidate.hints_text or "",
                created_at=candidate.created_at,
                version=version,
                FAIL_TO_PASS=json.dumps(vr.FAIL_TO_PASS),
                PASS_TO_PASS=json.dumps(vr.PASS_TO_PASS),
                environment_setup_commit=None,
                image_name=None,
                fix_merge_date=candidate.merged_at or None,
                provenance="public_upstream",
                link_confidence=candidate.link_confidence,
                repo_language=repo_language,
                n_fail_to_pass=len(vr.FAIL_TO_PASS),
                patch_lines=patch_lines,
                files_touched=files_touched,
                cross_file=files_touched > 1,
                env_spec_hash=spec_hash,
                n_runs=vr.n_runs,
                flake_count=vr.flake_count,
                quarantined_tests=vr.quarantined_tests,
            )
        )

    return instances
