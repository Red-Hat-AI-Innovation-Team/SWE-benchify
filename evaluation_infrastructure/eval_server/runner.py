"""Executes train and test Harbor evaluations for a submitted job."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MODEL = "anthropic/claude-opus-4-6@default"
AGENT = "my_factory:SwebenchFactoryCeo"
TRAIN_BENCHMARK = "benchmark-go-train/harbor-tasks"
TEST_BENCHMARK = "benchmark-go-test/harbor-tasks"
VERTEX_COMPOSE = "vertex-creds.yaml"

# Configurable via env (used for smoke testing with a single task).
CONCURRENCY = int(os.environ.get("EVAL_CONCURRENCY", "4"))
LIMIT = int(os.environ["EVAL_LIMIT"]) if os.environ.get("EVAL_LIMIT") else None
TIMEOUT_SECONDS = int(os.environ.get("EVAL_TIMEOUT_SECONDS", str(4 * 3600)))


def create_compose_override(job_dir: Path, script_path: Path) -> Path:
    """Per-job compose override: mount the submitted script at /tmp/my_swebench.py.

    Mirrors vertex-creds.yaml but swaps the workflow script mount for the
    job's uploaded copy, so each eval uses the submitted workflow.
    """
    base = yaml.safe_load(REPO_ROOT.joinpath(VERTEX_COMPOSE).read_text())
    volumes = base["services"]["main"]["volumes"]
    replaced = False
    for i, volume in enumerate(volumes):
        parts = volume.split(":")
        if len(parts) >= 2 and parts[1] == "/tmp/my_swebench.py":
            volumes[i] = f"{script_path}:/tmp/my_swebench.py:ro"
            replaced = True
    if not replaced:
        raise RuntimeError(
            f"{VERTEX_COMPOSE} does not contain a /tmp/my_swebench.py mount"
        )
    override = job_dir / "compose.yaml"
    override.write_text(yaml.safe_dump(base, sort_keys=False))
    return override


def _run_harbor(job_dir: Path, benchmark: str, job_name: str,
                compose_path: Path) -> Path:
    cmd = [
        "uvx", "harbor", "run",
        "-p", str(REPO_ROOT / benchmark),
        "--agent", AGENT,
        "--model", DEFAULT_MODEL,
        "-n", str(CONCURRENCY),
        "--job-name", job_name,
        "-o", str(job_dir / "harbor-jobs"),
        "--extra-docker-compose", str(compose_path),
    ]
    if LIMIT is not None:
        cmd += ["-l", str(LIMIT)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/gcp-creds.json"
    subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, check=True,
                   timeout=TIMEOUT_SECONDS)
    return job_dir / "harbor-jobs" / job_name


def parse_score(job_output_dir: Path) -> float:
    result_path = job_output_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError(f"missing result.json at {result_path}")
    result = json.loads(result_path.read_text())
    evals = result.get("stats", {}).get("evals", {})
    if not evals:
        raise RuntimeError(f"no evals in {result_path}: {json.dumps(result)[:500]}")
    metrics = next(iter(evals.values())).get("metrics", [])
    if not metrics or "mean" not in metrics[0]:
        raise RuntimeError(f"no mean metric in {result_path}")
    return float(metrics[0]["mean"])


def zip_train_logs(zip_path: Path, train_output_dir: Path) -> None:
    """Zip the full train job output (result.json, logs, per-trial artifacts)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(train_output_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(train_output_dir))


def run_eval(job: dict[str, Any]) -> dict[str, Any]:
    """Run train then test eval for *job*. Returns scores and artifacts.

    Raises RuntimeError with a descriptive message on any failure.
    """
    job_dir = Path(job["script_path"]).parent
    script_path = Path(job["script_path"])
    if not script_path.exists():
        raise RuntimeError(f"script not found: {script_path}")

    compose_path = create_compose_override(job_dir, script_path)

    train_output = _run_harbor(job_dir, TRAIN_BENCHMARK, f"eval-train-{job['id']}",
                               compose_path)
    train_score = parse_score(train_output)

    zip_path = job_dir / "train-eval.zip"
    zip_train_logs(zip_path, train_output)

    test_output = _run_harbor(job_dir, TEST_BENCHMARK, f"eval-test-{job['id']}",
                              compose_path)
    test_score = parse_score(test_output)

    return {
        "train_score": train_score,
        "test_score": test_score,
        "zip_path": str(zip_path),
        "train_output_dir": str(train_output),
        "test_output_dir": str(test_output),
    }


def cleanup_job_dir(job_dir: Path) -> None:
    """Remove the per-job working directory (logs, compose override, zips)."""
    shutil.rmtree(job_dir, ignore_errors=True)
