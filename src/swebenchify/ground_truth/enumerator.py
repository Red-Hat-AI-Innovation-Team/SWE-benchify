from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field

from swebenchify.ground_truth.models import DescriptionSource, GroundTruthChange
from swebenchify.ground_truth.patch_categorizer import split_patch_5way

logger = logging.getLogger(__name__)

_MERGE_PR_RE = re.compile(r"Merge pull request #(\d+)\b")
_SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
_TRAILER_PR_RE = re.compile(
    r"^(?:PR|Closes|Fixes|Resolves):\s*#?(\d+)", re.MULTILINE | re.IGNORECASE
)

_RECORD_SEP = chr(30)


def enumerate_landed_changes(
    repo_path: str,
    target_branch: str = "main",
    after: str | None = None,
    before: str | None = None,
) -> list[dict]:
    fmt = f"%H|%P|%s|%aI|%b{_RECORD_SEP}"
    cmd = ["git", "log", "--first-parent", f"--format={fmt}", target_branch]
    if after:
        cmd.append(f"--after={after}")
    if before:
        cmd.append(f"--before={before}")

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=repo_path, check=True
    )

    commits: list[dict] = []
    for record in result.stdout.split(_RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split("|", 4)
        if len(parts) < 5:
            continue
        sha, parent_str, subject, author_date, body = parts
        parents = parent_str.split() if parent_str.strip() else []
        commits.append(
            {
                "sha": sha,
                "parents": parents,
                "subject": subject,
                "author_date": author_date,
                "body": body.strip(),
            }
        )
    return commits


def parse_trailers(body: str) -> dict[str, str]:
    trailers: dict[str, str] = {}
    if not body:
        return trailers
    lines = body.strip().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            break
        if ": " in line:
            key, _, value = line.partition(": ")
            trailers[key.strip()] = value.strip()
        else:
            break
    return trailers


def link_to_pr(
    sha: str,
    subject: str,
    body: str,
    repo: str | None = None,
    github_token: str | None = None,
    use_api: bool = False,
) -> tuple[int | None, float]:
    m = _MERGE_PR_RE.search(subject)
    if m:
        return int(m.group(1)), 1.0

    m = _SQUASH_PR_RE.search(subject)
    if m:
        return int(m.group(1)), 0.95

    m = _TRAILER_PR_RE.search(body)
    if m:
        return int(m.group(1)), 0.8

    return None, 0.0


def classify_change_kind(parents: list[str], pr_number: int | None) -> str:
    num_parents = len(parents)
    if num_parents >= 2 and pr_number is not None:
        return "pull_request"
    if num_parents >= 2 and pr_number is None:
        return "merge_commit"
    if num_parents == 1 and pr_number is not None:
        return "squash_commit"
    if num_parents == 1 and pr_number is None:
        return "direct_commit"
    return "unknown"


def build_change_from_commit(
    commit_data: dict,
    repo_path: str,
    repo_name: str,
    pr_number: int | None,
    change_kind: str,
    link_confidence: float = 0.0,
) -> GroundTruthChange:
    sha = commit_data["sha"]
    parents = commit_data["parents"]
    first_parent = parents[0] if parents else sha + "~1"

    diff_result = subprocess.run(
        ["git", "diff", f"{first_parent}..{sha}"],
        capture_output=True,
        text=True,
        cwd=repo_path,
        check=True,
    )
    full_diff = diff_result.stdout

    patches = split_patch_5way(full_diff)

    if change_kind == "pull_request" and pr_number is not None:
        change_id = f"pr:{pr_number}"
    elif change_kind == "merge_commit":
        change_id = f"merge:{sha[:12]}"
    elif change_kind == "squash_commit" and pr_number is not None:
        change_id = f"pr:{pr_number}"
    else:
        change_id = f"commit:{sha[:12]}"

    changed_files: list[str] = []
    ls_result = subprocess.run(
        ["git", "diff", "--name-only", f"{first_parent}..{sha}"],
        capture_output=True,
        text=True,
        cwd=repo_path,
        check=True,
    )
    changed_files = [f for f in ls_result.stdout.strip().splitlines() if f]

    desc_source = DescriptionSource(
        source_kind="commit_message",
        source_id=sha,
        created_at=commit_data.get("author_date", ""),
        text=commit_data.get("subject", ""),
    )

    return GroundTruthChange(
        repo=repo_name,
        change_id=change_id,
        change_kind=change_kind,
        base_commit=first_parent,
        head_commit=sha,
        merge_commit=sha if len(parents) >= 2 else "",
        landed_at=commit_data.get("author_date", ""),
        title=commit_data.get("subject", ""),
        body=commit_data.get("body", ""),
        description_sources=[desc_source],
        full_diff=full_diff,
        code_patch=patches.get("code_patch"),
        test_patch=patches.get("test_patch"),
        doc_patch=patches.get("doc_patch"),
        tooling_patch=patches.get("tooling_patch"),
        agent_instruction_patch=patches.get("agent_instruction_patch"),
        changed_files=changed_files,
        link_confidence=link_confidence,
    )


def is_empty_merge(commit_data: dict, repo_path: str) -> bool:
    parents = commit_data.get("parents", [])
    if len(parents) < 2:
        return False
    first_parent = parents[0]
    sha = commit_data["sha"]
    result = subprocess.run(
        ["git", "diff", "--stat", f"{first_parent}..{sha}"],
        capture_output=True,
        text=True,
        cwd=repo_path,
        check=True,
    )
    return not result.stdout.strip()


def batch_direct_commits(
    commits: list[dict],
    repo_path: str,
    repo_name: str,
) -> list[GroundTruthChange]:
    if not commits:
        return []

    changes: list[GroundTruthChange] = []

    first = commits[0]
    last = commits[-1]
    first_parent = first["parents"][0] if first["parents"] else first["sha"] + "~1"

    if len(commits) == 1:
        return [
            build_change_from_commit(
                first, repo_path, repo_name,
                pr_number=None, change_kind="direct_commit",
            )
        ]

    diff_result = subprocess.run(
        ["git", "diff", f"{first_parent}..{last['sha']}"],
        capture_output=True, text=True, cwd=repo_path, check=True,
    )
    full_diff = diff_result.stdout

    patches = split_patch_5way(full_diff)

    ls_result = subprocess.run(
        ["git", "diff", "--name-only", f"{first_parent}..{last['sha']}"],
        capture_output=True, text=True, cwd=repo_path, check=True,
    )
    changed_files = [f for f in ls_result.stdout.strip().splitlines() if f]

    first_subject = first["subject"]
    last_subject = last["subject"]
    title = f"Batch of {len(commits)} commits: {first_subject} ... {last_subject}"
    if len(title) > 200:
        title = title[:197] + "..."

    body_parts = []
    desc_sources = []
    for c in commits:
        msg = c["subject"]
        if c.get("body"):
            msg += "\n\n" + c["body"]
        body_parts.append(msg)
        desc_sources.append(
            DescriptionSource(
                source_kind="commit_message",
                source_id=c["sha"],
                created_at=c.get("author_date", ""),
                text=msg,
            )
        )

    change_id = f"batch:{first['sha'][:8]}..{last['sha'][:8]}"

    changes.append(GroundTruthChange(
        repo=repo_name,
        change_id=change_id,
        change_kind="commit_batch",
        base_commit=first_parent,
        head_commit=last["sha"],
        landed_at=last.get("author_date", ""),
        title=title,
        body="\n---\n".join(body_parts),
        description_sources=desc_sources,
        full_diff=full_diff,
        code_patch=patches.get("code_patch"),
        test_patch=patches.get("test_patch"),
        doc_patch=patches.get("doc_patch"),
        tooling_patch=patches.get("tooling_patch"),
        agent_instruction_patch=patches.get("agent_instruction_patch"),
        changed_files=changed_files,
    ))

    return changes


def collect_all_ground_truth(
    repo_path: str,
    repo_name: str,
    config: dict | None = None,
    github_token: str | None = None,
    existing_change_ids: set[str] | None = None,
) -> list[GroundTruthChange]:
    config = config or {}
    existing_change_ids = existing_change_ids or set()

    target_branch = config.get("target_branch", "main")
    after = config.get("after")
    before = config.get("before")

    commits = enumerate_landed_changes(
        repo_path, target_branch=target_branch, after=after, before=before
    )

    changes: list[GroundTruthChange] = []
    seen_ids: set[str] = set(existing_change_ids)

    annotated: list[tuple[dict, int | None, float, str]] = []
    for commit_data in commits:
        pr_number, confidence = link_to_pr(
            commit_data["sha"],
            commit_data["subject"],
            commit_data["body"],
            repo=repo_name,
            github_token=github_token,
        )
        change_kind = classify_change_kind(commit_data["parents"], pr_number)
        annotated.append((commit_data, pr_number, confidence, change_kind))

    current_batch: list[dict] = []

    def _flush_batch() -> None:
        if not current_batch:
            return
        batch_changes = batch_direct_commits(
            list(current_batch), repo_path, repo_name,
        )
        for bc in batch_changes:
            if bc.change_id not in seen_ids:
                seen_ids.add(bc.change_id)
                changes.append(bc)
        current_batch.clear()

    for commit_data, pr_number, confidence, change_kind in annotated:
        is_pr_backed = change_kind in ("pull_request", "squash_commit")

        if is_pr_backed:
            _flush_batch()

            candidate_id = f"pr:{pr_number}"
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            change = build_change_from_commit(
                commit_data, repo_path, repo_name, pr_number, change_kind, confidence
            )
            changes.append(change)
        else:
            if change_kind == "merge_commit" and is_empty_merge(commit_data, repo_path):
                continue
            current_batch.append(commit_data)

    _flush_batch()

    changes.sort(key=lambda c: c.landed_at)
    return changes
