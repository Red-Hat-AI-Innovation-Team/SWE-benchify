from __future__ import annotations

import logging
import re

from swebenchify.github import github_get, make_headers
from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange

logger = logging.getLogger(__name__)
_GITHUB_API_BASE = "https://api.github.com"


def extract_from_commit_message(subject: str, body: str, sha: str) -> DescriptionSource:
    return DescriptionSource(
        source_kind="commit_message",
        source_id=sha,
        created_at="",
        text=f"{subject}\n{body}".strip(),
        leakage_risk="low",
        allowed_for_task_prompt=True,
    )


def extract_from_pr_body(
    repo: str, pr_number: int, github_token: str | None = None
) -> DescriptionSource | None:
    owner, name = repo.split("/")
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{pr_number}"
    try:
        resp = github_get(url, token=github_token)
    except Exception:
        logger.warning("Failed to fetch PR #%d for %s", pr_number, repo)
        return None

    if resp.status_code != 200:
        logger.warning(
            "PR #%d fetch returned HTTP %d for %s", pr_number, resp.status_code, repo
        )
        return None

    data = resp.json()
    title = data.get("title", "")
    body = data.get("body", "") or ""
    text = f"{title}\n{body}".strip()
    if not text:
        return None

    return DescriptionSource(
        source_kind="pr_body",
        source_id=f"https://github.com/{repo}/pull/{pr_number}",
        created_at=data.get("created_at", ""),
        text=text,
        leakage_risk="medium",
        allowed_for_task_prompt=True,
    )


def extract_from_linked_issues(
    repo: str, issue_numbers: list[str], github_token: str | None = None
) -> list[DescriptionSource]:
    owner, name = repo.split("/")
    sources: list[DescriptionSource] = []

    for issue_id in issue_numbers:
        if not issue_id.isdigit():
            sources.append(
                DescriptionSource(
                    source_kind="issue",
                    source_id=issue_id,
                    created_at="",
                    text=issue_id,
                    leakage_risk="low",
                    allowed_for_task_prompt=True,
                )
            )
            continue

        url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/issues/{issue_id}"
        try:
            resp = github_get(url, token=github_token)
        except Exception:
            logger.warning("Failed to fetch issue #%s for %s", issue_id, repo)
            continue

        if resp.status_code != 200:
            logger.warning(
                "Issue #%s fetch returned HTTP %d for %s",
                issue_id,
                resp.status_code,
                repo,
            )
            continue

        data = resp.json()
        title = data.get("title", "")
        body = data.get("body", "") or ""
        text = f"{title}\n{body}".strip()

        sources.append(
            DescriptionSource(
                source_kind="issue",
                source_id=f"https://github.com/{repo}/issues/{issue_id}",
                created_at=data.get("created_at", ""),
                text=text,
                leakage_risk="low",
                allowed_for_task_prompt=True,
            )
        )

    return sources


def extract_from_review_comments(
    repo: str, pr_number: int, github_token: str | None = None
) -> list[DescriptionSource]:
    owner, name = repo.split("/")
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{pr_number}/reviews"
    try:
        resp = github_get(url, token=github_token)
    except Exception:
        logger.warning("Failed to fetch reviews for PR #%d in %s", pr_number, repo)
        return []

    if resp.status_code != 200:
        return []

    sources: list[DescriptionSource] = []
    for review in resp.json():
        body = review.get("body", "") or ""
        if not body.strip():
            continue
        sources.append(
            DescriptionSource(
                source_kind="review_comment",
                source_id=review.get("html_url", f"review:{review.get('id', '')}"),
                created_at=review.get("submitted_at", ""),
                text=body.strip(),
                leakage_risk="high",
                allowed_for_task_prompt=False,
            )
        )

    return sources


def extract_trailers(body: str) -> list[DescriptionSource]:
    if not body:
        return []

    lines = body.strip().splitlines()
    trailer_re = re.compile(r"^([A-Za-z][A-Za-z0-9_-]+):\s+(.+)$")
    trailers: list[DescriptionSource] = []

    for line in reversed(lines):
        line = line.strip()
        if not line:
            break
        m = trailer_re.match(line)
        if not m:
            break
        key, value = m.group(1), m.group(2)
        trailers.append(
            DescriptionSource(
                source_kind="commit_message",
                source_id=f"trailer:{key}",
                created_at="",
                text=f"{key}: {value}",
                leakage_risk="none",
                allowed_for_task_prompt=True,
            )
        )

    trailers.reverse()
    return trailers


def classify_leakage_risk(text: str, changed_files: list[str]) -> str:
    if not text or not text.strip():
        return "none"

    for path in changed_files:
        if path in text:
            return "high"

    code_patterns = ["`", "def ", "import ", "from ", "class ", "function ", "const "]
    for pattern in code_patterns:
        if pattern in text:
            return "medium"

    return "low"


def extract_all_descriptions(
    change: GroundTruthChange,
    repo: str,
    github_token: str | None = None,
) -> list[DescriptionSource]:
    sources: list[DescriptionSource] = []

    sources.append(
        extract_from_commit_message(change.title, change.body, change.head_commit)
    )

    sources.extend(extract_trailers(change.body))

    is_pr_backed = change.change_kind in ("pull_request", "squash_commit") and change.change_id.startswith("pr:")

    if is_pr_backed:
        pr_number = int(change.change_id.split(":")[1])
        pr_body = extract_from_pr_body(repo, pr_number, github_token)
        if pr_body is not None:
            sources.append(pr_body)

        sources.extend(
            extract_from_linked_issues(repo, change.linked_issues, github_token)
        )

        sources.extend(
            extract_from_review_comments(repo, pr_number, github_token)
        )

    for source in sources:
        source.leakage_risk = classify_leakage_risk(source.text, change.changed_files)

    return sources
