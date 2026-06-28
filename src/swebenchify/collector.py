"""Stage 1: PR collection.

Fetches merged pull requests with linked issues from the GitHub API.
See SPEC.md Section 5.2.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict

import requests

from swebenchify.github import github_get as _shared_github_get, make_headers
from swebenchify.models import CandidatePR, Repository

logger = logging.getLogger(__name__)

# SWE-bench keyword regex: matches "keyword #number" patterns.
# The keyword must be one of the close/fix/resolve family.
_ISSUE_KEYWORD_PATTERN = re.compile(
    r"(\w+)\s+#?(\d+)", re.IGNORECASE
)

_KEYWORDS = frozenset({
    "close", "closes", "closed",
    "fix", "fixes", "fixed",
    "resolve", "resolves", "resolved",
})

_GITHUB_API_BASE = "https://api.github.com"

# ---------------------------------------------------------------------------
# RH issue-linking patterns
# ---------------------------------------------------------------------------

# Commit trailers with an explicit score of 1.0 or 0.95
_TRAILER_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"^Resolves:\s+\S+", re.MULTILINE | re.IGNORECASE), 1.0),
    (re.compile(r"^Fixes:\s+\S+", re.MULTILINE | re.IGNORECASE), 1.0),
    (re.compile(r"^Bug-Url:\s+\S+", re.MULTILINE | re.IGNORECASE), 0.95),
]

_RHBZ_PATTERN = re.compile(r"rhbz#\d+", re.IGNORECASE)
_CHANGE_ID_PATTERN = re.compile(r"^Change-Id:\s+I[0-9a-f]+", re.MULTILINE)

# OCPBUGS is always recognised; other keys come from config.
_OCPBUGS_PATTERN = re.compile(r"\bOCPBUGS-\d+\b")


def compute_link_confidence(
    title: str | None,
    body: str | None,
    commit_messages: list[str] | None = None,
    rh_jira_projects: list[str] | None = None,
) -> float:
    """Return a confidence score [0, 1] that the PR resolves a tracked issue.

    Scans title, body, and (optionally) commit messages for known issue-linking
    patterns and returns the highest score found. Pattern precedence:

    - GitHub close/fix/resolve keyword → 1.0
    - ``Resolves:`` / ``Fixes:`` commit trailers → 1.0
    - ``Bug-Url:`` trailer → 0.95
    - ``rhbz#NNNNNN`` → 0.9
    - ``OCPBUGS-NNNN`` → 0.9
    - Configured Jira project key (e.g. ``STOR-567``) → 0.7
    - ``Change-Id:`` only → 0.5
    - No match → 0.0

    Args:
        title: PR title text.
        body: PR body text.
        commit_messages: List of commit message strings to scan.
        rh_jira_projects: Additional Jira project keys to recognise at 0.7.
            Defaults to ``["STOR", "MGMT"]`` (OCPBUGS is always included at 0.9).

    Returns:
        Float confidence score in [0, 1].
    """
    all_text = "\n".join(filter(None, [title, body, *( commit_messages or [])]))
    if not all_text.strip():
        return 0.0

    best = 0.0

    # GitHub keyword → 1.0
    if extract_resolved_issues(all_text):
        return 1.0

    # Commit trailers
    for pattern, score in _TRAILER_PATTERNS:
        if pattern.search(all_text):
            best = max(best, score)

    # rhbz#
    if _RHBZ_PATTERN.search(all_text):
        best = max(best, 0.9)

    # OCPBUGS
    if _OCPBUGS_PATTERN.search(all_text):
        best = max(best, 0.9)

    # Configured Jira project keys
    extra_projects = rh_jira_projects or ["STOR", "MGMT"]
    for project in extra_projects:
        if re.search(rf"\b{re.escape(project)}-\d+\b", all_text):
            best = max(best, 0.7)

    # Change-Id (weakest signal)
    if _CHANGE_ID_PATTERN.search(all_text):
        best = max(best, 0.5)

    return best


def extract_resolved_issues(text: str) -> list[int]:
    """Extract issue numbers that are resolved by keyword references.

    Scans *text* for patterns like ``fixes #123`` or ``Closes #456`` and
    returns a deduplicated, sorted list of the referenced issue numbers.

    Only matches where the preceding word is a recognised close/fix/resolve
    keyword are returned.

    Args:
        text: PR title, body, or commit message text to scan.

    Returns:
        Sorted list of unique issue numbers.
    """
    if not text:
        return []

    issues: set[int] = set()
    for match in _ISSUE_KEYWORD_PATTERN.finditer(text):
        keyword = match.group(1).lower()
        if keyword in _KEYWORDS:
            issues.add(int(match.group(2)))
    return sorted(issues)


def extract_jira_issues(
    text: str,
    rh_jira_projects: list[str] | None = None,
) -> list[str]:
    """Extract Jira issue keys from text.

    Always recognises ``OCPBUGS-NNNN``.  Additionally recognises
    ``PROJECT-NNNN`` for each key in *rh_jira_projects* (defaults to
    ``["STOR", "MGMT"]``).

    Args:
        text: PR title, body, or commit message text to scan.
        rh_jira_projects: Additional Jira project keys to recognise.

    Returns:
        Sorted list of unique Jira issue keys (e.g. ``["OCPBUGS-1234"]``).
    """
    if not text:
        return []

    issues: set[str] = set()

    for m in _OCPBUGS_PATTERN.finditer(text):
        issues.add(m.group(0))

    extra_projects = rh_jira_projects if rh_jira_projects is not None else ["STOR", "MGMT"]
    for project in extra_projects:
        for m in re.finditer(rf"\b{re.escape(project)}-\d+\b", text):
            issues.add(m.group(0))

    return sorted(issues)


def _make_headers(token: str | None) -> dict[str, str]:
    """Build HTTP headers for GitHub API requests."""
    return make_headers(token)


def _github_get(
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    max_retries: int = 5,
) -> requests.Response:
    """Perform a GET request to the GitHub API with rate-limit handling.

    Delegates to the shared :func:`swebenchify.github.github_get`.
    The *headers* parameter is accepted for backward-compatibility but
    the token is extracted from the ``Authorization`` header and passed
    to the shared implementation.
    """
    # Extract token from headers for the shared helper
    auth = headers.get("Authorization", "")
    token = auth.replace("token ", "") if auth.startswith("token ") else None
    return _shared_github_get(url, token=token, params=params, max_retries=max_retries)


def _fetch_pr_commits(
    owner: str,
    repo: str,
    pr_number: int,
    headers: dict[str, str],
) -> list[dict]:
    """Fetch commit objects for a pull request."""
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
    all_commits: list[dict] = []
    page = 1
    while True:
        resp = _github_get(url, headers, params={"per_page": "100", "page": str(page)})
        data = resp.json()
        if not data:
            break
        all_commits.extend(data)
        if len(data) < 100:
            break
        page += 1
    return all_commits


def collect_prs(
    repo: Repository,
    max_prs: int | None = None,
    pr_after: str | None = None,
    pr_before: str | None = None,
    existing_pr_numbers: set[int] | None = None,
    on_candidate: Callable[[CandidatePR], None] | None = None,
    rh_jira_projects: list[str] | None = None,
) -> list[CandidatePR]:
    """Collect merged pull requests that reference issues from a repository.

    Fetches closed PRs from the GitHub REST API, filters to those that are
    merged and reference at least one issue via a close/fix/resolve keyword,
    and returns a list of :class:`CandidatePR` instances.

    Args:
        repo: Repository to collect PRs from.
        max_prs: Maximum number of candidate PRs to return. ``None`` means
            no limit.
        pr_after: Only include PRs created after this ISO 8601 date string.
        pr_before: Only include PRs created before this ISO 8601 date string.
        existing_pr_numbers: Set of PR numbers to skip (for resumption).

    Returns:
        List of CandidatePR dataclass instances.
    """
    headers = _make_headers(repo.access_token)
    owner = repo.owner
    name = repo.name
    existing = existing_pr_numbers or set()

    candidates: list[CandidatePR] = []
    page = 1

    while True:
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls"
        params = {
            "state": "closed",
            "sort": "created",
            "direction": "desc",
            "per_page": "100",
            "page": str(page),
        }

        if page % 10 == 1:
            logger.info(
                "%s/%s: scanning page %d (%d candidates so far)",
                owner, name, page, len(candidates),
            )

        time.sleep(1)  # stay well under GitHub's secondary rate limit
        resp = _github_get(url, headers, params=params)
        pulls = resp.json()

        if not pulls:
            break

        for pr in pulls:
            pr_number = pr["number"]

            # Skip already-processed PRs
            if pr_number in existing:
                continue

            # Only merged PRs
            if pr.get("merged_at") is None:
                continue

            created_at = pr["created_at"]

            # Date filtering — PRs are sorted by created desc, so once
            # we pass the after cutoff all remaining PRs are older.
            if pr_after and created_at < pr_after:
                return candidates
            if pr_before and created_at > pr_before:
                continue

            # Extract resolved issues from title + body only.
            # Commit-message scanning was removed: it required one extra API
            # call per PR (~87% of PRs for large repos), triggering GitHub's
            # secondary rate limit at scale.
            title = pr.get("title") or ""
            body = pr.get("body") or ""
            resolved = set(extract_resolved_issues(title))
            resolved.update(extract_resolved_issues(body))

            jira_resolved = set(extract_jira_issues(title, rh_jira_projects))
            jira_resolved.update(extract_jira_issues(body, rh_jira_projects))

            if not resolved and not jira_resolved:
                continue

            confidence = compute_link_confidence(
                title, body, rh_jira_projects=rh_jira_projects,
            )

            # Get the actual base commit (first parent of merge commit).
            # Fall back to pr.base.sha (the base branch tip when the PR was
            # opened) — merge_commit_sha can be a temporary test-merge SHA
            # that GitHub garbage-collects, making both it and its parents
            # unreachable.
            merge_commit_sha = pr.get("merge_commit_sha") or ""
            pr_base_sha = (pr.get("base") or {}).get("sha", "")
            base_sha = pr_base_sha or merge_commit_sha  # fallback
            if merge_commit_sha:
                commit_resp = _github_get(
                    f"{_GITHUB_API_BASE}/repos/{owner}/{name}/git/commits/{merge_commit_sha}",
                    headers,
                )
                if commit_resp and commit_resp.status_code == 200:
                    parents = commit_resp.json().get("parents", [])
                    if parents:
                        base_sha = parents[0]["sha"]
            diff_url = pr.get("diff_url") or f"https://github.com/{owner}/{name}/pull/{pr_number}.diff"

            candidate = CandidatePR(
                repo=repo.full_name,
                pr_number=pr_number,
                title=title,
                body=body,
                base_commit=base_sha,
                merge_commit=merge_commit_sha,
                diff_url=diff_url,
                resolved_issues=sorted(resolved),
                created_at=created_at,
                merged_at=pr["merged_at"],
                resolved_jira_issues=sorted(jira_resolved),
                link_confidence=confidence,
            )
            candidates.append(candidate)
            if on_candidate is not None:
                on_candidate(candidate)

            if max_prs is not None and len(candidates) >= max_prs:
                return candidates

        if len(pulls) < 100:
            break

        page += 1

    return candidates


def save_prs(prs: list[CandidatePR], path: str) -> None:
    """Save a list of CandidatePR objects to a JSONL file.

    Each line is a JSON object representing one CandidatePR.

    Args:
        prs: List of CandidatePR instances to save.
        path: File path to write.
    """
    with open(path, "w") as f:
        for pr in prs:
            f.write(json.dumps(asdict(pr)) + "\n")


def load_prs(path: str) -> list[CandidatePR]:
    """Load CandidatePR objects from a JSONL file.

    Args:
        path: File path to read.

    Returns:
        List of CandidatePR instances.
    """
    prs: list[CandidatePR] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            prs.append(CandidatePR(**data))
    return prs
