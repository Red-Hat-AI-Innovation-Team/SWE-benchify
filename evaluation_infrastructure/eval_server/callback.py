"""Delivers eval results to the job's callback URL as a multipart upload."""

from __future__ import annotations

import time
from pathlib import Path

import requests

RETRIES = 5
BACKOFF_SECONDS = 10


def send_callback(callback_url: str, job_id: str, status: str,
                  train_score: float | None, test_score: float | None,
                  zip_path: str | None = None,
                  error: str | None = None,
                  retries: int = RETRIES,
                  backoff: float = BACKOFF_SECONDS) -> bool:
    """POST the results (zip + fields) to *callback_url* with retries.

    Returns True on success. Never raises.
    """
    data = {
        "job_id": job_id,
        "status": status,
        "train_score": "" if train_score is None else str(train_score),
        "test_score": "" if test_score is None else str(test_score),
    }
    if error:
        data["error"] = error
    zip_path_obj = Path(zip_path) if zip_path else None
    for attempt in range(1, retries + 1):
        files = None
        if zip_path_obj and zip_path_obj.exists():
            files = {"logs": (zip_path_obj.name, open(zip_path_obj, "rb"),
                              "application/zip")}
        try:
            response = requests.post(callback_url, data=data, files=files,
                                     timeout=120)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        finally:
            if files is not None:
                files["logs"][1].close()
        if attempt < retries:
            time.sleep(backoff * attempt)
    return False
