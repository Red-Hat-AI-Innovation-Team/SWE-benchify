"""Stage 2: Patch extraction.

Downloads PR diffs and splits them into gold patches and test patches.
See docs/SPEC.md Section 5.3.

Also provides brace-counting utilities for Go/Rust/Java function boundary
detection that correctly skip braces inside string literals and comments.
"""

from __future__ import annotations

import enum
import json
import logging
import re
from dataclasses import asdict
from io import StringIO

import requests
from unidiff import PatchSet

from swebenchify.github import github_get as _shared_github_get, make_headers
from swebenchify.models import CandidateInstance, CandidatePR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Brace-counting state machine for Go / Rust / Java
# ---------------------------------------------------------------------------


class _LexState(enum.Enum):
    CODE = "code"
    LINE_COMMENT = "line_comment"
    BLOCK_COMMENT = "block_comment"
    DOUBLE_STRING = "double_string"
    SINGLE_STRING = "single_string"
    BACKTICK_STRING = "backtick_string"
    RAW_STRING = "raw_string"


def count_braces(source: str, language: str = "go") -> int:
    """Count net brace depth (opens minus closes) in *source*, skipping
    braces that appear inside string literals or comments.

    Supported languages: ``"go"``, ``"rust"``, ``"java"``.

    Language-specific handling:

    * **Go** — backtick (raw) strings, double-quoted strings, single-quoted
      rune literals, ``//`` and ``/* */`` comments.
    * **Rust** — ``r"..."`` / ``r#"..."#`` raw strings, double-quoted
      strings, byte strings (``b"..."``, ``br"..."``, ``br#"..."#``),
      single-quoted char literals, ``//`` and ``/* */`` comments.
    * **Java** — double-quoted strings, single-quoted char literals,
      ``//`` and ``/* */`` comments.

    Returns:
        Net depth (positive means more ``{`` than ``}``).
    """
    state = _LexState.CODE
    depth = 0
    i = 0
    n = len(source)
    raw_hashes = 0

    while i < n:
        c = source[i]

        if state == _LexState.CODE:
            if c == "/" and i + 1 < n:
                if source[i + 1] == "/":
                    state = _LexState.LINE_COMMENT
                    i += 2
                    continue
                if source[i + 1] == "*":
                    state = _LexState.BLOCK_COMMENT
                    i += 2
                    continue

            if c == '"':
                state = _LexState.DOUBLE_STRING
                i += 1
                continue

            if c == "'" and language in ("go", "rust", "java"):
                state = _LexState.SINGLE_STRING
                i += 1
                continue

            if c == "`" and language == "go":
                state = _LexState.BACKTICK_STRING
                i += 1
                continue

            if language == "rust" and c in ("r", "b"):
                consumed, hashes = _try_rust_raw_string_start(source, i, n)
                if consumed > 0:
                    raw_hashes = hashes
                    state = _LexState.RAW_STRING
                    i += consumed
                    continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1

        elif state == _LexState.LINE_COMMENT:
            if c == "\n":
                state = _LexState.CODE
            i += 1

        elif state == _LexState.BLOCK_COMMENT:
            if c == "*" and i + 1 < n and source[i + 1] == "/":
                state = _LexState.CODE
                i += 2
                continue
            i += 1

        elif state == _LexState.DOUBLE_STRING:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                state = _LexState.CODE
            i += 1

        elif state == _LexState.SINGLE_STRING:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                state = _LexState.CODE
            i += 1

        elif state == _LexState.BACKTICK_STRING:
            if c == "`":
                state = _LexState.CODE
            i += 1

        elif state == _LexState.RAW_STRING:
            if c == '"':
                closing = '"' + "#" * raw_hashes
                end = i + 1 + raw_hashes
                if source[i:end] == closing:
                    state = _LexState.CODE
                    i = end
                    continue
            i += 1

    return depth


