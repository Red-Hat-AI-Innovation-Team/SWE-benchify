from __future__ import annotations

import logging
import re
from io import StringIO

from unidiff import PatchSet

from swebenchify.extractor import is_test_file

logger = logging.getLogger(__name__)

_DOC_EXTENSIONS = {".md", ".rst", ".adoc"}

_DOC_DIRS = {"docs", "doc"}

_DOC_ROOT_TXT = re.compile(r"^[^/]+\.txt$")

_DOC_BASENAMES = re.compile(
    r"^(README|CHANGELOG|HISTORY|AUTHORS|CONTRIBUTING|LICENSE)"
    r"(\..+)?$",
    re.IGNORECASE,
)

_AGENT_INSTRUCTION_FILES = {
    "claude.md",
    "agents.md",
    "gemini.md",
    "codex.md",
    ".cursorrules",
}

_AGENT_INSTRUCTION_DIRS = {".claude", ".cursor", ".codex"}

_TOOLING_DIRS = {".gitlab-ci"}

_TOOLING_BASENAMES = {
    "makefile",
    "dockerfile",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "cargo.toml",
    "go.mod",
    "go.sum",
    "gemfile",
    "package.json",
    "tsconfig.json",
}

_TOOLING_PREFIXES = [
    "dockerfile",
    "docker-compose",
    ".pre-commit-config",
    ".goreleaser",
    ".eslintrc",
    ".prettierrc",
    ".gitlab-ci",
]

_CI_CONFIG_PATTERNS = [
    re.compile(r"\.travis\.yml$"),
    re.compile(r"circle\.yml$"),
    re.compile(r"\.circleci/"),
    re.compile(r"Jenkinsfile$"),
    re.compile(r"azure-pipelines"),
    re.compile(r"appveyor\.yml$"),
    re.compile(r"\.buildkite/"),
    re.compile(r"cloudbuild\.yaml$"),
    re.compile(r"codecov\.yml$"),
    re.compile(r"\.codecov\.yml$"),
]


def is_doc_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1] if parts else ""

    if _DOC_BASENAMES.match(basename):
        return True

    _, ext = _splitext(basename)
    if ext in _DOC_EXTENSIONS:
        return True

    for part in parts[:-1]:
        if part.lower() in _DOC_DIRS:
            return True

    if len(parts) == 1 and ext == ".txt":
        return True

    if parts[0].lower() in _DOC_DIRS:
        return True

    return False


def is_tooling_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1] if parts else ""
    basename_lower = basename.lower()

    if parts[0] == ".github" and not _is_copilot_path(normalized):
        return True

    if basename_lower in _TOOLING_BASENAMES:
        return True

    for prefix in _TOOLING_PREFIXES:
        if basename_lower.startswith(prefix):
            return True

    for pattern in _CI_CONFIG_PATTERNS:
        if pattern.search(normalized):
            return True

    return False


def is_agent_instruction_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1] if parts else ""

    if basename.lower() in _AGENT_INSTRUCTION_FILES:
        return True

    for part in parts:
        if part.lower() in _AGENT_INSTRUCTION_DIRS:
            return True

    if _is_copilot_path(normalized):
        return True

    if basename.lower().startswith(".aider"):
        return True

    return False


def _is_copilot_path(normalized_path: str) -> bool:
    parts = normalized_path.split("/")
    if len(parts) >= 2 and parts[0] == ".github":
        return parts[1].lower().startswith("copilot")
    return False


def _splitext(basename: str) -> tuple[str, str]:
    dot = basename.rfind(".")
    if dot <= 0:
        return basename, ""
    return basename[:dot], basename[dot:]


def categorize_file(path: str) -> str:
    if is_test_file(path):
        return "test"
    if is_agent_instruction_file(path):
        return "agent_instruction"
    if is_doc_file(path):
        return "doc"
    if is_tooling_file(path):
        return "tooling"
    return "code"


def split_patch_5way(diff_text: str) -> dict[str, str | None]:
    categories = {
        "code_patch": [],
        "test_patch": [],
        "doc_patch": [],
        "tooling_patch": [],
        "agent_instruction_patch": [],
    }

    if not diff_text or not diff_text.strip():
        return {k: None for k in categories}

    try:
        patch_set = PatchSet(StringIO(diff_text))
    except Exception:
        logger.warning("Failed to parse diff, returning raw diff as code patch")
        return {
            "code_patch": diff_text,
            "test_patch": None,
            "doc_patch": None,
            "tooling_patch": None,
            "agent_instruction_patch": None,
        }

    _CATEGORY_TO_KEY = {
        "code": "code_patch",
        "test": "test_patch",
        "doc": "doc_patch",
        "tooling": "tooling_patch",
        "agent_instruction": "agent_instruction_patch",
    }

    for patched_file in patch_set:
        file_path = patched_file.path
        category = categorize_file(file_path)
        key = _CATEGORY_TO_KEY[category]
        categories[key].append(str(patched_file))

    return {
        k: "".join(v) if v else None
        for k, v in categories.items()
    }


def validate_patch_reconstruction(
    original_diff: str,
    patches: dict[str, str | None],
) -> bool:
    if not original_diff or not original_diff.strip():
        return all(v is None for v in patches.values())

    try:
        original_set = PatchSet(StringIO(original_diff))
    except Exception:
        return False

    original_files = {pf.path for pf in original_set}

    reconstructed_files: set[str] = set()
    for patch_text in patches.values():
        if patch_text is None:
            continue
        try:
            ps = PatchSet(StringIO(patch_text))
            for pf in ps:
                reconstructed_files.add(pf.path)
        except Exception:
            return False

    return original_files == reconstructed_files
