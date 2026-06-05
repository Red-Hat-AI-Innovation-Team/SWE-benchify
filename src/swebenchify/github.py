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
    initial_backoff: int = 10,
) -> requests.Response:
    """GET with rate limit handling and exponential backoff.

    Handles both GitHub API 403 (rate limit) and generic 429 (too many
    requests) responses, respecting the ``Retry-After`` header when present.

    Args:
        url: The URL to request.
        token: GitHub personal access token (optional).
        params: Query parameters for the request.
        max_retries: Maximum number of retry attempts on 403/429.
        initial_backoff: Starting backoff in seconds (doubles each retry).

    Returns:
        The successful ``requests.Response``.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    headers = make_headers(token)
    backoff = initial_backoff
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            wait = backoff
            logger.warning(
                "Network error (attempt %d/%d), retrying in %ds: %s",
                attempt + 1,
                max_retries,
                wait,
                exc,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
            continue

        if resp.status_code == 200:
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
            if remaining == 0:
                reset_time = int(resp.headers.get("X-RateLimit-Reset", 0))
                sleep_time = max(reset_time - int(time.time()), 1)
                logger.warning("Rate limit reached, sleeping %ds", sleep_time)
                time.sleep(sleep_time)
            return resp
        elif resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else backoff
            logger.warning(
                "HTTP 429, backing off %ds (attempt %d/%d)", wait, attempt + 1, max_retries
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
        elif resp.status_code == 403:
            # Only retry if GitHub flagged this as a rate limit; otherwise fail fast.
            body = resp.text.lower()
            is_rate_limit = (
                "rate limit" in body
                or "secondary rate" in body
                or "abuse" in body
                or resp.headers.get("X-RateLimit-Remaining") == "0"
            )
            if not is_rate_limit:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else backoff
            logger.warning(
                "HTTP 403 (rate limit), backing off %ds (attempt %d/%d)",
                wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
        elif resp.status_code == 404:
            return resp  # Let caller handle 404
        else:
            resp.raise_for_status()
    raise RuntimeError(
        f"GitHub API request failed after {max_retries} retries: {url}"
    )