def _try_rust_raw_string_start(source: str, i: int, n: int) -> tuple[int, int]:
    """Try to match a Rust raw string opening at position *i*.

    Handles ``r""``, ``r#""#``, ``br""``, ``br#""#``, ``b""``.

    Returns ``(chars_consumed, hash_count)``; ``(0, 0)`` if no match.
    """
    j = i
    if j < n and source[j] == "b":
        j += 1
    if j >= n:
        return 0, 0

    if source[j] == "r":
        j += 1
        hashes = 0
        while j < n and source[j] == "#":
            hashes += 1
            j += 1
        if j < n and source[j] == '"':
            return j - i + 1, hashes
        return 0, 0

    if source[j] == '"' and i < n and source[i] == "b":
        return j - i + 1, 0

    return 0, 0


def find_function_end(lines: list[str], start_line: int, language: str = "go") -> int:
    """Find the closing brace of a function starting at *start_line*.

    Scans lines beginning at *start_line* (0-indexed), counting braces
    with :func:`count_braces` (which correctly skips string literals and
    comments). Returns the 0-based index of the line containing the
    closing ``}`` that brings depth back to zero.

    If the function body is never closed (e.g. truncated source), returns
    ``len(lines) - 1``.
    """
    depth = 0
    found_open = False
    for idx in range(start_line, len(lines)):
        depth += count_braces(lines[idx], language)
        if depth > 0:
            found_open = True
        if found_open and depth <= 0:
            return idx
    return len(lines) - 1

# Patterns that identify test files.  A file is considered a test file if
# any path component matches one of these directory names, or if the
# basename matches common test-file naming conventions.
#
# "testdata" is Go's convention for embedding fixture files alongside
# package code; those files are test-only and must not appear in the gold
# patch.
_TEST_DIR_NAMES = {"test", "tests", "e2e", "testing", "testdata"}

_TEST_FILE_PATTERNS = [
    re.compile(r"^test_"),        # test_foo.py
    re.compile(r"_test\.go$"),    # foo_test.go  (Go in-package test files)
    re.compile(r"_test\.rs$"),    # foo_test.rs  (Rust convention)
    re.compile(r"_test\."),       # foo_test.py / foo_test.ts (other languages)
    re.compile(r"\.test\."),      # foo.test.ts
    re.compile(r"_spec\."),       # foo_spec.ts
    re.compile(r"\.spec\."),      # foo.spec.ts
]

_GITHUB_API_BASE = "https://api.github.com"


def is_test_file(path: str) -> bool:
    """Determine whether a file path refers to a test file.

    A file is a test file if any of its path components is ``test``,
    ``tests``, ``e2e``, ``testing``, or ``testdata``, or if its basename
    matches common test naming conventions (``test_*``, ``*_test.go``,
    ``*_test.*``, ``*.test.*``, ``*_spec.*``, ``*.spec.*``).

    Go-specific rules:
    - Files ending in ``_test.go`` are Go's in-package test files.
    - Files under a ``testdata/`` directory are test fixtures.

    Args:
        path: File path (forward-slash separated, as in a unified diff).

    Returns:
        True if the file is a test file.
    """
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")

    # Check directory components
    for part in parts:
        if part.lower() in _TEST_DIR_NAMES:
            return True

    # Also catch Java convention: src/test/...
    if normalized.startswith("src/test/") or "/src/test/" in normalized:
        return True

    # Check basename against patterns
    basename = parts[-1] if parts else ""
    for pattern in _TEST_FILE_PATTERNS:
        if pattern.search(basename):
            return True

    return False


