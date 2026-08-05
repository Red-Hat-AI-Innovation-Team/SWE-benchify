"""Background worker: runs queued eval jobs one at a time and callbacks."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from eval_server import callback as callback_mod
from eval_server.db import JobDatabase

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0

Runner = Callable[[dict[str, Any]], dict[str, Any]]


class EvalWorker(threading.Thread):
    def __init__(self, db: JobDatabase, runner: Runner,
                 callback: Callable[..., bool] = callback_mod.send_callback) -> None:
        super().__init__(name="eval-worker", daemon=True)
        self.db = db
        self.runner = runner
        self.callback = callback
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        self.db.recover_stale_running()
        while not self._stop.is_set():
            job = self.db.claim_next()
            if job is None:
                self._stop.wait(POLL_INTERVAL)
                continue
            try:
                self._process(job)
            except Exception:
                logger.exception("unexpected worker failure for job %s", job["id"])

    def _process(self, job: dict[str, Any]) -> None:
        job_id, callback_url = job["id"], job["callback_url"]
        logger.info("processing job %s", job_id)
        try:
            result = self.runner(job)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.error("job %s failed: %s", job_id, error)
            self.db.fail(job_id, error)
            self._deliver(callback_url, job_id, "failed",
                          None, None, None, error)
            return

        train_score = result.get("train_score")
        test_score = result.get("test_score")
        zip_path = result.get("zip_path")
        self.db.complete(job_id, train_score, test_score, result)
        logger.info("job %s done: train=%.4f test=%.4f",
                    job_id, train_score, test_score)
        self._deliver(callback_url, job_id, "completed",
                      train_score, test_score, zip_path, None)

    def _deliver(self, callback_url: str, job_id: str, status: str,
                 train_score: float | None, test_score: float | None,
                 zip_path: str | None, error: str | None) -> None:
        ok = self.callback(callback_url, job_id, status, train_score,
                           test_score, zip_path, error)
        if not ok:
            logger.error("callback failed for job %s (status %s)", job_id, status)
            self.db.mark_callback_failed(job_id, "callback unreachable")
