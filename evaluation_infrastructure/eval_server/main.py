"""Eval server: submit jobs, run train/test evals, callback results."""

from __future__ import annotations

import ast
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status

from eval_server import runner as runner_mod
from eval_server.db import STATUS_QUEUED, JobDatabase
from eval_server.worker import EvalWorker, Runner

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "eval-server.db"
DEFAULT_JOBS_ROOT = REPO_ROOT / "server-jobs"


def create_app(db_path: str | Path = DEFAULT_DB,
               jobs_root: str | Path = DEFAULT_JOBS_ROOT,
               runner: Runner = runner_mod.run_eval,
               start_worker: bool = True) -> FastAPI:
    db = JobDatabase(db_path)
    jobs_root = Path(jobs_root)
    jobs_root.mkdir(parents=True, exist_ok=True)
    worker = EvalWorker(db, runner) if start_worker else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if worker is not None:
            worker.start()
            logger.info("eval worker started (db=%s)", db_path)
        yield
        if worker is not None:
            worker.stop()

    app = FastAPI(title="SWE-benchify eval server", lifespan=lifespan)
    app.state.db = db

    @app.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def submit_job(payload: dict[str, Any]) -> dict[str, Any]:
        script = payload.get("script")
        callback_url = payload.get("callback_url")
        if not isinstance(script, str) or not script.strip():
            raise HTTPException(status_code=400, detail="'script' must be a non-empty string")
        if not isinstance(callback_url, str) or not (
            callback_url.startswith("http://") or callback_url.startswith("https://")
        ):
            raise HTTPException(status_code=400, detail="'callback_url' must be an http(s) URL")
        try:
            ast.parse(script)
        except SyntaxError as exc:
            raise HTTPException(status_code=400, detail=f"script has syntax error: {exc}")

        job_id = uuid.uuid4().hex[:12]
        try:
            job_dir = jobs_root / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            script_path = job_dir / "my_swebench.py"
            script_path.write_text(script)
            db.create_job(callback_url, str(script_path), job_id=job_id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to persist job: {exc}")
        return {"job_id": job_id, "status": STATUS_QUEUED}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = db.public_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    return app


app = create_app()
