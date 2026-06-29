from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict

from swebenchify.collector import collect_prs
from swebenchify.config import GroundTruthConfig
from swebenchify.github import github_get, make_headers
from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange
from swebenchify.ground_truth.patch_categorizer import split_patch_5way
from swebenchify.models import CandidatePR, Repository

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"


def pr_to_ground_truth_change(
    candidate_pr: CandidatePR,
    diff_text: str,
) -> GroundTruthChange:
    patches = split_patch_5way(diff_text)

    pr_description = f"{candidate_pr.title or ''}\n{candidate_pr.body or ''}".strip()
    description_sources = []
    if pr_description:
        description_sources.append(
            DescriptionSource(
                source_kind="pr_body",
                source_id=f"pr:{candidate_pr.pr_number}",
                created_at=candidate_pr.created_at,
                text=pr_description,
                leakage_risk="medium",
            )
        )

    linked_issues = [str(i) for i in candidate_pr.resolved_issues]
    linked_issues.extend(candidate_pr.resolved_jira_issues)

    changed_files: list[str] = []
    if diff_text and diff_text.strip():
        from io import StringIO
        try:
            from unidiff import PatchSet
            ps = PatchSet(StringIO(diff_text))
            changed_files = [pf.path for pf in ps]
        except Exception:
            pass

    return GroundTruthChange(
        repo=candidate_pr.repo,
        change_id=f"pr:{candidate_pr.pr_number}",
        change_kind="pull_request",
        base_commit=candidate_pr.base_commit,
        head_commit=candidate_pr.merge_commit,
        merge_commit=candidate_pr.merge_commit,
        landed_at=candidate_pr.merged_at,
        title=candidate_pr.title or "",
        body=candidate_pr.body or "",
        description_sources=description_sources,
        linked_issues=linked_issues,
        full_diff=diff_text,
        code_patch=patches["code_patch"],
        test_patch=patches["test_patch"],
        doc_patch=patches["doc_patch"],
        tooling_patch=patches["tooling_patch"],
        agent_instruction_patch=patches["agent_instruction_patch"],
        changed_files=changed_files,
        link_confidence=candidate_pr.link_confidence,
    )


def _fetch_pr_diff(
    repo: str,
    pr_number: int,
    github_token: str | None = None,
) -> str:
    owner, name = repo.split("/")
    diff_url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{pr_number}"
    headers = make_headers(github_token)
    headers["Accept"] = "application/vnd.github.v3.diff"
    try:
        resp = github_get(diff_url, token=github_token, max_retries=3)
        # The shared github_get uses its own headers; fetch diff directly
        import requests
        diff_resp = requests.get(diff_url, headers=headers, timeout=60)
        if diff_resp.status_code == 200:
            return diff_resp.text
        logger.warning(
            "Failed to fetch diff for PR #%d (HTTP %d)", pr_number, diff_resp.status_code
        )
    except Exception as exc:
        logger.warning("Failed to fetch diff for PR #%d: %s", pr_number, exc)
    return ""


def collect_pr_ground_truth(
    repo: Repository,
    config: GroundTruthConfig,
    github_token: str | None = None,
    existing_change_ids: set[str] | None = None,
    on_change: Callable[[GroundTruthChange], None] | None = None,
) -> list[GroundTruthChange]:
    existing = existing_change_ids or set()
    token = github_token or repo.access_token

    candidate_prs = collect_prs(
        repo,
        max_prs=config.max_changes_per_repo,
        pr_after=config.commit_after,
        pr_before=config.commit_before,
    )

    changes: list[GroundTruthChange] = []
    for pr in candidate_prs:
        change_id = f"pr:{pr.pr_number}"

        if change_id in existing:
            logger.debug("Skipping already-processed %s", change_id)
            continue

        if config.min_link_confidence > 0 and pr.link_confidence < config.min_link_confidence:
            logger.debug(
                "Skipping PR #%d: link_confidence %.2f < %.2f",
                pr.pr_number,
                pr.link_confidence,
                config.min_link_confidence,
            )
            continue

        diff_text = _fetch_pr_diff(pr.repo, pr.pr_number, github_token=token)
        change = pr_to_ground_truth_change(pr, diff_text)
        changes.append(change)

        if on_change is not None:
            on_change(change)

    return changes


def save_ground_truth_changes(changes: list[GroundTruthChange], path: str) -> None:
    with open(path, "w") as f:
        for change in changes:
            f.write(json.dumps(asdict(change)) + "\n")


def load_ground_truth_changes(path: str) -> list[GroundTruthChange]:
    changes: list[GroundTruthChange] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "description_sources" in data:
                data["description_sources"] = [
                    DescriptionSource(**ds) for ds in data["description_sources"]
                ]
            changes.append(GroundTruthChange(**data))
    return changes
