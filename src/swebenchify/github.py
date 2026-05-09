"""Shared GitHub API utilities.

Provides authenticated HTTP helpers with rate-limit handling
and exponential backoff for use across pipeline stages.
"""

from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


def make_headers(token: str | None = None) -> dict[str, str]:
    """Build HTTP headers for GitHub API requests.

    Falls back to ``$GITHUB_TOKEN`` from the environment if *token* is
    not provided.
    """
    t = token or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if t:
        headers["Authorization"] = f"token {t}"
    return headers


def github_get(
    url: str,
    token: str | None = None,
    params: dict[str, str] | None = None,
    max_retries: int = 5,
) -> requests.Response:
    """GET with rate limit handling and exponential backoff.

    Args:
        url: The GitHub API URL to request.
        token: GitHub personal access token (optional).
        params: Query parameters for the request.
        max_retries: Maximum number of retry attempts on 403.

    Returns:
        The successful ``requests.Response``.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    headers = make_headers(token)
    backoff = 60
    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
            if remaining == 0:
                reset_time = int(resp.headers.get("X-RateLimit-Reset", 0))
                sleep_time = max(reset_time - int(time.time()), 1)
                logger.warning("Rate limit reached, sleeping %ds", sleep_time)
                time.sleep(sleep_time)
            return resp
        elif resp.status_code == 403:
            logger.warning(
                "GitHub 403, backing off %ds (attempt %d)",
                backoff,
                attempt + 1,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
        elif resp.status_code == 404:
            return resp  # Let caller handle 404
        else:
            resp.raise_for_status()
    raise RuntimeError(
        f"GitHub API request failed after {max_retries} retries: {url}"
    )