def split_patch(diff_text: str | None) -> tuple[str | None, str | None]:
    """Split a unified diff into a gold patch and a test patch.

    Hunks from test files (identified by :func:`is_test_file`) go into the
    test patch; everything else goes into the gold patch.

    Args:
        diff_text: Full unified diff text from a PR.

    Returns:
        A ``(gold_patch, test_patch)`` tuple. Either value is ``None`` if
        there are no hunks for that category.
    """
    if not diff_text or not diff_text.strip():
        return None, None

    try:
        patch_set = PatchSet(StringIO(diff_text))
    except Exception:
        logger.warning("Failed to parse diff, returning raw diff as gold patch")
        return diff_text, None

    gold_files: list[str] = []
    test_files: list[str] = []

    for patched_file in patch_set:
        # unidiff uses the target path (b/...) for the file path
        file_path = patched_file.path
        file_str = str(patched_file)

        if is_test_file(file_path):
            test_files.append(file_str)
        else:
            gold_files.append(file_str)

    gold_patch = "".join(gold_files) if gold_files else None
    test_patch = "".join(test_files) if test_files else None

    return gold_patch, test_patch


def _make_headers(token: str | None) -> dict[str, str]:
    """Build HTTP headers for GitHub API requests."""
    return make_headers(token)


def _github_get(
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
) -> requests.Response | None:
    """Perform a GET request with basic error handling.

    Delegates to the shared :func:`swebenchify.github.github_get`.
    Returns None on 404 or other client errors to allow graceful
    degradation.
    """
    try:
        # Extract token from headers for the shared helper
        auth = headers.get("Authorization", "")
        token = auth.replace("token ", "") if auth.startswith("token ") else None
        resp = _shared_github_get(url, token=token, params=params, max_retries=1)
        if resp.status_code == 200:
            return resp
        if resp.status_code == 404:
            logger.warning("Resource not found: %s", url)
            return None
        resp.raise_for_status()
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning("HTTP request failed for %s: %s", url, exc)
    return None


def _fetch_problem_statement(
    owner: str,
    repo: str,
    issue_numbers: list[int],
    headers: dict[str, str],
) -> str | None:
    """Fetch and concatenate problem statements from linked issues.

    For each issue, concatenates ``title + "\\n" + body``.  Multiple
    issues are separated by ``\\n\\n``.

    Returns None if no issue could be fetched.
    """
    parts: list[str] = []
    for issue_num in issue_numbers:
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_num}"
        resp = _github_get(url, headers)
        if resp is None:
            continue
        data = resp.json()
        title = data.get("title") or ""
        body = data.get("body") or ""
        parts.append(f"{title}\n{body}")

    return "\n\n".join(parts) if parts else None


def _fetch_hints(
    owner: str,
    repo: str,
    issue_numbers: list[int],
    first_commit_date: str | None,
    headers: dict[str, str],
) -> str | None:
    """Fetch issue comments posted before the first PR commit.

    These comments serve as "hints" that a human solver might have seen
    before the fix was submitted.

    Args:
        owner: Repository owner.
        repo: Repository name.
        issue_numbers: Issue numbers to fetch comments for.
        first_commit_date: ISO 8601 timestamp of the first PR commit.
            Comments after this date are excluded.
        headers: HTTP headers for the GitHub API.

    Returns:
        Concatenated comment bodies, or None if no qualifying comments
        exist.
    """
    if first_commit_date is None:
        return None

    hint_parts: list[str] = []
    for issue_num in issue_numbers:
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_num}/comments"
        resp = _github_get(url, headers)
        if resp is None:
            continue
        comments = resp.json()
        for comment in comments:
            comment_date = comment.get("created_at", "")
            if comment_date < first_commit_date:
                body = comment.get("body") or ""
                if body.strip():
                    hint_parts.append(body)

    return "\n\n".join(hint_parts) if hint_parts else None


def _get_first_commit_date(
    owner: str,
    repo: str,
    pr_number: int,
    headers: dict[str, str],
) -> str | None:
    """Get the creation date of the first commit in a PR."""
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
    resp = _github_get(url, headers, params={"per_page": "1", "page": "1"})
    if resp is None:
        return None
    commits = resp.json()
    if not commits:
        return None
    # The commit date from the author
    commit_data = commits[0].get("commit", {})
    author_date = commit_data.get("author", {}).get("date")
    committer_date = commit_data.get("committer", {}).get("date")
    return author_date or committer_date


