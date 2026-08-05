#!/usr/bin/env python3
"""Submit a SWE-bench eval job and wait for the results.

Usage:
    python submit_eval.py <workflow_script.py> [options]

Starts a local callback receiver, submits the workflow script to the eval
server, waits until the evaluation finishes, then saves the delivered
results (zip + summary) under --output-dir/<job_id>/ and prints the path:

    Results saved to: /abs/path/to/eval-results/<job_id>

Exit codes: 0 = results received (failed evals exit 1), 1 = timeout,
2 = submission error.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile

DEFAULT_EVAL_SERVER = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = "./eval-results"
DEFAULT_TIMEOUT = 24 * 3600
STATUS_POLL_INTERVAL = 900.0


class CallbackState:
    def __init__(self) -> None:
        self.received = threading.Event()
        self.result: dict[str, Any] | None = None
        self.save_error: str | None = None


def build_callback_app(state: CallbackState, output_dir: Path) -> FastAPI:
    app = FastAPI()

    @app.post("/callback")
    async def callback(
        logs: UploadFile | None = File(None),
        job_id: str = Form(...),
        status: str = Form(...),
        train_score: str = Form(""),
        test_score: str = Form(""),
        error: str = Form(""),
    ) -> dict[str, Any]:
        def _to_float(value: str) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        result: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "train_score": _to_float(train_score),
            "test_score": _to_float(test_score),
            "error": error or None,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        job_dir = output_dir / job_id
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            if logs is not None:
                zip_path = job_dir / "train-eval.zip"
                zip_path.write_bytes(await logs.read())
                result["zip"] = str(zip_path)
                extract_dir = job_dir / "train-eval"
                extract_dir.mkdir(exist_ok=True)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(extract_dir)
                result["extracted_dir"] = str(extract_dir)
            summary_path = job_dir / "summary.json"
            summary_path.write_text(json.dumps(result, indent=2))
            result["summary_path"] = str(summary_path)
        except Exception as exc:  # noqa: BLE001 - save_error is reported to caller
            state.save_error = f"{type(exc).__name__}: {exc}"
        state.result = result
        state.received.set()
        return {"ok": True}

    return app


def submit(script_text: str, eval_server: str, callback_url: str) -> tuple[str, str]:
    response = requests.post(f"{eval_server}/jobs",
                             json={"script": script_text,
                                   "callback_url": callback_url},
                             timeout=60)
    if response.status_code != 202:
        raise RuntimeError(f"submit failed (HTTP {response.status_code}): "
                           f"{response.text[:500]}")
    payload = response.json()
    return payload["job_id"], payload["status"]


def wait_for_results(state: CallbackState, eval_server: str, job_id: str,
                     timeout: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    last_poll = time.monotonic()
    last_status = "queued"
    while not state.received.is_set():
        if time.monotonic() >= deadline:
            return None
        if time.monotonic() - last_poll >= STATUS_POLL_INTERVAL:
            try:
                job = requests.get(f"{eval_server}/jobs/{job_id}",
                                   timeout=30).json()
                status = job.get("status", "unknown")
                if status != last_status:
                    print(f"[{job_id}] status: {status}")
                    last_status = status
            except requests.RequestException:
                pass
            last_poll = time.monotonic()
        time.sleep(1)
    return state.result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="path to the workflow script (my_swebench.py)")
    parser.add_argument("--eval-server", default=DEFAULT_EVAL_SERVER,
                        help=f"eval server base URL (default: {DEFAULT_EVAL_SERVER})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help=f"where to save results (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"seconds to wait for results (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--port", type=int, default=0,
                        help="local callback port (default: ephemeral)")
    args = parser.parse_args()

    script_path = Path(args.script)
    if not script_path.is_file():
        print(f"error: script not found: {script_path}", file=sys.stderr)
        return 2
    try:
        script_text = script_path.read_text()
    except OSError as exc:
        print(f"error: cannot read script: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)
    if sys.stderr is not None:
        sys.stderr.reconfigure(line_buffering=True)

    state = CallbackState()
    app = build_callback_app(state, output_dir)
    config = uvicorn.Config(app, host="127.0.0.1", port=args.port,
                            log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            print("error: callback server failed to start", file=sys.stderr)
            return 2
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    callback_url = f"http://127.0.0.1:{port}/callback"
    print(f"callback receiver listening on {callback_url}")

    try:
        job_id, _ = submit(script_text, args.eval_server, callback_url)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Submitted job {job_id} to {args.eval_server}")

    result = wait_for_results(state, args.eval_server, job_id, args.timeout)
    if result is None:
        print(f"error: timed out after {args.timeout:.0f}s waiting for results "
              f"(job {job_id} may still be running on the eval server)",
              file=sys.stderr)
        return 1

    if state.save_error:
        print(f"error: failed to save results: {state.save_error}", file=sys.stderr)
        return 1

    summary_path = Path(result["summary_path"])
    print(f"Results saved to: {summary_path.parent}")
    if result.get("status") == "completed":
        print(f"  train_score={result['train_score']} "
              f"test_score={result['test_score']}")
        return 0
    print(f"  status={result['status']}", file=sys.stderr)
    if result.get("error"):
        print(f"  error: {result['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
