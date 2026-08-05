"""SQLite storage for eval jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CALLBACK_FAILED = "callback_failed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    callback_url TEXT NOT NULL,
    script_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    train_score REAL,
    test_score REAL,
    error TEXT,
    results_json TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)

    def create_job(self, callback_url: str, script_path: str,
                   job_id: str | None = None) -> dict[str, Any]:
        job_id = job_id or uuid.uuid4().hex[:12]
        row = {
            "id": job_id,
            "callback_url": callback_url,
            "script_path": script_path,
            "status": STATUS_QUEUED,
            "created_at": now_iso(),
            "started_at": None,
            "finished_at": None,
            "train_score": None,
            "test_score": None,
            "error": None,
            "results_json": None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, callback_url, script_path, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (job_id, callback_url, script_path, STATUS_QUEUED, row["created_at"]),
            )
        return row

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim_next(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at LIMIT 1",
                (STATUS_QUEUED,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = ?, started_at = ? WHERE id = ?",
                (STATUS_RUNNING, now_iso(), row["id"]),
            )
        return dict(row)

    def complete(self, job_id: str, train_score: float | None, test_score: float | None,
                 results: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, train_score = ?,"
                " test_score = ?, results_json = ? WHERE id = ?",
                (STATUS_COMPLETED, now_iso(), train_score, test_score,
                 json.dumps(results) if results else None, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
                (STATUS_FAILED, now_iso(), error, job_id),
            )

    def mark_callback_failed(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ? WHERE id = ?",
                (STATUS_CALLBACK_FAILED, error, job_id),
            )

    def recover_stale_running(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, error = ?"
                " WHERE status = ?",
                (STATUS_FAILED, now_iso(),
                 "interrupted by server restart", STATUS_RUNNING),
            )

    def public_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if job is None:
            return None
        keep = {"id", "callback_url", "status", "created_at", "started_at",
                "finished_at", "train_score", "test_score", "error"}
        return {k: job[k] for k in keep}