def extract_patches(
    candidate: CandidatePR,
    github_token: str | None = None,
) -> CandidateInstance:
    """Extract patches and problem statement from a CandidatePR.

    Downloads the PR diff, splits it into gold and test patches, fetches
    the problem statement from linked issues, and gathers hint comments.

    Args:
        candidate: The candidate PR to process.
        github_token: GitHub token for API authentication.

    Returns:
        A CandidateInstance with all extracted fields populated.
    """
    owner, repo_name = candidate.repo.split("/")
    headers = _make_headers(github_token)

    # 1. Download the PR diff (with auth token)
    diff_text = ""
    diff_url = candidate.diff_url
    try:
        diff_resp = _shared_github_get(diff_url, token=github_token, max_retries=5)
        if diff_resp.status_code == 200:
            diff_text = diff_resp.text
        else:
            logger.warning(
                "Failed to download diff for PR #%d (HTTP %d)",
                candidate.pr_number,
                diff_resp.status_code,
            )
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning(
            "Failed to download diff for PR #%d: %s",
            candidate.pr_number,
            exc,
        )

    # 2. Split into gold and test patches
    gold_patch, test_patch = split_patch(diff_text)

    # 3. Fetch problem statement
    problem_statement = _fetch_problem_statement(
        owner, repo_name, candidate.resolved_issues, headers
    )

    # Jira-only PRs: use PR title + body as problem statement
    if problem_statement is None and candidate.resolved_jira_issues:
        fallback = f"{candidate.title}\n{candidate.body or ''}".strip()
        problem_statement = fallback or None

    # 4. Get first commit date and fetch hints
    first_commit_date = _get_first_commit_date(
        owner, repo_name, candidate.pr_number, headers
    )
    hints_text = _fetch_hints(
        owner, repo_name, candidate.resolved_issues, first_commit_date, headers
    )

    # 5. Build instance_id
    instance_id = f"{owner}__{repo_name}-{candidate.pr_number}"

    return CandidateInstance(
        repo=candidate.repo,
        instance_id=instance_id,
        pr_number=candidate.pr_number,
        base_commit=candidate.base_commit,
        merge_commit=candidate.merge_commit,
        patch=gold_patch,
        test_patch=test_patch,
        problem_statement=problem_statement,
        hints_text=hints_text,
        created_at=candidate.created_at,
        resolved_issues=candidate.resolved_issues,
        resolved_jira_issues=candidate.resolved_jira_issues,
        merged_at=candidate.merged_at,
        link_confidence=candidate.link_confidence,
    )


def extract_all(
    prs: list[CandidatePR],
    github_token: str | None = None,
) -> list[CandidateInstance]:
    """Extract patches from a list of CandidatePRs.

    Processes each candidate sequentially and returns a list of
    :class:`CandidateInstance` objects.

    Args:
        prs: List of CandidatePR instances.
        github_token: GitHub token for API authentication.

    Returns:
        List of CandidateInstance objects.
    """
    instances: list[CandidateInstance] = []
    for i, pr in enumerate(prs):
        logger.info(
            "Extracting patches for PR #%d (%d/%d)",
            pr.pr_number,
            i + 1,
            len(prs),
        )
        instance = extract_patches(pr, github_token=github_token)
        instances.append(instance)
    return instances


def save_candidates(candidates: list[CandidateInstance], path: str) -> None:
    """Save a list of CandidateInstance objects to a JSONL file.

    Args:
        candidates: List of CandidateInstance instances to save.
        path: File path to write.
    """
    with open(path, "w") as f:
        for candidate in candidates:
            f.write(json.dumps(asdict(candidate)) + "\n")


def load_candidates(path: str) -> list[CandidateInstance]:
    """Load CandidateInstance objects from a JSONL file.

    Args:
        path: File path to read.

    Returns:
        List of CandidateInstance instances.
    """
    candidates: list[CandidateInstance] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            candidates.append(CandidateInstance(**data))
    return candidates
