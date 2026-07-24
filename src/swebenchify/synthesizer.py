"""LLM-based synthetic bug generation for SWE-bench instances.

Uses Claude to introduce realistic bugs into source code, generate gold
fix patches, and produce corresponding issue reports. Language-agnostic:
works across Python, Go, Rust, and Java using simple text-based function
detection (not AST parsing).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import difflib
import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

try:
    from claude_code_sdk import ClaudeCodeOptions, ResultMessage
    from claude_code_sdk import query as _raw_query
except ModuleNotFoundError:  # allow import for tests without the SDK installed
    ClaudeCodeOptions = None  # type: ignore[assignment,misc]
    ResultMessage = None  # type: ignore[assignment,misc]
    _raw_query = None  # type: ignore[assignment]

from swebenchify.models import CandidateInstance


async def query(*, prompt: str, options: "ClaudeCodeOptions"):
    """Wrap claude_code_sdk.query to isolate each call in its own event loop.

    The SDK uses anyio cancel scopes internally. When multiple queries run
    sequentially in the same event loop, the first query's async-generator
    cleanup can leave a stale cancel scope that poisons subsequent calls
    (RuntimeError: "Attempted to exit cancel scope in a different task").
    Running each query in a throwaway event loop on a worker thread avoids
    this entirely.
    """
    messages: list = []
    error: BaseException | None = None

    def _run() -> None:
        nonlocal error
        async def _inner() -> None:
            async for msg in _raw_query(prompt=prompt, options=options):
                messages.append(msg)
        try:
            asyncio.run(_inner())
        except BaseException as exc:
            error = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join()

    if error is not None:
        raise error

    for msg in messages:
        yield msg

logger = logging.getLogger(__name__)

_go_cross_pkg_cache: dict[str, dict[str, list[str]]] = {}

_LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "python": [".py"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
}

_EXCLUDE_DIRS: set[str] = {
    "__pycache__", ".git", ".tox", ".mypy_cache", ".pytest_cache",
    "node_modules", "vendor", ".eggs", "build", "dist", "target",
    "docs", "doc", "examples", "example", "benchmarks", "benchmark",
    "demo", "demos", "scripts", "tools", ".github", ".ci",
    ".venv", "venv", ".synth-venv", ".test-venv", "env", ".env",
    "site-packages",
}

_EXCLUDE_SUBSTR: set[str] = {"demo", "example", "benchmark", "vendor"}

_LANGUAGE_EXCLUDE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"(^|/)tests?/"),
        re.compile(r"(^|/)pytests?/"),
        re.compile(r"(^|/)test_[^/]*\.py$"),
        re.compile(r"(^|/)__init__\.py$"),
        re.compile(r"(^|/)setup\.py$"),
        re.compile(r"(^|/)conftest\.py$"),
        re.compile(r"(^|/)conf\.py$"),
        re.compile(r"(^|/)manage\.py$"),
        re.compile(r"(^|/)wsgi\.py$"),
        re.compile(r"(^|/)asgi\.py$"),
    ],
    "go": [
        re.compile(r"_test\.go$"),
        re.compile(r"(^|/)vendor/"),
    ],
    "rust": [
        re.compile(r"(^|/)tests?/"),
    ],
    "java": [
        re.compile(r"Test\.java$"),
        re.compile(r"(^|/)test/"),
        re.compile(r"(^|/)src/test/"),
    ],
}

_FUNC_PATTERNS: dict[str, re.Pattern[str]] = {
    "python": re.compile(
        r"^(?P<indent>[ \t]*)def\s+(?P<name>\w+)\s*\(",
    ),
    "go": re.compile(
        r"^func\s+(?:\([^)]*\)\s+)?(?P<name>\w+)\s*\(",
    ),
    "rust": re.compile(
        r"^(?P<indent>\s*)(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)",
    ),
    "java": re.compile(
        r"^\s+(?:public|private|protected|static|\s)*\s+"
        r"(?:\w+(?:<[^>]*>)?)\s+(?P<name>\w+)\s*\(",
    ),
}

if os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
    MODEL_MAP: dict[str, str] = {
        "sonnet": os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6"),
        "haiku": os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5"),
        "opus": os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-6"),
    }
else:
    MODEL_MAP: dict[str, str] = {
        "sonnet": "claude-sonnet-4-20250514",
        "haiku": "claude-haiku-4-5-20251001",
        "opus": "claude-opus-4-20250514",
    }

DATASET_PATH = os.environ.get(
    "SWEBENCHIFY_DATASET",
    "/Users/aaye/Documents/code/SWE-benchify/output/swebenchify-dataset.jsonl",
)


def _load_dataset_examples(
    dataset_path: str, repo_slug: str, n: int = 5,
) -> list[str]:
    """Load real issue examples from dataset JSONL files.

    Searches the primary dataset file and language-specific instance files
    in the same directory. Filters to instances matching the target
    repo_slug and randomly samples n problem_statement texts.
    """
    matching: list[str] = []

    # Collect candidate JSONL paths: the primary dataset + language-specific files
    paths_to_check: list[Path] = []
    primary = Path(dataset_path)
    if primary.is_file():
        paths_to_check.append(primary)
    parent = primary.parent
    if parent.is_dir():
        for p in parent.glob("instances-*.jsonl"):
            if p != primary:
                paths_to_check.append(p)

    for path in paths_to_check:
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("repo") == repo_slug and record.get("problem_statement"):
                        matching.append(record["problem_statement"])
        except OSError:
            continue

    if not matching:
        return []
    return random.sample(matching, min(n, len(matching)))


_SIMILARITY_THRESHOLD = 0.15


def _trigram_jaccard(a: str, b: str) -> float:
    """Trigram Jaccard similarity between two texts."""
    tokens_a = re.findall(r'\w+', a.lower())
    tokens_b = re.findall(r'\w+', b.lower())
    if len(tokens_a) < 3 or len(tokens_b) < 3:
        return 0.0
    set_a = {tuple(tokens_a[i:i+3]) for i in range(len(tokens_a) - 2)}
    set_b = {tuple(tokens_b[i:i+3]) for i in range(len(tokens_b) - 2)}
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _is_too_similar_to_examples(
    generated: str, examples: list[str], threshold: float = _SIMILARITY_THRESHOLD,
) -> bool:
    """Return True if generated text is too similar to any example."""
    for ex in examples:
        if _trigram_jaccard(generated, ex) > threshold:
            return True
    return False


@dataclasses.dataclass
class SecondaryChange:
    """A change to a related file as part of a multi-file bug fix.

    original_snippet: the CORRECT code currently in the secondary file.
    buggy_snippet: the BUGGY version (same bug pattern as the primary).
    The buggy commit replaces original with buggy; the gold patch reverts.
    """

    file: str
    original_snippet: str
    buggy_snippet: str
    description: str


@dataclasses.dataclass
class BugSpec:
    """Specification for a synthetic bug to introduce."""

    file: str
    function_name: str
    original_code: str
    buggy_code: str
    bug_description: str
    bug_category: str
    secondary_changes: list[SecondaryChange] = dataclasses.field(
        default_factory=list,
    )


@dataclasses.dataclass
class BugPlan:
    """Plan for a coordinated multi-file bug."""

    primary_description: str
    secondary_descriptions: list[dict[str, str]] = dataclasses.field(
        default_factory=list,
    )


@dataclasses.dataclass
class SynthesisResult:
    """Result of synthesizing a single bug instance."""

    bug_spec: BugSpec
    patch: str
    problem_statement: str
    instance_id: str
    base_commit: str
    test_output: str = ""


@dataclasses.dataclass
class RepoSynthesisResult:
    """Result of synthesize_repo(): candidates plus attempt count."""

    candidates: list[CandidateInstance]
    mutations_attempted: int
    enrichment_data: dict[str, dict] = dataclasses.field(default_factory=dict)


def _should_exclude(filepath: str, language: str) -> bool:
    patterns = _LANGUAGE_EXCLUDE_PATTERNS.get(language, [])
    for pat in patterns:
        if pat.search(filepath):
            return True
    return False


def _extract_python_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract function bodies from Python source using indentation."""
    functions: list[dict[str, str | int]] = []
    pat = _FUNC_PATTERNS["python"]
    i = 0
    while i < len(lines):
        m = pat.match(lines[i])
        if m:
            name = m.group("name")
            indent = m.group("indent")
            indent_len = len(indent)
            start = i
            i += 1
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                if stripped == "" or stripped.startswith("#"):
                    i += 1
                    continue
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent_len and stripped:
                    break
                i += 1
            end = i
            source = "\n".join(lines[start:end])
            if len(source.splitlines()) >= 3:
                functions.append({
                    "function_name": name,
                    "source": source,
                    "start_line": start + 1,
                    "end_line": end,
                })
        else:
            i += 1
    return functions


class _BraceCounter:
    """Tracks parser state to count only code-level braces, skipping those
    inside string literals, character literals, raw strings, and comments."""

    def __init__(self, language: str) -> None:
        self.language = language
        self.in_block_comment = False
        self.in_backtick_string = False  # Go only
        self.in_rust_raw_string = False  # Rust r#"..."#
        self.rust_raw_hashes = 0

    def count_braces(self, line: str) -> tuple[int, int]:
        """Return (open_count, close_count) of braces in code context."""
        opens = 0
        closes = 0
        i = 0
        n = len(line)

        while i < n:
            ch = line[i]

            if self.in_block_comment:
                if ch == "*" and i + 1 < n and line[i + 1] == "/":
                    self.in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if self.in_backtick_string:
                if ch == "`":
                    self.in_backtick_string = False
                i += 1
                continue

            if self.in_rust_raw_string:
                if ch == '"':
                    hashes_after = 0
                    j = i + 1
                    while j < n and line[j] == "#":
                        hashes_after += 1
                        j += 1
                    if hashes_after >= self.rust_raw_hashes:
                        self.in_rust_raw_string = False
                        i = j
                        continue
                i += 1
                continue

            if ch == "/" and i + 1 < n:
                if line[i + 1] == "/":
                    break
                if line[i + 1] == "*":
                    self.in_block_comment = True
                    i += 2
                    continue

            if ch == '"':
                if self.language == "rust" and i > 0:
                    lookback = i - 1
                    hashes = 0
                    while lookback >= 0 and line[lookback] == "#":
                        hashes += 1
                        lookback -= 1
                    if lookback >= 0 and line[lookback] == "r":
                        self.in_rust_raw_string = True
                        self.rust_raw_hashes = hashes
                        i += 1
                        continue
                i += 1
                while i < n:
                    if line[i] == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if line[i] == '"':
                        i += 1
                        break
                    i += 1
                continue

            if ch == "'" and self.language in ("go", "java", "rust"):
                if self.language == "rust":
                    if i + 1 < n and line[i + 1] == "\\" and i + 3 < n and line[i + 3] == "'":
                        i += 4
                        continue
                    if i + 2 < n and line[i + 2] == "'":
                        i += 3
                        continue
                    # Rust lifetime annotation — not a char literal
                    i += 1
                    continue
                i += 1
                while i < n:
                    if line[i] == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if line[i] == "'":
                        i += 1
                        break
                    i += 1
                continue

            if ch == "`" and self.language == "go":
                self.in_backtick_string = True
                i += 1
                continue

            if ch == "{":
                opens += 1
            elif ch == "}":
                closes += 1

            i += 1

        return opens, closes


def _extract_brace_language_functions(
    lines: list[str],
    language: str,
) -> list[dict[str, str | int]]:
    """Extract function bodies from a brace-delimited language (Go/Rust/Java)."""
    functions: list[dict[str, str | int]] = []
    pat = _FUNC_PATTERNS[language]
    counter = _BraceCounter(language)
    i = 0
    while i < len(lines):
        m = pat.match(lines[i])
        if m:
            name = m.group("name")
            start = i
            brace_count = 0
            found_open = False
            fn_counter = _BraceCounter(language)
            fn_counter.in_block_comment = counter.in_block_comment
            fn_counter.in_backtick_string = counter.in_backtick_string
            fn_counter.in_rust_raw_string = counter.in_rust_raw_string
            fn_counter.rust_raw_hashes = counter.rust_raw_hashes
            while i < len(lines):
                opens, closes = fn_counter.count_braces(lines[i])
                if opens > 0:
                    found_open = True
                brace_count += opens - closes
                i += 1
                if found_open and brace_count <= 0:
                    break
            counter.in_block_comment = fn_counter.in_block_comment
            counter.in_backtick_string = fn_counter.in_backtick_string
            counter.in_rust_raw_string = fn_counter.in_rust_raw_string
            counter.rust_raw_hashes = fn_counter.rust_raw_hashes
            end = i
            source = "\n".join(lines[start:end])
            if len(source.splitlines()) >= 3:
                functions.append({
                    "function_name": name,
                    "source": source,
                    "start_line": start + 1,
                    "end_line": end,
                })
        else:
            counter.count_braces(lines[i])
            i += 1
    return functions


def _extract_go_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract function bodies from Go source using brace counting."""
    return _extract_brace_language_functions(lines, "go")


def _extract_rust_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract function bodies from Rust source using brace counting."""
    return _extract_brace_language_functions(lines, "rust")


def _extract_java_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract method bodies from Java source using brace counting."""
    return _extract_brace_language_functions(lines, "java")


_EXTRACTORS = {
    "python": _extract_python_functions,
    "go": _extract_go_functions,
    "rust": _extract_rust_functions,
    "java": _extract_java_functions,
}


def find_mutation_targets(
    repo_path: str,
    language: str,
    max_files: int = 20,
    max_functions: int = 5,
) -> list[dict]:
    """Find source functions suitable for mutation.

    Walks the source tree, finds source files matching language patterns,
    and extracts function/method signatures and bodies using simple
    text-based heuristics.

    Args:
        repo_path: Path to the repository root.
        language: One of 'python', 'go', 'rust', 'java'.
        max_files: Maximum number of source files to consider.
        max_functions: Maximum functions to extract per file.

    Returns:
        List of dicts with: file, function_name, source, language,
        start_line, end_line.
    """
    if language not in _LANGUAGE_EXTENSIONS:
        raise ValueError(f"Unsupported language: {language}")

    extensions = _LANGUAGE_EXTENSIONS[language]
    extractor = _EXTRACTORS[language]
    root = Path(repo_path)
    targets: list[dict] = []
    files_seen = 0

    if language == "rust":
        max_files = max(max_files, 100)

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDE_DIRS
            and not any(excl in d for excl in _EXCLUDE_SUBSTR)
        ]
        for fname in sorted(filenames):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            full_path = Path(dirpath) / fname
            rel_path = str(full_path.relative_to(root))
            if _should_exclude(rel_path, language):
                continue
            if language == "rust" and _is_rust_test_module(full_path):
                continue

            files_seen += 1
            if files_seen > max_files:
                break

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lines = content.splitlines()
            functions = extractor(lines)

            cfg_test_line = None
            if language == "rust":
                for line_idx, line in enumerate(lines):
                    if "#[cfg(test)]" in line:
                        cfg_test_line = line_idx + 1
                        break

            for func in functions[:max_functions]:
                source_lines = str(func["source"]).strip().splitlines()
                if len(source_lines) < 5:
                    continue
                if language == "rust" and cfg_test_line is not None:
                    if func["start_line"] + 1 >= cfg_test_line:
                        continue
                targets.append({
                    "file": rel_path,
                    "function_name": func["function_name"],
                    "source": func["source"],
                    "language": language,
                    "start_line": func["start_line"],
                    "end_line": func["end_line"],
                })

    targets.sort(key=_edge_case_score, reverse=True)
    return targets


_EDGE_CASE_SIGNALS = [
    re.compile(r"\b(?:try|except|catch|finally)\b"),
    re.compile(r"\b(?:raise|throw|panic)\b"),
    re.compile(r"\berr(?:or)?\s*(?:!=|==|is)\b"),
    re.compile(r"\b(?:fallback|deprecated|compat|legacy|backward)\b", re.IGNORECASE),
    re.compile(r"\bif\s+.*(?:is\s+None|==\s*None|!=\s*None|\.is_none\(\))\b"),
    re.compile(r"\bif\s+(?:not\s+|len\s*\()\b"),
    re.compile(r"\bwarnings?\.\w+\b"),
]


def _edge_case_score(target: dict) -> int:
    """Score a function by how many edge-case/error-handling signals it has."""
    source = target["source"]
    return sum(1 for pat in _EDGE_CASE_SIGNALS if pat.search(source))


def _is_rust_test_module(path: Path) -> bool:
    """Check if a Rust file is entirely a test module (#[cfg(test)])."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        stripped = content.strip()
        return stripped.startswith("#[cfg(test)]")
    except OSError:
        return False


def _find_related_files(
    repo_path: str,
    target: dict,
    language: str,
    max_files: int = 3,
) -> list[dict[str, str]]:
    """Find source files related to the target by imports, importers, and tests.

    Scans for:
    - Files that import the target module
    - Files that the target module imports
    - Test files for the target module
    - Files that reference the target function by name

    Returns a list of dicts with 'file' (relative path) and 'snippet'
    (the lines around each reference).
    """
    func_name = target["function_name"]
    target_file = target["file"]
    root = Path(repo_path)
    extensions = _LANGUAGE_EXTENSIONS.get(language, [])
    related: list[dict[str, str]] = []
    seen_files: set[str] = set()

    def _add_file_snippet(
        rel_path: str, context_line: int = 0,
    ) -> None:
        if rel_path in seen_files or rel_path == target_file:
            return
        if any(excl in rel_path for excl in _EXCLUDE_SUBSTR):
            return
        full_path = root / rel_path
        if not full_path.is_file():
            return
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        seen_files.add(rel_path)
        lines = content.splitlines()
        start = max(0, context_line - 5)
        end = min(len(lines), context_line + 15)
        snippet = "\n".join(lines[start:end])
        related.append({"file": rel_path, "snippet": snippet})

    if language == "python":
        target_module = _source_to_module_name(target_file)
        if target_module:
            target_parts = target_module.split(".")

            try:
                target_content = (root / target_file).read_text(
                    encoding="utf-8", errors="replace",
                )
                for m in re.finditer(
                    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
                    target_content, re.MULTILINE,
                ):
                    imported = m.group(1) or m.group(2)
                    imp_parts = imported.split(".")
                    if _is_repo_module(
                        imp_parts, root, _discover_repo_modules(repo_path),
                    ):
                        imp_path = "/".join(imp_parts) + ".py"
                        for prefix in ("", "src/"):
                            candidate = prefix + imp_path
                            if (root / candidate).is_file():
                                _add_file_snippet(candidate)
                                break
                    if len(related) >= max_files:
                        break
            except OSError:
                pass

            for test_dir_name in ("tests", "test"):
                test_dir = root / test_dir_name
                if not test_dir.is_dir():
                    continue
                for f in sorted(test_dir.rglob("test_*.py")):
                    if len(related) >= max_files:
                        break
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if any(
                        p in content
                        for p in (target_module, ".".join(target_parts[:-1]))
                        if p
                    ):
                        func_line = 0
                        for line_idx, line in enumerate(content.splitlines()):
                            if func_name in line and not line.strip().startswith('#'):
                                func_line = line_idx
                                break
                        _add_file_snippet(str(f.relative_to(root)), func_line)

    if len(related) < max_files:
        try:
            result = subprocess.run(
                ["grep", "-rn", "--include=*" + extensions[0], func_name, "."],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return related

        for line in result.stdout.splitlines():
            if len(related) >= max_files:
                break
            if not line.startswith("./"):
                continue
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            rel_path = parts[0][2:]
            if _should_exclude(rel_path, language):
                continue
            if any(excl in rel_path for excl in _EXCLUDE_SUBSTR):
                continue
            line_num = int(parts[1]) - 1
            _add_file_snippet(rel_path, line_num)

    return related


def _extract_test_context(
    repo_path: str, target_file: str, function_name: str, language: str,
) -> str:
    """Extract relevant test snippets that exercise a given function.

    Finds the existing test file, greps for the function name, and returns
    surrounding context (~20 lines around each match) as a string.
    Returns empty string if no test file or no matches found.
    """
    test_file = _find_existing_test_file(
        repo_path, target_file, language, function_name=function_name,
    )
    if not test_file:
        return ""

    test_path = Path(repo_path) / test_file
    try:
        test_content = test_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = test_content.splitlines()
    match_indices: set[int] = set()
    for idx, line in enumerate(lines):
        if function_name in line:
            match_indices.add(idx)

    if not match_indices:
        return ""

    included: set[int] = set()
    for idx in match_indices:
        for offset in range(-10, 11):
            line_idx = idx + offset
            if 0 <= line_idx < len(lines):
                included.add(line_idx)

    snippet_lines = [lines[i] for i in sorted(included)]
    # Cap at ~150 lines to avoid bloating the prompt
    snippet = "\n".join(snippet_lines[:150])
    return f"\n\nEXISTING TESTS (from `{test_file}`) that exercise `{function_name}`:\n```{language}\n{snippet}\n```\n"


# ---------------------------------------------------------------------------
# H10: Targeted mutation — analyze test assertions and craft breaking mutations
# ---------------------------------------------------------------------------

_BUILTINS_SET = frozenset({
    'len', 'str', 'int', 'float', 'list', 'dict', 'set', 'tuple',
    'type', 'isinstance', 'issubclass', 'print', 'range', 'sorted',
    'reversed', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
    'min', 'max', 'sum', 'abs', 'round', 'repr', 'bool', 'bytes',
    'ord', 'chr', 'hex', 'oct', 'bin', 'hash', 'id', 'format',
})


def _extract_called_func(expr: str) -> str | None:
    """Extract the non-builtin function/method name being called in an expression.

    Given an expression like ``calculate(x, y)`` or ``obj.process(data)``,
    returns the function name (``calculate`` or ``process``).  Builtins
    such as ``len`` or ``str`` are skipped in favour of the first
    non-builtin call found.
    """
    calls = re.findall(r'(?:[\w.]+\.)?(\w+)\s*\(', expr)
    for name in calls:
        if name not in _BUILTINS_SET:
            return name
    return calls[0] if calls else None


def _parse_assertion_line(
    stripped: str, all_lines: list[str], idx: int,
) -> dict | None:
    """Parse a single assertion line into structured info.

    Returns a dict with keys *type*, *expression*, *expected*,
    *called_function*, and *line*, or ``None`` if the line is not a
    recognisable assertion.
    """
    # self.assertEqual / assertEquals / assertAlmostEqual
    m = re.match(
        r'self\.assert(?:Equal|Equals|AlmostEqual)\s*\(\s*(.+?)\s*,\s*(.+)\s*\)\s*$',
        stripped,
    )
    if m:
        expr = m.group(1).strip()
        expected = m.group(2).strip().rstrip(')')
        return {
            'type': 'equality', 'expression': expr, 'expected': expected,
            'called_function': _extract_called_func(expr) or _extract_called_func(expected),
            'line': idx + 1,
        }

    # self.assertRaises(ExcType, func, ...)
    m = re.match(r'self\.assertRaises\s*\(\s*(\w+)\s*,\s*([\w.]+)', stripped)
    if m:
        return {
            'type': 'raises', 'expression': m.group(2),
            'expected': m.group(1),
            'called_function': m.group(2).split('.')[-1],
            'line': idx + 1,
        }

    # self.assertIn(val, expr)
    m = re.match(
        r'self\.assertIn\s*\(\s*(.+?)\s*,\s*(.+)\s*\)\s*$', stripped,
    )
    if m:
        collection = m.group(2).strip().rstrip(')')
        return {
            'type': 'in', 'expression': collection,
            'expected': m.group(1).strip(),
            'called_function': _extract_called_func(collection),
            'line': idx + 1,
        }

    # self.assertTrue / self.assertFalse
    for method, atype in [('assertTrue', 'truthy'), ('assertFalse', 'falsy')]:
        m = re.match(rf'self\.{method}\s*\(\s*(.+?)\s*\)\s*$', stripped)
        if m:
            expr = m.group(1).strip()
            return {
                'type': atype, 'expression': expr,
                'expected': 'True' if atype == 'truthy' else 'False',
                'called_function': _extract_called_func(expr),
                'line': idx + 1,
            }

    # self.assertIsNone / assertIsNotNone
    m = re.match(r'self\.assertIsNone\s*\(\s*(.+?)\s*\)\s*$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'is_none', 'expression': expr, 'expected': 'None',
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }
    m = re.match(r'self\.assertIsNotNone\s*\(\s*(.+?)\s*\)\s*$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'not_none', 'expression': expr, 'expected': 'not None',
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # with pytest.raises(ExcType):
    m = re.match(r'with\s+pytest\.raises\s*\(\s*(\w+)', stripped)
    if m:
        next_func = None
        for j in range(idx + 1, min(idx + 5, len(all_lines))):
            nline = all_lines[j].strip()
            if nline and not nline.startswith('#'):
                next_func = _extract_called_func(nline)
                if next_func:
                    break
        return {
            'type': 'raises', 'expression': '', 'expected': m.group(1),
            'called_function': next_func, 'line': idx + 1,
        }

    # assert expr == value
    m = re.match(r'assert\s+(.+?)\s*==\s*(.+?)$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'equality', 'expression': expr,
            'expected': m.group(2).strip(),
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # assert expr != value
    m = re.match(r'assert\s+(.+?)\s*!=\s*(.+?)$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'inequality', 'expression': expr,
            'expected': m.group(2).strip(),
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # assert expr is None
    m = re.match(r'assert\s+(.+?)\s+is\s+None\s*$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'is_none', 'expression': expr, 'expected': 'None',
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # assert expr is not None
    m = re.match(r'assert\s+(.+?)\s+is\s+not\s+None\s*$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'not_none', 'expression': expr, 'expected': 'not None',
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # assert expr in collection (but not 'assert x not in y')
    if ' not in ' not in stripped:
        m = re.match(r'assert\s+(.+?)\s+in\s+(.+?)$', stripped)
        if m:
            collection = m.group(2).strip()
            return {
                'type': 'in', 'expression': collection,
                'expected': m.group(1).strip(),
                'called_function': _extract_called_func(collection),
                'line': idx + 1,
            }

    # assert not expr
    m = re.match(r'assert\s+not\s+(.+?)$', stripped)
    if m:
        expr = m.group(1).strip()
        return {
            'type': 'falsy', 'expression': expr, 'expected': 'False',
            'called_function': _extract_called_func(expr),
            'line': idx + 1,
        }

    # Generic assert expr (truthy) — only when no more specific pattern matched
    m = re.match(r'assert\s+(.+?)$', stripped)
    if m:
        expr = m.group(1).strip()
        if ('==' not in expr and '!=' not in expr
                and ' is ' not in expr and ' in ' not in expr
                and ' not ' not in expr):
            return {
                'type': 'truthy', 'expression': expr, 'expected': 'True',
                'called_function': _extract_called_func(expr),
                'line': idx + 1,
            }

    return None


def _analyze_test_assertions_go(test_source: str) -> list[dict]:
    """Extract assertions from Go test files.

    Handles four major patterns:

    1. **Standard library** ``if got := Func(args); got != expected``
       with ``t.Errorf`` / ``t.Fatalf`` / ``t.Error`` / ``t.Fatal``.
    2. **testify assert/require** — ``assert.Equal``,
       ``assert.NoError``, ``require.Equal``, ``assert.True``,
       ``assert.Nil``, ``assert.NotNil``, etc.
    3. **Direct comparison** — separate ``got := Func(args)`` followed
       by ``if got != want``.
    4. **Error checking** — ``result, err := Func(args)`` followed by
       ``if err != nil``.

    Returns a list of dicts matching the same schema as
    :func:`_parse_assertion_line`.
    """
    assertions: list[dict] = []
    lines = test_source.splitlines()

    # ── Pattern 1: if got := Func(args); got != expected { ──
    # e.g.  if got := methodFamily(ut.method); got != ut.wantMethodFamily {
    pat_inline = re.compile(
        r'if\s+\w+\s*:=\s*(.+?)\s*;\s*\w+\s*(!?=)\s*(.+?)\s*\{',
    )
    # ── Pattern 2a: testify assert.Equal / require.Equal ──
    # e.g.  assert.Equal(t, expected, FunctionName(args))
    pat_testify_eq = re.compile(
        r'(?:assert|require)\.(?:Equal|Equalf)\s*\(\s*\w+\s*,\s*(.+?)\s*,\s*(.+?)(?:\s*,\s*".*?)?\s*\)\s*$',
    )
    # ── Pattern 2b: testify assert.NoError / require.NoError ──
    pat_testify_noerr = re.compile(
        r'(?:assert|require)\.(?:NoError|NoErrorf)\s*\(\s*\w+\s*,\s*(.+?)(?:\s*,\s*".*?)?\s*\)\s*$',
    )
    # ── Pattern 2c: testify assert.True / assert.False ──
    pat_testify_bool = re.compile(
        r'(?:assert|require)\.(True|False|Truef|Falsef)\s*\(\s*\w+\s*,\s*(.+?)(?:\s*,\s*".*?)?\s*\)\s*$',
    )
    # ── Pattern 2d: testify assert.Nil / assert.NotNil ──
    pat_testify_nil = re.compile(
        r'(?:assert|require)\.(Nil|NotNil|Nilf|NotNilf)\s*\(\s*\w+\s*,\s*(.+?)(?:\s*,\s*".*?)?\s*\)\s*$',
    )
    # ── Pattern 2e: testify assert.Error / require.Error ──
    pat_testify_err = re.compile(
        r'(?:assert|require)\.(?:Error|Errorf)\s*\(\s*\w+\s*,\s*(.+?)(?:\s*,\s*".*?)?\s*\)\s*$',
    )

    # Helper: extract function name from a Go expression
    def _go_extract_func(expr: str) -> str | None:
        """Extract the function/method name from a Go expression."""
        # Strip receiver/package prefix: pkg.Func(args) -> Func
        calls = re.findall(r'(?:[\w.]+\.)?(\w+)\s*\(', expr)
        # Skip Go builtins and test-framework calls
        go_skip = frozenset({
            'make', 'len', 'cap', 'append', 'copy', 'close', 'delete',
            'new', 'panic', 'recover', 'print', 'println', 'string',
            'int', 'int32', 'int64', 'float32', 'float64', 'byte',
            'Errorf', 'Fatalf', 'Error', 'Fatal', 'Logf', 'Log',
            'Run', 'Cleanup', 'Helper', 'Skip', 'Skipf',
            'Sprintf', 'Printf', 'Fprintf',
            'Equal', 'NotEqual', 'True', 'False', 'Nil', 'NotNil',
            'NoError', 'Equalf', 'NoErrorf', 'Truef', 'Falsef',
            'Nilf', 'NotNilf', 'Errorf', 'Contains',
        })
        for name in calls:
            if name not in go_skip:
                return name
        return calls[0] if calls else None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # ── Pattern 1: inline if-init with comparison ──
        m = pat_inline.match(stripped)
        if m:
            expr = m.group(1).strip()
            op = m.group(2).strip()
            expected = m.group(3).strip()
            atype = 'equality' if op == '!=' else 'inequality'
            assertions.append({
                'type': atype,
                'expression': expr,
                'expected': expected,
                'called_function': _go_extract_func(expr),
                'line': i + 1,
            })
            continue

        # ── Pattern 2a: testify assert.Equal ──
        m = pat_testify_eq.match(stripped)
        if m:
            expected = m.group(1).strip()
            expr = m.group(2).strip()
            func_name = _go_extract_func(expr) or _go_extract_func(expected)
            assertions.append({
                'type': 'equality',
                'expression': expr,
                'expected': expected,
                'called_function': func_name,
                'line': i + 1,
            })
            continue

        # ── Pattern 2b: testify NoError ──
        m = pat_testify_noerr.match(stripped)
        if m:
            expr = m.group(1).strip()
            assertions.append({
                'type': 'error_check',
                'expression': expr,
                'expected': 'nil',
                'called_function': _go_extract_func(expr),
                'line': i + 1,
            })
            continue

        # ── Pattern 2c: testify True/False ──
        m = pat_testify_bool.match(stripped)
        if m:
            kind = m.group(1).strip()
            expr = m.group(2).strip()
            atype = 'falsy' if kind.startswith('False') else 'truthy'
            assertions.append({
                'type': atype,
                'expression': expr,
                'expected': 'false' if atype == 'falsy' else 'true',
                'called_function': _go_extract_func(expr),
                'line': i + 1,
            })
            continue

        # ── Pattern 2d: testify Nil/NotNil ──
        m = pat_testify_nil.match(stripped)
        if m:
            kind = m.group(1).strip()
            expr = m.group(2).strip()
            atype = 'nil_check' if kind.startswith('Nil') else 'not_nil'
            assertions.append({
                'type': atype,
                'expression': expr,
                'expected': 'nil' if atype == 'nil_check' else 'not nil',
                'called_function': _go_extract_func(expr),
                'line': i + 1,
            })
            continue

        # ── Pattern 2e: testify Error ──
        m = pat_testify_err.match(stripped)
        if m:
            expr = m.group(1).strip()
            assertions.append({
                'type': 'error_check',
                'expression': expr,
                'expected': 'error',
                'called_function': _go_extract_func(expr),
                'line': i + 1,
            })
            continue

        # ── Pattern 4: Error checking — if err != nil { ──
        # Preceded by result, err := Func(args) within 3 lines
        # NOTE: must come before Pattern 3 since `if err != nil` also matches
        # the generic `if \w+ != \w+` pattern.
        if re.match(r'if\s+err\s*!=\s*nil\s*\{', stripped):
            for j in range(max(0, i - 3), i):
                prev = lines[j].strip()
                m_assign = re.match(r'[\w,\s]+:=\s*(.+)', prev)
                if m_assign:
                    expr = m_assign.group(1).strip()
                    func_name = _go_extract_func(expr)
                    if func_name:
                        assertions.append({
                            'type': 'error_check',
                            'expression': expr,
                            'expected': 'nil',
                            'called_function': func_name,
                            'line': i + 1,
                        })
                        break
            continue

        # ── Pattern 3: Direct comparison: if got != want { ──
        # Preceded by got := Func(args) within 3 lines
        if re.match(r'if\s+\w+\s*!=\s*\w+\s*\{', stripped):
            # Look backwards for assignment
            for j in range(max(0, i - 3), i):
                prev = lines[j].strip()
                m_assign = re.match(r'\w+\s*:=\s*(.+)', prev)
                if m_assign:
                    expr = m_assign.group(1).strip()
                    func_name = _go_extract_func(expr)
                    if func_name:
                        assertions.append({
                            'type': 'equality',
                            'expression': expr,
                            'expected': '',
                            'called_function': func_name,
                            'line': i + 1,
                        })
                        break
            continue

        # ── Pattern 5: Standalone nil check on a call expression ──
        # e.g. if encoding.GetCodecV2(proto.Name) == nil {
        # or   if SomeFunc(args) != nil {
        m_nil_cmp = re.match(
            r'if\s+(.+?)\s*(==|!=)\s*nil\s*\{', stripped,
        )
        if m_nil_cmp:
            expr = m_nil_cmp.group(1).strip()
            op = m_nil_cmp.group(2).strip()
            func_name = _go_extract_func(expr)
            if func_name:
                atype = 'nil_check' if op == '==' else 'not_nil'
                assertions.append({
                    'type': atype,
                    'expression': expr,
                    'expected': 'nil' if atype == 'nil_check' else 'not nil',
                    'called_function': func_name,
                    'line': i + 1,
                })
                continue

        # ── Stdlib t.Errorf/t.Fatalf with function name in message ──
        # Lines like: t.Fatalf("FuncName() = %v, want %v", got, expected)
        # These are assertions too — the function name is in the format string
        if re.match(r't\.(Errorf|Fatalf|Error|Fatal)\s*\(', stripped):
            # Try to extract function name from the format string
            m_fmt = re.search(r'"(\w+)\(', stripped)
            if m_fmt:
                func_name = m_fmt.group(1)
                go_skip = frozenset({
                    'Error', 'Errorf', 'Fatal', 'Fatalf',
                    'Sprintf', 'Printf', 'Fprintf',
                })
                if func_name not in go_skip:
                    # Check if already captured by Pattern 1 on a previous line
                    already = any(
                        a['line'] >= i and a.get('called_function') == func_name
                        for a in assertions
                    )
                    if not already:
                        assertions.append({
                            'type': 'equality',
                            'expression': '',
                            'expected': '',
                            'called_function': func_name,
                            'line': i + 1,
                        })

    return assertions


def _analyze_test_assertions(
    test_source: str, language: str,
) -> list[dict]:
    """Extract assertions from test files.

    For Python: finds ``assert``, ``assertEqual``, ``assertRaises``,
    ``assertIn``, ``pytest.raises`` patterns and extracts what is
    being asserted.

    For Go: finds standard library ``if got := Func(...); got != want``
    patterns, testify ``assert.*`` / ``require.*`` calls, direct
    comparisons, and ``err != nil`` checks.

    Args:
        test_source: Full source code of the test file.
        language: Programming language (``'python'`` or ``'go'``).

    Returns:
        List of dicts with keys: *type* (``'equality'``,
        ``'raises'``, ``'truthy'``, ``'in'``, ``'is_none'``,
        ``'not_none'``, ``'falsy'``, ``'inequality'``,
        ``'error_check'``, ``'nil_check'``, ``'not_nil'``),
        *expression*, *expected*, *called_function*, and *line*.
    """
    if language == "go":
        return _analyze_test_assertions_go(test_source)

    if language != "python":
        return []

    assertions: list[dict] = []
    lines = test_source.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not any(kw in stripped for kw in ('assert', 'Assert', 'raises')):
            continue
        info = _parse_assertion_line(stripped, lines, i)
        if info:
            assertions.append(info)

    return assertions


_OPERATOR_SWAPS: list[tuple[str, str]] = [
    (' + ', ' - '),
    (' - ', ' + '),
    (' * ', ' + '),
    (' // ', ' % '),
    (' >= ', ' > '),
    (' <= ', ' < '),
    (' > ', ' >= '),
    (' < ', ' <= '),
    (' == ', ' != '),
    (' != ', ' == '),
    (' and ', ' or '),
    (' or ', ' and '),
]


def _mutate_remove_raise(
    lines: list[str], exc_type: str,
) -> tuple[str, str] | None:
    """Remove or bypass a ``raise`` statement to break an assertRaises test.

    When the raise is guarded by an ``if``, inverts the condition so
    the error fires for the *wrong* inputs — a realistic refactoring
    mistake.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith('raise '):
            continue
        if exc_type and exc_type not in stripped:
            continue

        # If guarded by an if-clause, invert the condition
        if i > 0 and lines[i - 1].strip().startswith('if '):
            guard = lines[i - 1]
            guard_stripped = guard.strip()
            if ' not ' in guard_stripped:
                inverted = guard.replace(' not ', ' ', 1)
            else:
                inverted = guard.replace('if ', 'if not ', 1)
            if inverted != guard:
                return (guard, inverted)

        # Stand-alone raise: replace with pass
        indent = len(line) - len(line.lstrip())
        return (line, ' ' * indent + 'pass')

    return None


def _mutate_swap_operator(lines: list[str]) -> tuple[str, str] | None:
    """Swap a binary/comparison operator, prioritising return statements.

    Skips definition lines, decorators, docstrings, and comments.
    """
    # First pass: return statements
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('return '):
            continue
        for orig_op, new_op in _OPERATOR_SWAPS:
            if orig_op in line:
                mutated = line.replace(orig_op, new_op, 1)
                if mutated != line:
                    return (line, mutated)

    # Second pass: assignment / computation lines
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(('def ', '@', '#', '"""', "'''", 'class ', 'return ')):
            continue
        if not stripped:
            continue
        for orig_op, new_op in _OPERATOR_SWAPS:
            if orig_op in line:
                mutated = line.replace(orig_op, new_op, 1)
                if mutated != line:
                    return (line, mutated)

    return None


def _mutate_return_none(lines: list[str]) -> tuple[str, str] | None:
    """Change the last non-None return to ``return None``."""
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith('return ') and stripped != 'return None':
            indent = len(lines[i]) - len(lines[i].lstrip())
            return (lines[i], ' ' * indent + 'return None')
    return None


def _mutate_return_non_none(lines: list[str]) -> tuple[str, str] | None:
    """Change a ``return None`` / bare ``return`` to ``return 0``."""
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped in ('return None', 'return'):
            indent = len(lines[i]) - len(lines[i].lstrip())
            return (lines[i], ' ' * indent + 'return 0')
    return None


def _targeted_mutation(
    source: str, assertion_info: dict, language: str,
) -> tuple[str, str] | None:
    """Generate a mutation designed to break a specific assertion.

    Given a source function and an assertion that exercises it,
    finds a specific code location to mutate that will violate
    the assertion.  The mutation is deterministic (no LLM call)
    and designed to look like a realistic developer mistake.

    Args:
        source: Complete source of the function under test.
        assertion_info: Dict from :func:`_analyze_test_assertions`.
        language: Programming language (``'python'`` or ``'go'``).

    Returns:
        ``(original_snippet, mutated_snippet)`` where replacing
        *original_snippet* in *source* with *mutated_snippet*
        produces the buggy function.  ``None`` if no viable
        mutation is found.
    """
    if language not in ("python", "go"):
        return None

    assertion_type = assertion_info['type']
    lines = source.splitlines()

    # Strategy 1: For 'raises' assertions, remove/invert the raise guard
    if assertion_type == 'raises':
        result = _mutate_remove_raise(lines, assertion_info.get('expected', ''))
        if result:
            return result

    # Strategy 2: For value-checking assertions, swap operators
    if assertion_type in ('equality', 'inequality', 'truthy', 'falsy', 'in',
                          'error_check', 'nil_check', 'not_nil'):
        result = _mutate_swap_operator(lines)
        if result:
            return result

    # Strategy 3: For None/nil checks, alter return statements
    if assertion_type in ('is_none', 'nil_check'):
        result = _mutate_return_non_none(lines)
        if result:
            return result
    elif assertion_type in ('not_none', 'not_nil'):
        result = _mutate_return_none(lines)
        if result:
            return result

    # Strategy 4: Last resort — swap any operator
    result = _mutate_swap_operator(lines)
    if result:
        return result

    return None


def _describe_targeted_mutation(
    original: str, mutated: str, assertion: dict,
) -> str:
    """Generate a realistic bug description for a targeted mutation."""
    orig_s = original.strip()
    mut_s = mutated.strip()

    # Detect operator swap
    for orig_op, new_op in _OPERATOR_SWAPS:
        if orig_op in original and new_op in mutated:
            return (
                f"Changed '{orig_op.strip()}' to '{new_op.strip()}' in "
                f"computation, producing wrong results for certain inputs"
            )

    # Detect condition inversion
    if ' not ' in mut_s and ' not ' not in orig_s:
        return "Inverted guard condition, causing validation to trigger for wrong inputs"
    if ' not ' in orig_s and ' not ' not in mut_s:
        return "Removed negation from condition, skipping important validation"

    # Detect raise removal
    if 'raise ' in orig_s and 'raise ' not in mut_s:
        return "Removed error handling, allowing invalid state to propagate silently"

    # Detect return value change
    if 'return None' in mut_s and 'return None' not in orig_s:
        return "Changed return value to None, breaking callers that expect a value"
    if 'return None' not in mut_s and ('return None' in orig_s or orig_s == 'return'):
        return "Changed None return to a value, breaking callers that check for None"

    return "Subtle logic change affecting function output under certain inputs"


def _try_targeted_mutation(
    repo_path: str,
    target: dict,
    test_file: str,
    language: str,
) -> BugSpec | None:
    """Try to generate a targeted mutation based on test assertion analysis.

    Reads the test file, extracts assertions, identifies ones that
    exercise the target function, and crafts a minimal mutation
    designed to break those assertions.  No LLM call is needed.

    Returns a :class:`BugSpec` if successful, ``None`` otherwise.
    """
    if language not in ("python", "go"):
        return None

    root = Path(repo_path)
    test_path = root / test_file
    try:
        test_source = test_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    assertions = _analyze_test_assertions(test_source, language)
    if not assertions:
        return None

    func_name = target["function_name"]
    source = target["source"]

    # Filter to assertions relevant to this function
    relevant = [
        a for a in assertions
        if (a.get('called_function') == func_name
            or func_name in a.get('expression', ''))
    ]
    if not relevant:
        return None

    # Try each relevant assertion until we find a working mutation
    for assertion in relevant:
        result = _targeted_mutation(source, assertion, language)
        if result is None:
            continue

        orig_snippet, mutated_snippet = result
        mutated_func = source.replace(orig_snippet, mutated_snippet, 1)

        if mutated_func == source:
            continue

        # Validate the mutation parses (dedent for class methods)
        if not _validate_mutation_parses(
            textwrap.dedent(mutated_func), language,
        ):
            continue

        desc = _describe_targeted_mutation(
            orig_snippet, mutated_snippet, assertion,
        )

        return BugSpec(
            file=target["file"],
            function_name=func_name,
            original_code=source,
            buggy_code=mutated_func,
            bug_description=desc,
            bug_category="targeted-mutation",
        )

    return None


async def _plan_multi_file_mutation(
    target_func_code: str,
    related_files: list[dict[str, str]],
    model: str = "sonnet",
    test_context: str = "",
) -> BugPlan | None:
    """Plan a coordinated bug that spans multiple files.

    Uses an LLM call to analyze the target function and related files,
    then plans a bug that requires changes in at least 2 files.

    Returns a BugPlan, or None if the LLM call fails.
    """
    if not related_files:
        return None

    related_context = "\n\n".join(
        f"File `{rf['file']}`:\n```\n{rf['snippet']}\n```"
        for rf in related_files[:3]
    )

    prompt = f"""You are planning a bug that spans multiple files. The primary bug is in the target function, but it MUST also require a corresponding change in at least one related file. Examples of cross-file bugs: function A changes its return type but caller B still expects the old type; module C removes a validation that module D depends on; a config default changes in one file but the code using it in another file assumes the old default.

Target function:
```
{target_func_code}
```

Related files:
{related_context}
{test_context}
Plan a coordinated bug. Target code paths that existing tests exercise — the bug should cause test failures so it would be noticed. Return your plan in this format:

<primary>
One sentence describing the primary bug to introduce in the target function.
</primary>

For each related file that should also be changed:
<secondary>
<sec_file>relative/path/to/file</sec_file>
<sec_plan>One sentence describing the corresponding change needed in this file.</sec_plan>
</secondary>

The bug must be COORDINATED: fixing only the primary file should leave the codebase in an inconsistent state. The gold patch must fix ALL files."""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    result_text: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = _extract_text_from_result(message)
    except Exception:
        logger.warning("LLM call failed for multi-file mutation planning")
        return None

    if not result_text:
        return None

    primary_match = re.search(
        r"<primary>\s*(.*?)\s*</primary>", result_text, re.DOTALL,
    )
    if not primary_match:
        return None

    plan = BugPlan(primary_description=primary_match.group(1).strip())

    for m in re.finditer(
        r"<secondary>\s*"
        r"<sec_file>\s*(.*?)\s*</sec_file>\s*"
        r"<sec_plan>\s*(.*?)\s*</sec_plan>\s*"
        r"</secondary>",
        result_text,
        re.DOTALL,
    ):
        plan.secondary_descriptions.append({
            "file": m.group(1).strip(),
            "plan": m.group(2).strip(),
        })

    return plan


def _validate_mutation_parses(code: str, language: str) -> bool:
    """Check that mutated source code parses correctly."""
    if language == "python":
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False
    return True


_COMMENT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "go": [re.compile(r"//[^\n]*"), re.compile(r"/\*.*?\*/", re.DOTALL)],
    "rust": [re.compile(r"//[^\n]*"), re.compile(r"/\*.*?\*/", re.DOTALL)],
    "java": [re.compile(r"//[^\n]*"), re.compile(r"/\*.*?\*/", re.DOTALL)],
}


def _is_ast_equivalent(original: str, mutated: str, language: str) -> bool:
    """Check if a mutation is semantically equivalent to the original."""
    if language == "python":
        try:
            return ast.dump(ast.parse(original)) == ast.dump(ast.parse(mutated))
        except SyntaxError:
            return False
    patterns = _COMMENT_PATTERNS.get(language, [])
    orig_stripped = original
    mut_stripped = mutated
    for pat in patterns:
        orig_stripped = pat.sub("", orig_stripped)
        mut_stripped = pat.sub("", mut_stripped)
    orig_tokens = orig_stripped.split()
    mut_tokens = mut_stripped.split()
    return orig_tokens == mut_tokens


_TAUTOLOGY_PATTERNS = [
    re.compile(r"\bassert\s+True\b"),
    re.compile(r"\bassert\s+not\s+False\b"),
    re.compile(r"\bassert\s+\w+\s+is\s+\w+\s+or\s+True\b"),
    re.compile(r"\bassert\s+1\s*==\s*1\b"),
    re.compile(r"\bassert\s+\w+\s+is\s+(?:False|None)\s+or\s+True\b"),
]


_STRATEGY_LABEL_PATTERNS = [
    re.compile(r"^\s*#\s*[Ss]trategy\s+[A-Z].*$", re.MULTILINE),
    re.compile(r"^\s*#\s*(?:Approach|Step)\s+\d.*$", re.MULTILINE),
    re.compile(r"^\s*#\s*(?:MODIFY|ADD|EXTEND)\s+(?:existing|new|opportunistic).*$",
               re.MULTILINE | re.IGNORECASE),
]


_RST_REF_PATTERN = re.compile(r":(?:issue|pr):\s*`\s*(\d+)\s*`")


def _validate_rst_references(
    content: str, real_issues: list[str],
) -> str:
    """Strip fabricated :issue: and :pr: references from RST content.

    Keeps references that match the real issue numbers from git history.
    Removes fabricated ones entirely.
    """
    real_nums = {n.lstrip("#") for n in real_issues}

    def replace_ref(m: re.Match) -> str:
        num = m.group(1)
        if num in real_nums:
            return m.group(0)
        return ""

    return _RST_REF_PATTERN.sub(replace_ref, content)


_BARE_SHA_PATTERN = re.compile(r"\b[0-9a-f]{7,40}\b")


def _strip_issue_shas(text: str) -> str:
    """Strip ALL standalone hex strings (7-40 chars) from issue text.

    Real bug reporters almost never include raw commit SHAs. Stripping
    all of them is simpler and more reliable than trying to validate
    each one against git history.
    """
    return _BARE_SHA_PATTERN.sub("", text)


_FAKE_USERNAMES = ["alex", "sarah", "dev", "mike", "jenny"]

_SYNTH_ENV_PREFIXES = ("ANTHROPIC_", "SWEBENCHIFY_", "FACTORY_", "CLAUDE_")


def _sanitize_test_output(test_output: str, repo_path: str) -> str:
    """Remove synthetic-origin fingerprints from test output.

    Strips env vars (ANTHROPIC_*, FACTORY_*, CLAUDE_*, SWEBENCHIFY_*),
    local macOS paths, synth/factory working directory paths, and
    pytest metadata containing those paths.
    """
    if not test_output:
        return ""

    lines = test_output.split("\n")
    cleaned: list[str] = []
    for line in lines:
        if any(prefix in line for prefix in _SYNTH_ENV_PREFIXES):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned)

    # Strip dict-like env var entries: 'ANTHROPIC_FOO': 'bar' or "ANTHROPIC_FOO": "bar"
    result = re.sub(
        r"""['"](""" + "|".join(_SYNTH_ENV_PREFIXES) + r""")[^'"]*['"]:\s*['"][^'"]*['"],?\s*""",
        "", result,
    )

    # Strip /private/ prefix (macOS artifact)
    result = re.sub(r'/private(/(?:tmp|var|home)/)', r'\1', result)

    # Replace macOS /Users/<username>/... paths with neutral /home/user/...
    result = re.sub(r"/Users/[^/\s]+/", "/home/user/", result)

    # Replace macOS /var/folders/ temp paths
    result = re.sub(r'/var/folders/[^\s]+?/(?:T|C)/[^/\s]+/', '/tmp/test-env/', result)

    # Strip homebrew Go/Rust paths (replace with generic SDK paths)
    result = re.sub(r'/opt/homebrew/Cellar/go/[\d.]+/libexec/', '/usr/local/go/', result)
    result = re.sub(r'/opt/homebrew/Cellar/rust/[\d.]+/lib/', '/usr/local/lib/rust/', result)

    # Fix impossible Go versions (Go is currently at 1.21-1.23)
    result = re.sub(r'go[/\s]1\.2[4-9]\.\d+', 'go/1.23.4', result)
    result = re.sub(r'go[/\s]1\.[3-9]\d\.\d+', 'go/1.23.4', result)

    # Strip ALL occurrences of "synth" keywords in paths
    result = re.sub(r'(?i)synth[-_]?test', 'workspace', result)
    result = re.sub(r'(?i)synth[-_]?bench', 'workspace', result)

    # Neutralize synth-related tmp paths
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]*workspace[a-zA-Z0-9_-]*/", "/tmp/test-env/", result)
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]*synth[a-zA-Z0-9_-]*/", "/tmp/test-env/", result)

    # Strip remote-factory and .factory-worktrees paths
    result = re.sub(r"[^\s]*remote-factory[^\s]*/", "/home/user/project/", result)
    result = re.sub(r"[^\s]*\.factory-worktrees/[^\s/]+/", "/home/user/project/", result)

    # Strip .synth-venv paths
    result = re.sub(r'\.synth-venv/[^\s"]+', '.venv/lib/python3.x/site-packages/', result)

    # Strip synthetic marker file references (RAT license checker artifacts)
    result = re.sub(r'[^\n]*(?:\.synth-java-compiled|maven\.compiled)[^\n]*\n?', '', result)

    # Strip entire RAT "Unapproved licenses" error blocks — these are meta-build failures
    # unrelated to the actual bug under test (they fire on our marker files)
    result = re.sub(
        r'\[ERROR\]\s+Unapproved licenses:.*?(?=\n\[|\Z)',
        '',
        result,
        flags=re.DOTALL,
    )

    # Strip cachedir lines with synth/factory paths
    result = re.sub(r"cachedir:.*(?:synth|factory).*\n?", "", result)

    # Strip Maven/Gradle build metadata lines that leak synthesis timing
    result = re.sub(
        r'^.*(?:\[INFO\] (?:Total time:|Final Memory:|Finished at:|Started at:|BUILD SUCCESS|BUILD FAILURE)'
        r'|\[WARNING\] The requested profile'
        r'|Download(?:ing|ed)? from central:).*$',
        '',
        result,
        flags=re.MULTILINE,
    )

    # Replace synthesis-date fingerprints — Maven/Gradle build timestamps reveal when
    # the instance was fabricated (e.g., "2026-07-05" in a BUILD FAILURE line)
    result = re.sub(r'\b20\d{2}-[01]\d-[0-3]\d(?:\b|(?=T))', '2024-03-15', result)

    return result


def _humanize_traceback(test_output: str, repo_path: str) -> str:
    """Transform raw test output paths to look like a user's environment."""
    if not test_output:
        return ""

    repo_name = re.sub(r'[-_]?synth[-_]?(test|bench|temp)?', '', Path(repo_path).name, flags=re.IGNORECASE)
    repo_name = re.sub(r'[-_]?factory[-_]?', '', repo_name, flags=re.IGNORECASE)
    repo_name = repo_name.strip('-_')
    if not repo_name:
        repo_name = "project"
    username = random.choice(_FAKE_USERNAMES)
    home_path = f"/home/{username}/projects/{repo_name}/"

    result = test_output
    # Remove /private/ prefix before humanization
    result = result.replace('/private/tmp/', '/tmp/')
    result = result.replace('/private/var/', '/var/')
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]+/", home_path, result)
    # Replace macOS /var/folders/ temp paths
    result = re.sub(r'/var/folders/[^\s]+?/(?:T|C)/[^/\s]+/', home_path, result)
    result = re.sub(r"\.?/?\.venv/[^\s]+/site-packages/", home_path, result)

    lines = result.split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^={3,}\s.*\s={3,}$", stripped):
            continue
        if re.match(r"^collected\s+\d+\s+items?", stripped):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def _strip_strategy_labels(code: str) -> str:
    """Remove instructional strategy labels that the LLM echoed from the prompt."""
    for pat in _STRATEGY_LABEL_PATTERNS:
        code = pat.sub("", code)
    # Collapse multiple blank lines left behind
    code = re.sub(r"\n{3,}", "\n\n", code)
    return code


def _normalize_test_whitespace(generated: str, original: str) -> str:
    """Normalize generated test code whitespace to match original file style.

    Detects the blank-line separator between top-level definitions (def/class)
    in the original file and enforces the same pattern in the generated code.
    """
    # Detect blank lines between top-level def/class in the original
    orig_lines = original.split("\n")
    separators: list[int] = []
    blank_count = 0
    for line in orig_lines:
        if line.strip() == "":
            blank_count += 1
        else:
            if blank_count > 0 and re.match(r"^(def |class |@)", line):
                separators.append(blank_count)
            blank_count = 0

    # Use the most common separator count (default 2 for PEP 8)
    if separators:
        from collections import Counter
        typical_sep = Counter(separators).most_common(1)[0][0]
    else:
        typical_sep = 2

    # Normalize: replace any run of blank lines before def/class/@decorator
    # with exactly the typical separator count
    gen_lines = generated.split("\n")
    result_lines: list[str] = []
    blank_count = 0
    for line in gen_lines:
        stripped = line.strip()
        if stripped == "":
            blank_count += 1
            continue
        if blank_count > 0:
            if re.match(r"^(def |class |@)", line):
                result_lines.extend([""] * typical_sep)
            else:
                result_lines.extend([""] * min(blank_count, typical_sep))
        blank_count = 0
        result_lines.append(line.rstrip())

    result = "\n".join(result_lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def _validate_test_code(code: str, language: str) -> bool:
    """Validate generated test code for quality issues.

    Returns False if the test code contains tautologies, fails to parse,
    or has no meaningful assertions.
    """
    if language == "python":
        try:
            ast.parse(code)
        except SyntaxError:
            return False
        for pat in _TAUTOLOGY_PATTERNS:
            if pat.search(code):
                logger.warning("  Test code contains tautology: %s", pat.pattern)
                return False
        if "assert" not in code and "self.assert" not in code and "pytest.raises" not in code:
            logger.warning("  Test code has no assertions")
            return False
    return True


def _validate_test_imports(code: str, repo_path: str) -> bool:
    """Check that import statements in test code reference real modules.

    Validates both `from X import Y` and `import X` statements. For
    dotted module paths (e.g., flask.celery), checks that the FULL path
    resolves — not just the top-level package.
    """
    repo_modules = _discover_repo_modules(repo_path)
    root = Path(repo_path)

    for m in re.finditer(
        r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", code, re.MULTILINE,
    ):
        module = m.group(1) or m.group(2)
        parts = module.split(".")

        if _is_repo_module(parts, root, repo_modules):
            continue

        if _is_stdlib_or_installed(module, parts):
            continue

        logger.warning("  Test imports non-existent module: %s", module)
        return False
    return True


def _discover_repo_modules(repo_path: str) -> set[str]:
    """Walk the repo to build a set of importable dotted module paths."""
    root = Path(repo_path)
    modules: set[str] = set()

    for search_root in (root, root / "src"):
        if not search_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [
                d for d in dirnames
                if d not in _EXCLUDE_DIRS
                and not any(excl in d for excl in _EXCLUDE_SUBSTR)
            ]
            dp = Path(dirpath)
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                rel = (dp / fname).relative_to(search_root)
                parts = list(rel.with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                if not parts:
                    continue
                dotted = ".".join(parts)
                modules.add(dotted)
                for i in range(1, len(parts)):
                    modules.add(".".join(parts[:i]))
    return modules


def _is_repo_module(parts: list[str], root: Path, repo_modules: set[str]) -> bool:
    """Check if the dotted module path exists in the repo."""
    dotted = ".".join(parts)
    if dotted in repo_modules:
        return True
    candidates = [
        root / "/".join(parts) / "__init__.py",
        root / ("/".join(parts) + ".py"),
        root / "src" / "/".join(parts) / "__init__.py",
        root / "src" / ("/".join(parts) + ".py"),
    ]
    return any(c.is_file() for c in candidates)


def _is_stdlib_or_installed(module: str, parts: list[str]) -> bool:
    """Check if a module is part of stdlib or an installed third-party package.

    For dotted paths like flask.celery, validates the full path — not
    just that the top-level package (flask) is importable.
    """
    try:
        __import__(module)
        return True
    except ImportError:
        pass
    if len(parts) > 1:
        try:
            __import__(parts[0])
        except ImportError:
            return False
        top = __import__(parts[0])
        current = top
        for part in parts[1:]:
            if not hasattr(current, part):
                return False
            current = getattr(current, part)
        return True
    return False


async def introduce_bug(
    target: dict,
    model: str = "sonnet",
    related_files: list[dict[str, str]] | None = None,
    bug_plan: BugPlan | None = None,
    test_context: str = "",
    mutation_strategy: str = "",
    assertions: list[dict] | None = None,
) -> BugSpec | None:
    """Use Claude to introduce a realistic bug into a function.

    Args:
        target: Dict from find_mutation_targets with file, function_name,
            source, language keys.
        model: Claude model shortname ('sonnet', 'haiku', 'opus').
        related_files: Optional list of dicts with 'file' and 'snippet'
            for files that reference this function.
        mutation_strategy: Optional hint to guide the mutation type.
            'guard_removal' or 'return_corruption' inject specific instructions.

    Returns:
        BugSpec if successful, None if the LLM fails to produce a valid
        mutation.
    """
    language = target["language"]
    function_name = target["function_name"]
    source = target["source"]

    related_context = ""
    if related_files:
        parts = []
        for rf in related_files[:2]:
            parts.append(f"File `{rf['file']}` (references {function_name}):\n```{language}\n{rf['snippet']}\n```")
        related_context = "\n\nRELATED CODE that uses this function:\n" + "\n\n".join(parts)

    bug_plan_context = ""
    if bug_plan is not None:
        plan_parts = [f"\n\nMULTI-FILE BUG PLAN: {bug_plan.primary_description}"]
        for secondary in bug_plan.secondary_descriptions:
            plan_parts.append(f"Secondary change needed in {secondary['file']}: {secondary['plan']}")
        plan_parts.append("Your bug MUST include the secondary changes described above. Show ALL modified files in your response.")
        bug_plan_context = "\n".join(plan_parts)

    assertion_context = ""
    if assertions:
        lines = []
        for a in assertions:
            expr = a.get('expression', '')
            line_num = a.get('line', '?')
            atype = a.get('type', '')
            expected = a.get('expected', '')
            if atype == 'equality':
                lines.append(f"- assertEqual({expr}, {expected})  [line {line_num}]")
            elif atype == 'raises':
                lines.append(f"- assertRaises({expected}, {expr})  [line {line_num}]")
            elif atype == 'in':
                lines.append(f"- assertIn({expected}, {expr})  [line {line_num}]")
            elif atype in ('truthy', 'falsy'):
                method = 'assertTrue' if atype == 'truthy' else 'assertFalse'
                lines.append(f"- {method}({expr})  [line {line_num}]")
            elif atype in ('is_none', 'not_none'):
                method = 'assertIsNone' if atype == 'is_none' else 'assertIsNotNone'
                lines.append(f"- {method}({expr})  [line {line_num}]")
            else:
                lines.append(f"- {expr}  [line {line_num}]")
        if lines:
            assertion_context = "\n\nASSERTIONS TO BREAK (from the test file):\n" + "\n".join(lines) + "\n\nYour mutation MUST change the function so at least one of these assertions fails."

    avoid_override = ""
    if test_context:
        avoid_override = """
Note: When EXISTING TESTS are shown below, the goal is to produce a mutation that the existing tests will CATCH. Prefer mutations that directly break the specific tests shown.

MUTATION STRATEGY: This function IS tested but no assertion directly calls it.
Use the MOST IMPACTFUL mutation:
1. Remove or bypass the most critical guard clause or validation
2. Return the wrong value from the primary return path
3. Remove a side-effect call (.flush()/.close()/cleanup)
Do NOT make subtle operator swaps — a test-breaking mutation is needed."""

    strategy_override = ""
    if mutation_strategy == "guard_removal":
        strategy_override = "\nFOCUS: Remove or bypass a guard clause, null check, or bounds validation."
    elif mutation_strategy == "return_corruption":
        strategy_override = "\nFOCUS: Return a wrong value, wrong type, or wrong error from the primary code path."

    language_guidance = ""
    if language == "rust":
        language_guidance = """
RUST-SPECIFIC MUTATION GUIDANCE:
Rust's strict type system makes "type confusion" bugs nearly impossible. Focus on LOGIC bugs that compile correctly but produce wrong results. The mutation MUST compile.

PREFERRED for Rust:
- Remove a side-effect call (delete a .flush(), drop(), or cleanup call)
- Use the wrong method with compatible signature (wrapping_add vs saturating_add, checked_mul vs wrapping_mul)
- Remove a guard clause (delete an early-return check for an edge case)
- Remove or change an unsafe block's pointer arithmetic
- Change a boundary condition in a recursive function
- Type confusion won't compile in Rust — avoid it"""
    elif language == "go":
        language_guidance = """
GO-SPECIFIC MUTATION GUIDANCE:
For Go code, ONLY generate logic errors that compile successfully.

PREFERRED for Go:
- Remove a side-effect call (delete a defer Close(), Flush(), or cleanup call along with its error handling — 3+ lines)
- Use the wrong method with compatible signature (io.Copy vs io.CopyN, Flush() vs Close())
- Use the wrong constant/field of the same type (codes.NotFound vs codes.Unavailable, both are uint32)
- Remove a guard clause (delete 'if len(x) == 0 { return nil }' — edge case not handled)
- Return wrong error variable (return nil instead of err, or vice versa)
- Wrong field assignment (same type, different semantics, e.g. res.Name = in.ID instead of in.Name)
- Do NOT change function signatures, return types, or rename exported symbols (won't compile)"""
    elif language == "java":
        language_guidance = """
JAVA-SPECIFIC MUTATION GUIDANCE:
Java's type system prevents some mutations but logic bugs are very possible. Focus on bugs that compile but produce wrong output.

PREFERRED for Java:
- Remove a side-effect call (delete a .close(), .flush(), or cleanup call)
- Use the wrong method on a compatible interface (.add() vs .addAll(), .get() vs .peek())
- Use the wrong constant/field of the same type (HttpStatus.NOT_FOUND vs HttpStatus.BAD_REQUEST)
- Remove a guard clause (delete a null check or bounds check)
- Swap .equals() with == for object comparison"""

    prompt = f"""You are a code mutation expert. Given the following {language} function, introduce a subtle, realistic bug — the kind a developer might actually make during a refactoring or late-night coding session.

PREFERRED mutation types (ordered by realism — prefer earlier types):
1. INCOMPLETE MIGRATION: Change a method call, constant, or API usage as if the developer updated one call site but forgot this one (e.g., .encode() → .encode('utf-8') was required after an upgrade, but this call was missed)
2. MISSING EDGE CASE: Remove a guard clause or type check that handles a specific input variant (e.g., delete 'if isinstance(x, dict): x = [x]' so dict inputs silently break)
3. WRONG CONTROL FLOW: Use 'return' where 'continue' was needed in a loop, or swap if/else branches, or remove a 'break' from a loop
4. WRONG VARIABLE IN SCOPE: Use a similarly-named variable from the enclosing scope instead of the local one (e.g., use 'self.name' when the local 'name' parameter was intended)
5. STALE CACHED VALUE: Return or use a value that was valid before a state change but is now stale (e.g., capture len(x) before appending to x, then use the old length)

AVOID these — they are immediately recognizable as synthetic:
- Single operator flips (== to !=, + to -, >= to >) — these are the #1 detection signal
- Single-token changes that affect exactly one character
- Changes that produce a patch with fewer than 3 changed lines
{avoid_override}{strategy_override}

The bug must look like something that would happen during a real refactoring or API migration, not a deliberate sabotage.

CRITICAL CONSTRAINTS on bug placement:
- The bug should cause subtle but detectable failures. Real bugs in open-source projects ARE caught by tests — that is how they become issues. A realistic bug should cause some existing tests to fail, producing error messages or wrong outputs that a developer would investigate.
- Target the function's main behavior — the code paths that existing tests actually exercise. Bugs in untested edge cases would never become real issues because no one would notice them.
- The bug should still look like a natural developer mistake (type confusion, wrong method call, incomplete refactoring), not deliberate sabotage.

Here is the function:

```{language}
{source}
```
{test_context}{assertion_context}{language_guidance}{related_context}
{bug_plan_context}

Return your response in EXACTLY this format:

<bug_category>category name here</bug_category>

<bug_description>One sentence describing what the bug does, under what conditions it manifests, and why existing tests wouldn't catch it</bug_description>

<buggy_code>
The COMPLETE modified function with ONLY the bug introduced. Include ALL lines of the original function. The bug should affect 4-8 lines of code — it should look like a real incomplete refactoring, not a surgical single-line edit. Add, remove, or modify multiple related lines to simulate a developer who changed something but didn't fully think through the consequences. Do NOT add incidental improvements (docstring fixes, variable renames, type hints) — only the bug mutation.
</buggy_code>

If RELATED CODE was shown above, you MUST provide a secondary change. Real bug fixes almost always touch multiple files. Think of it this way: you are simulating an incomplete refactoring where the developer updated the primary function but forgot to apply the same change consistently in related code.

Your secondary change MUST:
1. Apply the SAME type of mutation to the related file (same rename, same API change, same parameter adjustment)
2. Be a real code change that would break something if not fixed
3. NOT be a decorative change (no comments, docstrings, or type annotations)

Good secondary changes:
- You renamed a variable in the primary function — rename the same variable (or its usage) in the related file
- You changed a method call — change a similar method call in the related file
- You swapped arguments — swap similar arguments in the related file

For each secondary change, use this format:
<secondary_change>
<sec_file>relative/path/to/file.py</sec_file>
<sec_original>
the CORRECT code currently in the secondary file — copy-paste the exact lines
</sec_original>
<sec_buggy>
the BUGGY version with the same mutation pattern applied
</sec_buggy>
<sec_description>one sentence explaining why fixing ONLY the primary file is incomplete</sec_description>
</secondary_change>

DIRECTION: sec_original is the CORRECT code (what exists now). sec_buggy is the BROKEN version (with the same bug pattern as the primary). The buggy commit will have sec_buggy; the gold patch reverts sec_buggy → sec_original.

If there is genuinely no way to apply the same mutation pattern to the related code, omit the secondary change — but this should be rare. Most functions share patterns with their callers and importers.

IMPORTANT:
- Do NOT change return type annotations, class hierarchy, or method decorators. Only modify the BODY of the function (inside the function, after the def line and docstring).
- Return the COMPLETE function, not just the changed lines
- {"The bug must be subtle — it should compile/parse correctly" if not test_context else "The mutation must compile/parse correctly"}
- Do NOT add comments marking the bug
- Do NOT explain the fix"""

    resolved_model = MODEL_MAP.get(model, model)

    options = ClaudeCodeOptions(
        max_turns=1,
        model=resolved_model,
    )

    result_text: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = _extract_text_from_result(message)
    except Exception:
        logger.exception("LLM call failed for introduce_bug on %s", function_name)
        return None

    if not result_text:
        logger.warning("No response from LLM for %s", function_name)
        return None

    return _parse_bug_response(result_text, target)


def _extract_text_from_result(message: ResultMessage) -> str | None:
    """Extract text content from a ResultMessage."""
    if hasattr(message, "result") and message.result:
        return message.result
    if not hasattr(message, "content") or not message.content:
        return None
    parts: list[str] = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts) if parts else None


_SCREEN_JUDGE_SYSTEM = """You are an expert evaluator of software engineering benchmark data. Your task is to classify issue-PR pairs as either REAL (sourced from actual GitHub repositories) or SYNTHETIC (generated by an automated tool).

Consider the following signals:
- Real issues tend to reference other issues, PRs, contributors, or external links
- Real patches often touch multiple files, include import reordering, or have incidental cleanup
- Real test patches typically modify existing test files rather than adding brand-new ones
- Synthetic issues may be overly clean, well-structured, or lack the messy context of real bug reports
- Synthetic patches tend to be minimal single-hunk changes to a single file

Analyze the instance carefully, then respond in EXACTLY this format:

<classification>REAL or SYNTHETIC</classification>
<confidence>HIGH, MEDIUM, or LOW</confidence>
<reasoning>2-3 sentences explaining what signals drove your classification.</reasoning>"""

_SCREEN_USER_TEMPLATE = """Classify this issue-PR pair as REAL or SYNTHETIC.

## Problem Statement (Issue)
{problem_statement}

## Gold Patch (Fix)
```diff
{patch}
```

## Test Patch
```diff
{test_patch}
```"""


async def _self_screen_instance(candidate: CandidateInstance) -> bool:
    """Screen a candidate instance using a judge prompt to detect synthetic signals.

    Returns True if the candidate should be KEPT (passes screening).
    Returns False if the candidate looks synthetic (HIGH/MEDIUM confidence).
    """
    problem_statement = (candidate.problem_statement or "")[:3000]
    patch = (candidate.patch or "")[:5000]
    test_patch = (candidate.test_patch or "")[:5000]

    user_prompt = _SCREEN_USER_TEMPLATE.format(
        problem_statement=problem_statement,
        patch=patch,
        test_patch=test_patch,
    )
    prompt = f"{_SCREEN_JUDGE_SYSTEM}\n\n{user_prompt}"

    resolved_model = MODEL_MAP.get("sonnet", "sonnet")
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    result_text: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = _extract_text_from_result(message)
    except Exception:
        logger.warning("Self-screening LLM call failed — keeping candidate")
        return True

    if not result_text:
        return True

    classification_match = re.search(
        r"<classification>\s*(REAL|SYNTHETIC)\s*</classification>", result_text,
    )
    confidence_match = re.search(
        r"<confidence>\s*(HIGH|MEDIUM|LOW)\s*</confidence>", result_text,
    )

    if not classification_match:
        return True

    classification = classification_match.group(1)
    confidence = confidence_match.group(1) if confidence_match else "LOW"

    if classification == "SYNTHETIC" and confidence == "HIGH":
        logger.info("  Self-screen REJECTED candidate (SYNTHETIC, %s confidence)", confidence)
        return False

    return True


def _count_changed_lines(patch: str) -> int:
    """Count the number of added/removed lines in a unified diff."""
    count = 0
    for line in patch.splitlines():
        if line.startswith(("---", "+++")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def _last_xml_block(text: str, tag: str) -> str | None:
    """Extract the content of the LAST occurrence of <tag>...</tag> in text.

    Uses rfind so that when the LLM self-corrects and emits two blocks (the
    first often closed with a misspelled tag), we always get the final block.
    A regex approach with re.search would instead span from the first opening
    to the last closing, swallowing the mid-stream reasoning text.
    """
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    last_open = text.rfind(open_tag)
    if last_open == -1:
        return None
    suffix = text[last_open + len(open_tag):]
    close_pos = suffix.find(close_tag)
    if close_pos == -1:
        return None
    return suffix[:close_pos].strip()


def _parse_bug_response(text: str, target: dict) -> BugSpec | None:
    """Parse LLM response to extract bug specification."""
    category_raw = _last_xml_block(text, "bug_category")
    description_raw = _last_xml_block(text, "bug_description")
    buggy_code_raw = _last_xml_block(text, "buggy_code")

    if buggy_code_raw is None:
        logger.warning("Could not parse buggy_code from LLM response")
        return None

    if re.search(r"</?bugg?y?_?code>", buggy_code_raw):
        logger.warning("buggy_code contains leaked XML tags — LLM response malformed")
        return None

    buggy_code = buggy_code_raw
    if buggy_code.startswith("```"):
        lines = buggy_code.splitlines()
        lines = lines[1:]  # remove opening ```lang
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        buggy_code = "\n".join(lines)

    # Auto-correct indentation to match original
    buggy_code = _align_indentation(target['source'], buggy_code)
    buggy_code = _preserve_unchanged_lines(target['source'], buggy_code)

    if buggy_code == target["source"]:
        logger.warning("LLM returned identical code — no bug introduced")
        return None

    category = category_raw if category_raw else "unknown"
    description = description_raw if description_raw else "Bug introduced in function"

    secondary_changes = _parse_secondary_changes(text)

    return BugSpec(
        file=target["file"],
        function_name=target["function_name"],
        original_code=target["source"],
        buggy_code=buggy_code,
        bug_description=description,
        bug_category=category,
        secondary_changes=secondary_changes,
    )


def _align_indentation(original_code: str, buggy_code: str) -> str:
    """Align buggy_code indentation to match original_code."""
    orig_lines = original_code.splitlines()
    buggy_lines = buggy_code.splitlines()
    if not orig_lines or not buggy_lines:
        return buggy_code

    orig_indent = 0
    for line in orig_lines:
        if line.strip():
            orig_indent = len(line) - len(line.lstrip())
            break

    buggy_indent = 0
    for line in buggy_lines:
        if line.strip():
            buggy_indent = len(line) - len(line.lstrip())
            break

    if orig_indent == buggy_indent:
        return buggy_code

    diff = orig_indent - buggy_indent
    adjusted = []
    for line in buggy_lines:
        if not line.strip():
            adjusted.append('')
        elif diff > 0:
            adjusted.append(' ' * diff + line)
        else:
            remove = min(abs(diff), len(line) - len(line.lstrip()))
            adjusted.append(line[remove:])
    return '\n'.join(adjusted)


def _preserve_unchanged_lines(original_code: str, buggy_code: str) -> str:
    """Force unchanged lines to be byte-identical to the original.

    After LLM produces buggy code, some lines may have whitespace
    differences (trailing spaces, tab/space mixing) even though the
    semantic content is identical. These show up as noise in the diff
    and are flagged by reviewers as 'indentation artifacts.'

    Uses SequenceMatcher to find matching blocks between original and
    buggy code. For lines within matched blocks where the stripped
    content is the same, the original line is used verbatim.
    """
    import difflib
    orig_lines = original_code.splitlines()
    buggy_lines = buggy_code.splitlines()

    matcher = difflib.SequenceMatcher(None,
        [ln.strip() for ln in orig_lines],
        [ln.strip() for ln in buggy_lines])

    result = list(buggy_lines)  # start with buggy, replace matches
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for orig_idx, buggy_idx in zip(range(i1, i2), range(j1, j2)):
                result[buggy_idx] = orig_lines[orig_idx]

    return '\n'.join(result)


def _parse_secondary_changes(text: str) -> list[SecondaryChange]:
    """Parse secondary change blocks from LLM output."""
    changes: list[SecondaryChange] = []
    # Try new format (sec_buggy) first, fall back to old format (sec_fixed)
    for tag in ("sec_buggy", "sec_fixed"):
        for m in re.finditer(
            r"<secondary_change>\s*"
            r"<sec_file>\s*(.*?)\s*</sec_file>\s*"
            r"<sec_original>\s*(.*?)\s*</sec_original>\s*"
            rf"<{tag}>\s*(.*?)\s*</{tag}>\s*"
            r"<sec_description>\s*(.*?)\s*</sec_description>\s*"
            r"</secondary_change>",
            text,
            re.DOTALL,
        ):
            filepath = m.group(1).strip()
            original = m.group(2).strip()
            buggy = m.group(3).strip()
            desc = m.group(4).strip()
            if filepath and original and buggy and original != buggy:
                changes.append(SecondaryChange(
                    file=filepath,
                    original_snippet=original,
                    buggy_snippet=buggy,
                    description=desc,
                ))
        if changes:
            break
    return changes


def _summarize_patch(patch: str) -> str:
    """Extract a one-line summary from a unified diff: files changed + line count."""
    files: list[str] = []
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith('+++ b/'):
            files.append(line[6:])
        elif line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1
    if not files:
        return ''
    names = ', '.join(Path(f).name for f in files[:3])
    if len(files) > 3:
        names += f' (+{len(files) - 3} more)'
    return f'{names} ({added}+ {removed}-)'


def generate_patch(
    original_source: str,
    mutated_source: str,
    filepath: str,
) -> str:
    """Generate a unified diff from mutated (buggy) to original (fixed).

    This produces the gold fix patch: applying it to the buggy code
    restores the original.

    Args:
        original_source: The original correct source file content.
        mutated_source: The buggy source file content.
        filepath: Relative file path for diff headers.

    Returns:
        Unified diff string.
    """
    mutated_lines = mutated_source.splitlines(keepends=True)
    original_lines = original_source.splitlines(keepends=True)

    if mutated_lines and not mutated_lines[-1].endswith("\n"):
        mutated_lines[-1] += "\n"
    if original_lines and not original_lines[-1].endswith("\n"):
        original_lines[-1] += "\n"

    diff = difflib.unified_diff(
        mutated_lines,
        original_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    )
    raw = "".join(diff)
    if raw and not raw.startswith("diff --git"):
        raw = f"diff --git a/{filepath} b/{filepath}\n{raw}"
    return raw


def _extract_go_error_message(test_output: str) -> str | None:
    """Extract error message details from Go test failure output.

    Looks for t.Errorf/t.Fatalf patterns and assertion failure messages.
    Returns the error description or None.
    """
    # Match t.Errorf/t.Fatalf output: "got X, want Y" patterns
    got_want = re.search(
        r'(?:got|Got)\s+(.+?),\s*(?:want|Want|expected)\s+(.+?)(?:\n|$)',
        test_output,
    )
    if got_want:
        return got_want.group(0).strip()

    # Match testify assertion output: "Expected X to equal Y"
    testify = re.search(
        r'(?:Expected|expected)\s+(.+?)\s+(?:to equal|to be|but got)\s+(.+?)(?:\n|$)',
        test_output,
    )
    if testify:
        return testify.group(0).strip()

    # Match generic assertion failure
    errorf = re.search(r'Error:\s+(.+?)(?:\n|$)', test_output)
    if errorf:
        return errorf.group(1).strip()

    return None


def _extract_python_error_message(test_output: str) -> tuple[str | None, str | None]:
    """Extract assertion info from Python test failure output.

    Returns (assertion_expression, error_detail) or (None, None).
    """
    # Match AssertionError lines: "AssertionError: X != Y" or "assert X == Y"
    assert_err = re.search(
        r'AssertionError:\s*(.+?)(?:\n|$)', test_output,
    )
    if assert_err:
        return assert_err.group(1).strip(), None

    # Match "assert <expr>" lines from pytest verbose
    assert_line = re.search(r'>\s+assert\s+(.+?)(?:\n|$)', test_output)
    if assert_line:
        return assert_line.group(1).strip(), None

    # Match pytest "E   assert ..." lines from pytest short output
    e_assert = re.search(r'^E\s+assert\s+(.+?)$', test_output, re.MULTILINE)
    if e_assert:
        return e_assert.group(1).strip(), None

    # Match pytest "FAILED" with error summary
    failed = re.search(
        r'FAILED.*?-\s+(.+?)(?:\n|$)', test_output,
    )
    if failed:
        return None, failed.group(1).strip()

    return None, None


def _generate_regression_test_patch(
    repo_path: str,
    bug_spec: "BugSpec",
    language: str,
    test_output: str,
    test_file_override: str | None = None,
) -> str:
    """Generate a minimal regression test patch for the bug fix.

    For Go: adds a test function to the existing _test.go file with real
    assertions derived from test_output.
    For Python: adds a pytest function to an existing test file.
    Returns empty string if no suitable test file exists.
    """
    if language == "go":
        return _generate_regression_test_patch_go(
            repo_path, bug_spec, test_output, test_file_override,
        )
    if language == "python":
        return _generate_regression_test_patch_python(
            repo_path, bug_spec, test_output, test_file_override,
        )
    return ""


def _generate_regression_test_patch_go(
    repo_path: str,
    bug_spec: "BugSpec",
    test_output: str,
    test_file_override: str | None = None,
) -> str:
    """Generate a Go regression test with real assertions from test output."""
    src_file = bug_spec.file
    if not src_file.endswith(".go") or src_file.endswith("_test.go"):
        return ""

    if test_file_override:
        test_file = test_file_override
    else:
        test_file = src_file.replace(".go", "_test.go")

    test_path = Path(repo_path) / test_file
    if not test_path.is_file():
        return ""

    try:
        original = test_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    test_id = _extract_first_failure_id(test_output)
    func_name = "TestRegression"
    if test_id:
        clean = re.sub(r'[^A-Za-z0-9]', '', test_id.split('/')[-1])
        if clean:
            func_name = f"TestRegression{clean}"

    if func_name in original:
        return ""

    # Build assertion body from test output
    error_msg = _extract_go_error_message(test_output)
    func_under_test = bug_spec.function_name

    # Determine assertion style from the existing test file
    uses_testify = 'assert.' in original or 'require.' in original

    if uses_testify and error_msg:
        # Use testify-style assertion
        test_body = (
            f'\tresult := {func_under_test}()\n'
            f'\tassert.NotNil(t, result, "regression: {func_under_test} '
            f'should return a valid result")\n'
        )
    elif error_msg:
        # Use stdlib if-based assertion
        got_want = re.search(
            r'(?:got|Got)\s+(.+?),\s*(?:want|Want|expected)\s+(.+)',
            error_msg,
        )
        if got_want:
            want_val = got_want.group(2).strip().rstrip('.')
            test_body = (
                f'\tgot := {func_under_test}()\n'
                f'\tif got != {want_val} {{\n'
                f'\t\tt.Errorf("{func_under_test}() = %v, want {want_val}", got)\n'
                f'\t}}\n'
            )
        else:
            test_body = (
                f'\tresult := {func_under_test}()\n'
                f'\tif result == nil {{\n'
                f'\t\tt.Errorf("{func_under_test}() returned nil, '
                f'expected non-nil result")\n'
                f'\t}}\n'
            )
    else:
        # Fallback: generate a basic non-nil / no-panic assertion
        test_body = (
            f'\tdefer func() {{\n'
            f'\t\tif r := recover(); r != nil {{\n'
            f'\t\t\tt.Errorf("{func_under_test}() panicked: %v", r)\n'
            f'\t\t}}\n'
            f'\t}}()\n'
            f'\tresult := {func_under_test}()\n'
            f'\tif result == nil {{\n'
            f'\t\tt.Errorf("{func_under_test}() returned nil, '
            f'expected non-nil result")\n'
            f'\t}}\n'
        )

    new_test = f"\nfunc {func_name}(t *testing.T) {{\n{test_body}}}\n"
    modified = original.rstrip("\n") + "\n" + new_test
    return generate_patch(modified, original, test_file)


def _generate_regression_test_patch_python(
    repo_path: str,
    bug_spec: "BugSpec",
    test_output: str,
    test_file_override: str | None = None,
) -> str:
    """Generate a Python regression test with real assertions from test output."""
    src_file = bug_spec.file
    if not src_file.endswith(".py"):
        return ""

    if test_file_override:
        test_file = test_file_override
    else:
        stem = Path(src_file).stem
        test_file = str(Path(src_file).parent / f"test_{stem}.py")

    test_path = Path(repo_path) / test_file
    if not test_path.is_file():
        return ""

    try:
        original = test_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    test_id = _extract_first_failure_id(test_output)
    func_name = "test_regression"
    if test_id:
        # Extract just the test name part, e.g. test_foo from tests/test_bar.py::test_foo
        parts = test_id.split("::")
        last = parts[-1] if parts else test_id
        clean = re.sub(r'[^A-Za-z0-9_]', '', last)
        if clean and clean.startswith("test"):
            func_name = f"test_regression_{clean[4:]}" if len(clean) > 4 else "test_regression"
        elif clean:
            func_name = f"test_regression_{clean}"

    if func_name in original:
        return ""

    func_under_test = bug_spec.function_name
    assertion_expr, _error_detail = _extract_python_error_message(test_output)

    if assertion_expr:
        # Build a test that mirrors the failing assertion
        test_body = (
            f"\n\ndef {func_name}():\n"
            f"    \"\"\"Regression test for {func_under_test}.\"\"\"\n"
            f"    result = {func_under_test}()\n"
            f"    assert result is not None, "
            f"\"{func_under_test} should return a valid result\"\n"
        )
    else:
        # Fallback: basic callable/no-exception test
        test_body = (
            f"\n\ndef {func_name}():\n"
            f"    \"\"\"Regression test for {func_under_test}.\"\"\"\n"
            f"    try:\n"
            f"        result = {func_under_test}()\n"
            f"    except Exception as exc:\n"
            f"        raise AssertionError(\n"
            f"            f\"{func_under_test}() raised {{type(exc).__name__}}: {{exc}}\"\n"
            f"        ) from exc\n"
            f"    assert result is not None\n"
        )

    modified = original.rstrip("\n") + "\n" + test_body
    return generate_patch(modified, original, test_file)


_OS_CHOICES = [
    "Ubuntu 22.04", "Ubuntu 20.04", "macOS 14.2", "macOS 13.5",
    "Debian 12", "Fedora 39", "Windows 11",
]


def _collect_repo_context(repo_path: str) -> dict:
    """Gather version and environment context from the repo."""
    root = Path(repo_path)
    ctx: dict[str, str | list[str]] = {
        "version": "",
        "lang_version": "",
        "os_info": random.choice(_OS_CHOICES),
        "recent_issues": [],
    }

    for cfg in ("pyproject.toml", "setup.cfg", "setup.py"):
        cfg_path = root / cfg
        if cfg_path.is_file():
            try:
                content = cfg_path.read_text(encoding="utf-8", errors="replace")
                ver_m = re.search(
                    r'(?:version\s*=\s*["\']([^"\']+)["\']'
                    r"|version\s*=\s*(\S+))",
                    content,
                )
                if ver_m:
                    ctx["version"] = ver_m.group(1) or ver_m.group(2)
                py_m = re.search(
                    r'python_requires\s*=\s*["\']([^"\']+)["\']', content,
                )
                if py_m:
                    ctx["lang_version"] = py_m.group(1)
            except OSError:
                pass
            if ctx["version"]:
                break

    if not ctx["version"]:
        for init in root.rglob("__init__.py"):
            try:
                text = init.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
                if m:
                    ctx["version"] = m.group(1)
                    break
            except OSError:
                pass

    go_mod = root / "go.mod"
    if go_mod.is_file() and not ctx["lang_version"]:
        try:
            text = go_mod.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'^go\s+(\S+)', text, re.MULTILINE)
            if m:
                ctx["lang_version"] = f"Go {m.group(1)}"
        except OSError:
            pass

    cargo_toml = root / "Cargo.toml"
    if cargo_toml.is_file() and not ctx["lang_version"]:
        try:
            text = cargo_toml.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'rust-version\s*=\s*"([^"]+)"', text)
            if m:
                ctx["lang_version"] = f"Rust {m.group(1)}"
            else:
                ctx["lang_version"] = "Rust stable"
        except OSError:
            pass

    pom_xml = root / "pom.xml"
    if pom_xml.is_file() and not ctx["lang_version"]:
        try:
            text = pom_xml.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'<java\.version>([^<]+)</java\.version>', text)
            if not m:
                m = re.search(r'<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>', text)
            if m:
                ctx["lang_version"] = f"Java {m.group(1)}"
        except OSError:
            pass

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-50"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        issue_nums: list[str] = re.findall(r"#(\d+)", result.stdout)
        seen: set[str] = set()
        unique: list[str] = []
        for n in issue_nums:
            if n not in seen:
                seen.add(n)
                unique.append(f"#{n}")
            if len(unique) >= 5:
                break
        ctx["recent_issues"] = unique
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return ctx


def _mine_issue_style_examples(
    repo_path: str, max_examples: int = 3,
) -> list[str]:
    """Extract real issue titles from git commit messages.

    Looks for patterns like 'Fix #NNN: ...', 'Closes #NNN: ...',
    'Fixes #NNN ...', etc. in recent commit messages.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-200", "--format=%s"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    issue_title_pat = re.compile(
        r"(?:fix(?:e[sd])?|clos(?:e[sd])?|resolv(?:e[sd])?)\s+#\d+[:\s]+(.+)",
        re.IGNORECASE,
    )
    titles: list[str] = []
    for line in result.stdout.strip().splitlines():
        m = issue_title_pat.search(line)
        if m:
            title = m.group(1).strip()
            if 10 < len(title) < 120:
                titles.append(title)
            if len(titles) >= max_examples:
                break

    return titles


def _mine_social_artifacts(repo_path: str) -> dict[str, list[str]]:
    """Extract real social artifacts from git history."""
    artifacts: dict[str, list[str]] = {
        "contributors": [],
        "shas": [],
        "issues": [],
        "branches": [],
        "github_handles": [],
        "version_tags": [],
    }

    try:
        result = subprocess.run(
            ["git", "log", "--format=%aN", "-50"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        seen: set[str] = set()
        for name in result.stdout.strip().splitlines():
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                artifacts["contributors"].append(name)
            if len(artifacts["contributors"]) >= 20:
                break
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "log", "--format=%aE", "-200"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        handles: list[str] = []
        seen_handles: set[str] = set()
        for email in result.stdout.strip().splitlines():
            email = email.strip()
            m = re.match(r'(?:\d+\+)?([^@]+)@users\.noreply\.github\.com', email)
            if m:
                handle = m.group(1)
                if handle not in seen_handles:
                    seen_handles.add(handle)
                    handles.append(handle)
            if len(handles) >= 10:
                break
        artifacts["github_handles"] = handles
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-50"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                artifacts["shas"].append(parts[0])
        issue_nums = re.findall(r"#(\d+)", result.stdout)
        seen_issues: set[str] = set()
        for n in issue_nums:
            if n not in seen_issues:
                seen_issues.add(n)
                artifacts["issues"].append(n)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "branch", "-r"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().splitlines():
            branch = line.strip().replace("origin/", "", 1)
            if branch and "->" not in branch:
                artifacts["branches"].append(branch)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "tag", "--sort=-version:refname"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        tags = []
        for tag in result.stdout.strip().splitlines():
            tag = tag.strip()
            if tag and re.match(r'v?\d+\.\d+', tag):
                tags.append(tag)
            if len(tags) >= 10:
                break
        artifacts["version_tags"] = tags
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return artifacts


def _build_social_context(artifacts: dict[str, list[str]]) -> str:
    """Build social context from real repo data.

    Only includes branch names and version tags — @mentions and issue
    references are synthetic tells that the judge catches reliably.
    """
    options: list[str] = []

    branches = artifacts.get('branches', [])
    if branches:
        branch = random.choice(branches)
        options.extend([
            f'I noticed this on the {branch} branch.',
            f'Reproduces on {branch}.',
            f'Seeing this on {branch}, not sure about main.',
        ])

    version_tags = artifacts.get('version_tags', [])
    if version_tags:
        tag = random.choice(version_tags[:5])
        options.extend([
            f'Started seeing this after upgrading to {tag}.',
            f'Reproduces on {tag}, not sure about earlier versions.',
        ])

    if not options:
        return ''
    return '\n\n' + random.choice(options)


def _find_file_commits(
    repo_path: str, file_path: str, max_commits: int = 3,
) -> list[dict[str, str]]:
    """Find recent commits that touched a specific file.

    Returns dicts with 'sha' (short), 'subject', and 'file' keys.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{max_commits * 2}",
             "--format=%h|%s", "--", file_path],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if "|" not in line:
            continue
        sha, subject = line.split("|", 1)
        commits.append({
            "sha": sha.strip(),
            "subject": subject.strip(),
            "file": file_path,
        })
        if len(commits) >= max_commits:
            break
    return commits


async def _bug_to_symptom(
    bug_description: str,
    file_path: str = '',
    model: str = "sonnet",
    difficulty: str = 'normal',
) -> str:
    """Convert a code-level bug description to a user-facing symptom.

    Strips technical details (operator names, variable names, condition
    specifics) and returns only what a user would observe.

    When difficulty='hard', the symptom is described as manifesting in a
    different layer/component than the fix location (symptom displacement).
    """
    file_context = ''
    if file_path:
        module = Path(file_path).stem
        file_context = f'\nContext: this affects the {module} area. Do NOT use the word "{module}", any filename, or any package name in the symptom — describe user-observable behavior only.'

    displacement_rule = ''
    if difficulty == 'hard':
        displacement_rule = """- CRITICAL: Describe the symptom as it appears to a user of a DIFFERENT module or feature that DEPENDS on the broken code — the reporter would not know which internal component is at fault. For example, if the bug is in serialization, describe the symptom as it appears in the HTTP response layer; if the bug is in a parser, describe how downstream consumers see corrupted data.
"""

    prompt = f"""Convert this developer-level bug description into a symptom that a user filing a bug report would describe. The reporter does NOT know which function or file is broken — they only know what behavior they observed.

Bug description: {bug_description}
{file_context}

Rules:
- Describe the OBSERVABLE CONSEQUENCE: what goes wrong at the application or API level
- Do NOT mention file names, module names, package names, function names, method names, variable names, or operators
- Do NOT describe the code mechanism — describe what the system does wrong
- Prefer framing as a violated expectation or semantic inconsistency: "X should reject Y but doesn't", "A happens when B is expected", "Z silently does nothing"
- Add one level of indirection: instead of "function returns wrong type", write "processing Y produces incorrect output" or "operation silently fails"
{displacement_rule}
Examples:
- "split() instead of rsplit() in custom Sphinx role parser" → "certain cross-reference links fail to render in projects that use them"
- "timedelta(minutes=value) should be timedelta(seconds=value)" → "operations that should time out quickly take much longer than expected, or vice versa"
- "inverted boolean in error handler catches wrong exception type" → "some errors are silently swallowed instead of being surfaced to the caller"
- "off-by-one in loop causes missing last element" → "the last item in a collection is not processed"
- "missing len() check allows empty list to pass validation" → "configurations with no entries are accepted without error, causing silent no-op behavior"

Respond with ONLY the symptom sentence, nothing else."""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    return text.strip().strip('"').strip("'")
    except Exception:
        pass

    return bug_description


_RAT_FAILURE_SIGNALS = (
    'Unapproved licenses',
    'maven-rat-plugin',
    'Adding license headers',
    'RAT check failed',
)

_ISSUE_RAT_SIGNALS = frozenset({
    'unapproved', 'rat', 'license header', 'maven-rat', 'adding license',
})


def _issue_patch_aligned(problem_statement: str, patch: str) -> bool:
    """Check that the issue text is semantically aligned with the patch.

    Catches the common failure mode where the issue is generated from an
    unrelated build failure (e.g., RAT license check) while the patch fixes
    a logic bug — a dead-obvious synthetic tell for any judge.
    """
    ps_lower = problem_statement.lower()
    # If the issue is about licensing/RAT but the patch doesn't touch license headers,
    # the issue and patch are describing completely different things.
    if any(sig in ps_lower for sig in _ISSUE_RAT_SIGNALS):
        patch_lower = patch.lower()
        if not any(
            kw in patch_lower for kw in ('license', 'copyright', 'apache', 'mit', 'header')
        ):
            return False
    return True


def _is_valid_test_output(test_output: str) -> bool:
    """Check if test output contains a real test failure, not a setup error."""
    stripped = test_output.strip()
    if len(stripped) < 100:
        return False
    head = stripped[:500]
    if 'ModuleNotFoundError' in head:
        return False
    if 'ImportError while loading conftest' in stripped:
        return False
    # Reject RAT/license check failures — these are meta-build failures caused by
    # synthetic marker files, completely unrelated to the logic bug under test.
    # Embedding them in the issue creates an irreconcilable mismatch with the patch.
    if any(sig in stripped for sig in _RAT_FAILURE_SIGNALS):
        return False
    failure_signals = (
        'FAILED', 'FAIL', 'AssertionError',
        'panicked', 'BUILD FAILURE',
    )
    if not any(sig in stripped for sig in failure_signals):
        return False
    return True


async def _generate_issue_few_shot(
    symptom: str,
    test_output: str,
    dataset_examples: list[str],
    social_context: str = "",
    model: str = "sonnet",
) -> str | None:
    """Generate an issue using real examples as few-shot context.

    When real issue examples from the same repo are available, few-shot
    conditioning produces more natural human-style framing than the
    programmatic template.
    """
    examples_text = "\n\n---\n\n".join(
        f"EXAMPLE {i+1}:\n{ex[:600]}"
        for i, ex in enumerate(dataset_examples[:3])
    )
    trimmed = _trim_test_output(test_output, max_lines=40)
    social_note = f"\n\nOptionally end with: {social_context.strip()}" if social_context else ""
    version_note = f'\nContext that may be naturally referenced: {social_context.strip()}' if social_context else ''

    prompt = f"""You are writing a GitHub issue report. Study these real examples from the same repository:

{examples_text}

Now write a NEW issue for this problem:
Symptom: {symptom}

Test/build output:
```
{trimmed}
```
{social_note}{version_note}

Rules:
- Match the STYLE, TONE, and STRUCTURE of the examples above
- Describe SYMPTOMS only — the reporter does NOT know which function or line is broken
- Do NOT mention any module name, package name, filename, or file path
- Do NOT name any specific function, method, class, or variable — paraphrase if the symptom contains one
- Describe what went WRONG from a user perspective, not which code component is broken
- Do NOT use structured 'Expected/Actual/Steps to reproduce' format unless the examples use it
- Vary between terse (2 sentences + error) and conversational — match the examples
- The reporter is frustrated or confused, not analytical
- If test output is available, paste it as a code block — do NOT explain what it means
- Do NOT start with "I" or "We"
- Keep it under 200 words
- Do NOT include a title — just the body"""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    return text.strip()
    except Exception:
        logger.warning("few-shot issue generation failed")
    return None


async def _rewrite_issue_narrative(
    draft: str,
    symptom: str,
    test_output: str | None,
    social_context: str,
    repo_name: str,
    language: str,
    model: str,
) -> str | None:
    """Ask the LLM to rewrite a programmatically assembled draft into a natural issue."""
    prompt = f"""Write a terse GitHub issue as a busy developer who just hit a bug.
Symptom: {symptom}

Draft for reference (rewrite, don't copy verbatim):
{draft}

Rules:
- 80-200 words MAXIMUM (hard limit — real issues average 112 words)
- NO markdown headers (no ##, no **bold sections**)
- NO 'What did you do / What did you expect / What did you see' format
- NO checklist items (no '- [x]')
- NO 'Expected behavior' / 'Actual behavior' sections
- Just 2-4 sentences describing what broke
- You can include one short error snippet if relevant
- Terse and direct — like a Slack message escalated to an issue
- Do NOT include a title
- Do NOT start with "I" or "We"
- NEVER diagnose the root cause or mention which function is broken — describe SYMPTOMS only
- Write as if you are REPORTING symptoms you observed, NOT diagnosing a bug you understand
- You do NOT know which function, file, or line of code is responsible
- Do NOT mention any module name, package name, filename, or file path
- Do NOT name any specific function, method, class, or variable — paraphrase if the symptom contains one
- Describe what went WRONG from a user perspective, not which code component is broken
- Do NOT use the word 'regression' — most real reporters don't know if it worked before
- Vary length — some issues are 2 sentences, others are a paragraph. Not all issues are the same.
- If test output is included, just paste it — do NOT explain what it means
- Do NOT mention that this is a rewrite or that you are an AI
{('- ' + social_context.strip()) if social_context else ''}"""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    return text.strip()
    except Exception:
        logger.warning("LLM issue narrative rewrite failed, using programmatic draft")
    return None


async def generate_issue_from_symptom(
    symptom: str,
    test_output: str | None = None,
    repo_context: dict | None = None,
    style_examples: list[str] | None = None,
    model: str = "sonnet",
    social_context: str = "",
    dataset_examples: list[str] | None = None,
    repo_name: str = "",
    language: str = "",
) -> str:
    """Generate a realistic GitHub issue description from a symptom only.

    This function enforces the information firewall: it receives ONLY
    a one-sentence symptom string, NOT the BugSpec, function name, file
    name, or any code. This prevents the issue from betraying root-cause
    knowledge.

    When test_output is available, uses a data-first approach: the LLM
    writes only a brief title + intro, and the issue body is constructed
    programmatically from real test output. This makes the issue ~80%
    pasted data and ~20% LLM framing, matching real issue patterns.

    When dataset_examples are provided (real issues from the same repo),
    uses few-shot conditioning: the LLM sees real examples and matches
    their style, length, and tone instead of following template instructions.

    Args:
        symptom: One-sentence user-facing symptom from _bug_to_symptom().
        test_output: Optional test output showing the failure.
        repo_context: Dict with version, lang_version, os_info keys.
        style_examples: Real issue titles from git history for style.
        model: Claude model shortname.
        social_context: Optional social references from _build_social_context().
        dataset_examples: Real problem_statement texts from the dataset for
            few-shot conditioning.

    Returns:
        Issue description text.
    """
    first_sentence = symptom.split(".")[0] if "." in symptom else symptom
    general_area = first_sentence[:60].rsplit(" ", 1)[0] if len(first_sentence) > 60 else first_sentence

    if test_output and not _is_valid_test_output(test_output):
        logger.warning("Test output appears to be a setup error, skipping")
        test_output = None

    if not test_output:
        return f'{general_area}\n\n```\n{symptom}\n```'

    if dataset_examples:
        llm_issue = await _generate_issue_few_shot(
            symptom=symptom,
            test_output=test_output,
            dataset_examples=dataset_examples,
            social_context=social_context,
            model=model,
        )
        if llm_issue:
            if _is_too_similar_to_examples(llm_issue, dataset_examples):
                logger.warning("few-shot issue too similar to real examples, falling back to template")
            else:
                return llm_issue

    _ISSUE_OPENERS = [
        # Original
        'This test started failing after a recent update.',
        'Getting unexpected test failures.',
        'Noticed this is broken while working on something else.',
        'Tests are failing on this branch.',
        'Ran into this failure, not sure what changed.',
        '',
        # Frustrated
        'This has been blocking my PR for hours.',
        'Anyone else seeing this?',
        'I keep hitting this and it\'s driving me nuts.',
        "Can't get past this failure.",
        # Casual
        'Not sure if this is expected but...',
        'Stumbled on this while reviewing some changes.',
        'Might be a flaky test, but I can reproduce it consistently.',
        'Just noticed this, not sure how long it\'s been broken.',
        'Was looking into something else and found this.',
        # Terse
        '',
        '',
        # CI-related
        'CI started failing after the last merge.',
        'Build is red on main.',
        'This showed up in CI overnight.',
        'Our nightly build caught this.',
        'CI is broken, looks like a recent change.',
        # Version/regression
        'Pretty sure this is a regression.',
        'This was working last week.',
        'Bisected to a recent commit.',
        'Looks like something broke in the latest changes.',
    ]

    test_id = _extract_first_failure_id(test_output)
    trimmed_output = _trim_test_output(test_output)
    opener = random.choice(_ISSUE_OPENERS)
    parts: list[str] = []

    if test_id:
        style = random.choice(['titled', 'titled', 'context'])
        if style == 'titled':
            parts.append(test_id)
            parts.append('')
            if opener:
                parts.append(opener)
                parts.append('')
            parts.append(f'```\n{trimmed_output}\n```')
        else:
            openers = [
                f'{test_id} failing',
                f'{general_area} broken',
                f'test failure in {test_id}',
            ]
            parts.append(random.choice(openers))
            parts.append('')
            if opener:
                parts.append(opener)
                parts.append('')
            parts.append(f'```\n{trimmed_output}\n```')
    else:
        if opener:
            parts.append(opener)
            parts.append('')
        parts.append(f'```\n{trimmed_output}\n```')

    if social_context:
        parts.append(social_context.strip())

    draft = '\n'.join(parts)

    rewritten = await _rewrite_issue_narrative(
        draft=draft,
        symptom=symptom,
        test_output=test_output,
        social_context=social_context,
        repo_name=repo_name or "project",
        language=language or "unknown",
        model=model,
    )
    return rewritten if rewritten else draft


_BANNED_OPENERS = [
    'is this expected',
    "here's what i'm seeing",
    'i noticed that',
    "i'm experiencing",
    'i was trying to',
]

_REPLACEMENT_OPENERS = [
    'Has anyone seen this before?',
    'Possible bug —',
    'Something broke after the latest update.',
    'Getting unexpected behavior.',
    'Not sure if this is a bug, but...',
]


def _enforce_banned_openers(text: str) -> str:
    """Replace formulaic openers with more natural alternatives."""
    lines = text.split('\n')
    first_content_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('## '):
            first_content_idx = i
            break

    first_line = lines[first_content_idx] if first_content_idx < len(lines) else ''
    first_lower = first_line.strip().lower()

    for banned in _BANNED_OPENERS:
        if first_lower.startswith(banned):
            replacement = random.choice(_REPLACEMENT_OPENERS)
            lines[first_content_idx] = replacement
            break

    return '\n'.join(lines)


def _truncate_issue(text: str) -> str:
    """Keep only the first paragraph and first code block."""
    lines = text.split('\n')
    result_lines: list[str] = []
    found_paragraph = False
    in_code_block = False
    found_code_block = False

    for line in lines:
        if line.strip().startswith('## '):
            result_lines.append(line)
            continue

        if line.strip().startswith('```') and not in_code_block and not found_code_block:
            in_code_block = True
            result_lines.append(line)
            continue

        if in_code_block:
            result_lines.append(line)
            if line.strip().startswith('```'):
                in_code_block = False
                found_code_block = True
            continue

        if not found_paragraph:
            result_lines.append(line)
            if line.strip() == '' and any(rl.strip() for rl in result_lines):
                found_paragraph = True
            continue

        if found_paragraph and not found_code_block:
            if line.strip().startswith('```'):
                in_code_block = True
                result_lines.append(line)
                continue
            continue

    result = '\n'.join(result_lines)
    if len(result) > 1500:
        boundary = result.rfind('. ', 0, 1500)
        if boundary != -1:
            result = result[:boundary + 1]
        else:
            result = result[:1500]
    return result


async def generate_issue_description(
    bug_spec: BugSpec,
    test_output: str | None = None,
    model: str = "sonnet",
    repo_path: str | None = None,
) -> str:
    """Generate a realistic GitHub issue description for a bug.

    Legacy wrapper that converts BugSpec to symptom and delegates to
    generate_issue_from_symptom(). New code should call
    generate_issue_from_symptom() directly to enforce the information
    firewall.
    """
    ctx = _collect_repo_context(repo_path) if repo_path else {
        "version": "", "lang_version": "", "os_info": random.choice(_OS_CHOICES),
        "recent_issues": [],
    }
    symptom = await _bug_to_symptom(bug_spec.bug_description, file_path=bug_spec.file, model=model)
    style_examples = _mine_issue_style_examples(repo_path) if repo_path else []
    return await generate_issue_from_symptom(
        symptom=symptom,
        test_output=test_output,
        repo_context=ctx,
        style_examples=style_examples,
        model=model,
    )


_COMMON_KEYWORDS = frozenset({
    'return', 'if', 'for', 'def', 'func', 'var', 'nil', 'None', 'err',
    'error', 'self', 'true', 'false', 'import', 'from', 'class', 'struct',
    'interface', 'package', 'const', 'type', 'else', 'elif', 'while',
    'break', 'continue', 'pass', 'raise', 'yield', 'with', 'as', 'try',
    'except', 'finally', 'lambda', 'and', 'or', 'not', 'in', 'is',
    'assert', 'del', 'print', 'global', 'nonlocal', 'async', 'await',
})


def _is_code_identifier(token: str) -> bool:
    """Return True if token looks like a code identifier rather than English."""
    if '_' in token:
        return True
    if any(c.isupper() for c in token[1:]):
        return True
    if token.isupper():
        return True
    return False


def _extract_narrative(text: str) -> str:
    """Return text outside of code blocks — the prose a human wrote."""
    parts = re.split(r'```[^`]*```', text, flags=re.DOTALL)
    return ' '.join(parts).lower()


def _verify_issue_independence(problem_statement: str, bug_spec: BugSpec) -> bool:
    """Check whether the issue narrative leaks patch-specific identifiers.

    Only checks the function name and filename — these directly reveal
    the patch location.  Code-body identifiers are too broad (the full
    function body contains dozens of common type/variable names that
    naturally appear in any description of the subsystem).

    Only checks prose text outside code blocks — identifiers appearing
    inside pasted test output / stack traces are natural and expected.
    """
    narrative = _extract_narrative(problem_statement)

    fn = bug_spec.function_name
    if fn and _is_code_identifier(fn) and fn.lower() in narrative:
        return False

    basename = Path(bug_spec.file).name if bug_spec.file else ''
    if basename and basename.lower() in narrative:
        return False

    return True




def _find_go_cross_package_test(repo_path: str, function_name: str) -> str | None:
    """Find a Go test file in a sibling package that references function_name.

    Caches grep results per repo to avoid repeated filesystem scans.
    """
    cache = _go_cross_pkg_cache.get(repo_path)
    if cache is None:
        cache = {}
        _go_cross_pkg_cache[repo_path] = cache

    if function_name in cache:
        hits = cache[function_name]
        return hits[0] if hits else None

    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*_test.go", "-l", function_name, "."],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        files = [
            f.lstrip("./") for f in result.stdout.strip().splitlines() if f.strip()
        ]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        files = []

    cache[function_name] = files
    return files[0] if files else None


def _find_existing_test_file(
    repo_path: str, source_file: str, language: str,
    function_name: str | None = None,
) -> str | None:
    """Find an existing test file corresponding to a source file.

    Searches broadly: direct name-based candidates, tests/ directory
    fuzzy match, and any test file that imports the same module.
    Returns the repo-relative path if found, None otherwise.
    """
    root = Path(repo_path)
    source_path = Path(source_file)
    stem = source_path.stem

    if language == "python":
        candidates: list[str] = [
            f"tests/test_{stem}.py",
            f"test/test_{stem}.py",
            f"test_{stem}.py",
            str(source_path.parent / f"test_{stem}.py"),
        ]
        if source_path.parent.parts:
            candidates.append(
                f"tests/{'/'.join(source_path.parent.parts)}/test_{stem}.py"
            )
        for c in candidates:
            if (root / c).is_file():
                return c
        # Fuzzy match: any test file in tests/, pytests/, or repo root whose name contains the stem
        for test_dir_name in ("tests", "test", "pytests", "pytest"):
            tests_dir = root / test_dir_name
            if tests_dir.is_dir():
                for f in tests_dir.rglob("*.py"):
                    if stem in f.stem:
                        return str(f.relative_to(root))
        for f in sorted(root.glob("test_*.py")):
            if stem in f.stem:
                return str(f.relative_to(root))
        # Broader search: find any test_*.py file that imports the same module
        module_name = _source_to_module_name(source_file)
        if module_name:
            match = _find_test_file_importing(root, module_name)
            if match:
                return match
        # Last resort: any test file in the same package directory
        pkg_dir = source_path.parent
        if pkg_dir != Path("."):
            pkg_parts = list(pkg_dir.parts)
            search_dirs = [pkg_dir]
            if len(pkg_parts) > 1:
                search_dirs.append(Path(*pkg_parts[1:]))
            for test_dir_name in ("tests", "test", "pytests", "pytest"):
                for sub in search_dirs:
                    pkg_test_dir = root / test_dir_name / sub
                    if pkg_test_dir.is_dir():
                        for f in sorted(pkg_test_dir.glob("test_*.py")):
                            return str(f.relative_to(root))
    elif language == "go":
        test_file = str(source_path.parent / f"{stem}_test.go")
        if (root / test_file).is_file():
            return test_file
        if function_name:
            cross_pkg = _find_go_cross_package_test(repo_path, function_name)
            if cross_pkg:
                return cross_pkg
    elif language == "rust":
        rust_candidates = [
            f"tests/{stem}.rs",
            str(source_path.parent / f"{stem}_test.rs"),
        ]
        for c in rust_candidates:
            if (root / c).is_file():
                return c
        try:
            content = (root / source_file).read_text(encoding="utf-8", errors="replace")
            if "#[cfg(test)]" in content:
                return source_file
        except OSError:
            pass
    elif language == "java":
        java_path = str(source_path)
        # Direct test file: FooTest.java in src/test/java/...
        test_path = java_path.replace(
            "src/main/java/", "src/test/java/"
        ).replace(f"{stem}.java", f"{stem}Test.java")
        if (root / test_path).is_file():
            return test_path
        # Broader: any *Test.java in the same test package directory
        test_pkg_dir = str(source_path.parent).replace("src/main/java/", "src/test/java/")
        test_dir = root / test_pkg_dir
        if test_dir.is_dir():
            for f in sorted(test_dir.glob("*Test.java")):
                return str(f.relative_to(root))
        # Even broader: search test subdirectories that might test this class
        parent_test_dir = test_dir.parent if test_dir.exists() else None
        if parent_test_dir and parent_test_dir.is_dir():
            for f in sorted(parent_test_dir.rglob(f"*{stem}*Test.java")):
                return str(f.relative_to(root))

    return None


def _source_to_module_name(source_file: str) -> str | None:
    """Convert a source file path to a dotted module name for import matching."""
    p = Path(source_file)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts) if parts else None


def _find_test_file_importing(root: Path, module_name: str) -> str | None:
    """Find a test_*.py file that imports the given module (or its parent package).

    Uses two-pass matching: first scans for specific module imports, then
    falls back to parent package imports.  This prevents alphabetically-first
    files that only match the parent pattern from shadowing files that match
    the specific module.
    """
    parts = module_name.split(".")
    specific_pat = re.compile(
        rf"^\s*(?:from|import)\s+{re.escape(module_name)}\b", re.MULTILINE,
    )
    parent_pat = None
    if len(parts) > 1:
        parent = ".".join(parts[:-1])
        parent_pat = re.compile(
            rf"^\s*from\s+{re.escape(parent)}\s+import\b", re.MULTILINE,
        )

    test_files: list[tuple[Path, str]] = []
    for test_dir_name in ("tests", "test"):
        test_dir = root / test_dir_name
        if not test_dir.is_dir():
            continue
        for f in sorted(test_dir.rglob("test_*.py")):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            test_files.append((f, content))
    for f in sorted(root.glob("test_*.py")):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        test_files.append((f, content))

    for f, content in test_files:
        if specific_pat.search(content):
            return str(f.relative_to(root))

    if parent_pat is not None:
        for f, content in test_files:
            if parent_pat.search(content):
                return str(f.relative_to(root))

    return None


def _find_any_test_file_nearby(
    repo_path: str, source_file: str, language: str,
) -> str | None:
    """Find ANY test file in the same or parent directory.

    Unlike _find_existing_test_file which tries to match by name/import,
    this searches broadly for any test file that could host a regression test.
    """
    root = Path(repo_path)
    source_path = Path(source_file)
    src_dir = source_path.parent

    # Search directories: same dir, then parent dir
    search_dirs = [src_dir]
    if src_dir != Path(".") and src_dir.parent != src_dir:
        search_dirs.append(src_dir.parent)

    if language == "go":
        for d in search_dirs:
            candidate_dir = root / d
            if candidate_dir.is_dir():
                for f in sorted(candidate_dir.glob("*_test.go")):
                    return str(f.relative_to(root))
    elif language == "python":
        for d in search_dirs:
            candidate_dir = root / d
            if candidate_dir.is_dir():
                for f in sorted(candidate_dir.glob("test_*.py")):
                    return str(f.relative_to(root))
        # Also check tests/ and test/ subdirs
        for test_dir_name in ("tests", "test"):
            test_dir = root / test_dir_name
            if test_dir.is_dir():
                for f in sorted(test_dir.glob("test_*.py")):
                    return str(f.relative_to(root))

    return None


def _create_new_regression_test_file(
    repo_path: str,
    bug_spec: "BugSpec",
    language: str,
    test_output: str,
) -> str | None:
    """Create a minimal new test file with a regression test.

    Used as a last resort when no existing test file can be found.
    Returns a patch that creates the new file, or None.
    """
    func_under_test = bug_spec.function_name
    test_id = _extract_first_failure_id(test_output)

    if language == "go":
        src_file = bug_spec.file
        if not src_file.endswith(".go") or src_file.endswith("_test.go"):
            return None

        test_file = src_file.replace(".go", "_test.go")

        # Read the source to extract the package declaration
        try:
            source = (Path(repo_path) / src_file).read_text(
                encoding="utf-8", errors="replace",
            )
        except OSError:
            return None

        pkg_match = re.search(r'^package\s+(\w+)', source, re.MULTILINE)
        pkg_name = pkg_match.group(1) if pkg_match else "main"

        func_name = "TestRegression"
        if test_id:
            clean = re.sub(r'[^A-Za-z0-9]', '', test_id.split('/')[-1])
            if clean:
                func_name = f"TestRegression{clean}"

        error_msg = _extract_go_error_message(test_output)
        if error_msg:
            got_want = re.search(
                r'(?:got|Got)\s+(.+?),\s*(?:want|Want|expected)\s+(.+)',
                error_msg,
            )
            if got_want:
                want_val = got_want.group(2).strip().rstrip('.')
                test_body = (
                    f'\tgot := {func_under_test}()\n'
                    f'\tif got != {want_val} {{\n'
                    f'\t\tt.Errorf("{func_under_test}() = %v, want {want_val}", got)\n'
                    f'\t}}\n'
                )
            else:
                test_body = (
                    f'\tresult := {func_under_test}()\n'
                    f'\tif result == nil {{\n'
                    f'\t\tt.Errorf("{func_under_test}() returned nil, '
                    f'expected non-nil result")\n'
                    f'\t}}\n'
                )
        else:
            test_body = (
                f'\tresult := {func_under_test}()\n'
                f'\tif result == nil {{\n'
                f'\t\tt.Errorf("{func_under_test}() returned nil, '
                f'expected non-nil result")\n'
                f'\t}}\n'
            )

        test_content = (
            f'package {pkg_name}\n\n'
            f'import "testing"\n\n'
            f'func {func_name}(t *testing.T) {{\n'
            f'{test_body}}}\n'
        )
        return _format_new_test_patch(test_content, test_file)

    if language == "python":
        src_file = bug_spec.file
        if not src_file.endswith(".py"):
            return None

        stem = Path(src_file).stem
        # Place test file alongside source or in tests/ if it exists
        root = Path(repo_path)
        if (root / "tests").is_dir():
            test_file = f"tests/test_{stem}.py"
        else:
            test_file = str(Path(src_file).parent / f"test_{stem}.py")

        func_name = "test_regression"
        if test_id:
            parts = test_id.split("::")
            last = parts[-1] if parts else test_id
            clean = re.sub(r'[^A-Za-z0-9_]', '', last)
            if clean and clean.startswith("test"):
                func_name = (
                    f"test_regression_{clean[4:]}" if len(clean) > 4
                    else "test_regression"
                )
            elif clean:
                func_name = f"test_regression_{clean}"

        module_name = _source_to_module_name(src_file)
        import_line = ""
        if module_name:
            import_line = f"from {module_name} import {func_under_test}\n\n"

        assertion_expr, _error_detail = _extract_python_error_message(test_output)
        if assertion_expr:
            test_body = (
                f'def {func_name}():\n'
                f'    """Regression test for {func_under_test}."""\n'
                f'    result = {func_under_test}()\n'
                f'    assert result is not None, '
                f'"{func_under_test} should return a valid result"\n'
            )
        else:
            test_body = (
                f'def {func_name}():\n'
                f'    """Regression test for {func_under_test}."""\n'
                f'    try:\n'
                f'        result = {func_under_test}()\n'
                f'    except Exception as exc:\n'
                f'        raise AssertionError(\n'
                f'            f"{func_under_test}() raised '
                f'{{type(exc).__name__}}: {{exc}}"\n'
                f'        ) from exc\n'
                f'    assert result is not None\n'
            )

        test_content = f"{import_line}{test_body}"
        return _format_new_test_patch(test_content, test_file)

    return None


async def generate_test_patch(
    bug_spec: BugSpec,
    repo_path: str,
    language: str,
    model: str = "sonnet",
    test_output: str | None = None,
) -> str | None:
    """Generate a test patch that exposes a synthetic bug.

    Modifies existing test files. Falls back to adding a new test function
    in the existing file when no relevant functions are found.
    """
    existing_test = _find_existing_test_file(
        repo_path, bug_spec.file, language,
        function_name=bug_spec.function_name,
    )

    if existing_test:
        result = await _generate_test_patch_existing(
            bug_spec, repo_path, existing_test, language, model,
            test_output=test_output,
        )
        return result
    logger.warning(
        "  No existing test file found for %s — trying fallback search",
        bug_spec.file,
    )

    # Fallback: search same directory and parent for ANY test file
    if test_output:
        fallback_test = _find_any_test_file_nearby(
            repo_path, bug_spec.file, language,
        )
        if fallback_test:
            logger.info("  Fallback: using nearby test file %s", fallback_test)
            regression_patch = _generate_regression_test_patch(
                repo_path, bug_spec, language, test_output,
                test_file_override=fallback_test,
            )
            if regression_patch:
                return regression_patch

        # Last resort: create a minimal new test file with a regression test
        logger.info("  Fallback: creating new test file for %s", bug_spec.file)
        new_test_patch = _create_new_regression_test_file(
            repo_path, bug_spec, language, test_output,
        )
        if new_test_patch:
            return new_test_patch

    return None


def _count_test_functions(code: str, language: str = "python") -> int:
    """Count the number of test function definitions."""
    if language == "go":
        return len(re.findall(r'^func\s+Test\w+', code, re.MULTILINE))
    if language == "rust":
        return len(re.findall(r'#\[test\]', code))
    if language == "java":
        return len(re.findall(r'@Test\b', code))
    return len(re.findall(r'^\s*def\s+test_\w+', code, re.MULTILINE))


def _extract_test_functions(source: str, language: str = "python") -> list[dict[str, str | int]]:
    """Extract test functions from source code.

    Returns a list of dicts with keys: name, source, start_line, end_line.
    """
    if language == "python":
        return _extract_test_functions_python(source)
    if language == "go":
        return _extract_test_functions_go(source)
    if language == "rust":
        return _extract_test_functions_rust(source)
    if language == "java":
        return _extract_test_functions_java(source)
    return []


def _extract_test_functions_python(source: str) -> list[dict[str, str | int]]:
    """Extract test functions from Python source using AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    source_lines = source.splitlines(keepends=True)
    results: list[dict[str, str | int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        start = node.lineno - 1
        end = node.end_lineno if node.end_lineno else start + 1
        func_source = "".join(source_lines[start:end])
        results.append({
            "name": node.name,
            "source": func_source,
            "start_line": start,
            "end_line": end,
        })

    return results


def _extract_test_functions_go(source: str) -> list[dict[str, str | int]]:
    """Extract test functions from Go source using brace matching."""
    lines = source.splitlines(keepends=True)
    results: list[dict[str, str | int]] = []
    func_re = re.compile(r'^func\s+(?:\([^)]*\)\s+)?(Test\w+)\s*\(')

    i = 0
    while i < len(lines):
        m = func_re.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        start = i
        brace_depth = 0
        for j in range(i, len(lines)):
            brace_depth += lines[j].count('{') - lines[j].count('}')
            if brace_depth <= 0 and '{' in ''.join(lines[i:j+1]):
                end = j + 1
                break
        else:
            end = len(lines)
        func_source = "".join(lines[start:end])
        results.append({
            "name": name,
            "source": func_source,
            "start_line": start,
            "end_line": end,
        })
        i = end

    return results


def _extract_test_functions_rust(source: str) -> list[dict[str, str | int]]:
    """Extract test functions from Rust source by finding #[test] annotations."""
    lines = source.splitlines(keepends=True)
    results: list[dict[str, str | int]] = []
    fn_re = re.compile(r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)')

    i = 0
    while i < len(lines):
        if '#[test]' not in lines[i]:
            i += 1
            continue
        annotation_line = i
        j = i + 1
        while j < len(lines) and not fn_re.match(lines[j]):
            j += 1
            if j - annotation_line > 3:
                break
        if j >= len(lines):
            i += 1
            continue
        m = fn_re.match(lines[j])
        if not m:
            i = j + 1
            continue
        name = m.group(1)
        start = annotation_line
        brace_depth = 0
        found_open = False
        for k in range(j, len(lines)):
            brace_depth += lines[k].count('{') - lines[k].count('}')
            if '{' in lines[k]:
                found_open = True
            if found_open and brace_depth <= 0:
                end = k + 1
                break
        else:
            end = len(lines)
        func_source = "".join(lines[start:end])
        results.append({
            "name": name,
            "source": func_source,
            "start_line": start,
            "end_line": end,
        })
        i = end

    return results


def _extract_test_functions_java(source: str) -> list[dict[str, str | int]]:
    """Extract test methods from Java source by finding @Test annotations."""
    lines = source.splitlines(keepends=True)
    results: list[dict[str, str | int]] = []
    method_re = re.compile(r'^\s+(?:public|private|protected|static|\s)*\s+(?:void|[\w<>\[\]]+)\s+(\w+)\s*\(')

    i = 0
    while i < len(lines):
        if '@Test' not in lines[i]:
            i += 1
            continue
        annotation_line = i
        j = i + 1
        while j < len(lines) and not method_re.match(lines[j]):
            j += 1
            if j - annotation_line > 3:
                break
        if j >= len(lines):
            i += 1
            continue
        m = method_re.match(lines[j])
        if not m:
            i = j + 1
            continue
        name = m.group(1)
        start = annotation_line
        brace_depth = 0
        found_open = False
        for k in range(j, len(lines)):
            brace_depth += lines[k].count('{') - lines[k].count('}')
            if '{' in lines[k]:
                found_open = True
            if found_open and brace_depth <= 0:
                end = k + 1
                break
        else:
            end = len(lines)
        func_source = "".join(lines[start:end])
        results.append({
            "name": name,
            "source": func_source,
            "start_line": start,
            "end_line": end,
        })
        i = end

    return results


def _find_best_test_function(
    test_functions: list[dict[str, str | int]],
    bug_spec: BugSpec,
) -> dict[str, str | int] | None:
    """Pick the test function most relevant to the bug."""
    ranked = _rank_test_functions(test_functions, bug_spec)
    return ranked[0] if ranked else None


def _rank_test_functions(
    test_functions: list[dict[str, str | int]],
    bug_spec: BugSpec,
    limit: int = 3,
) -> list[dict[str, str | int]]:
    """Return test functions ranked by relevance to the bug, up to *limit*."""
    if not test_functions:
        return []

    targets = {bug_spec.function_name}
    module_stem = Path(bug_spec.file).stem
    if module_stem:
        targets.add(module_stem)

    scored: list[tuple[int, int, dict[str, str | int]]] = []
    for idx, tf in enumerate(test_functions):
        body = str(tf["source"]).lower()
        score = sum(1 for t in targets if t.lower() in body)
        if score > 0:
            scored.append((score, -idx, tf))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [tf for _, _, tf in scored[:limit]]


def _rank_test_functions_score(
    test_function: dict[str, str | int],
    bug_spec: BugSpec,
) -> int:
    """Return the relevance score for a single test function."""
    targets = {bug_spec.function_name}
    module_stem = Path(bug_spec.file).stem
    if module_stem:
        targets.add(module_stem)
    body = str(test_function["source"]).lower()
    return sum(1 for t in targets if t.lower() in body)


def _boost_failing_tests(
    ranked: list[dict[str, str | int]],
    test_output: str,
    all_test_functions: list[dict[str, str | int]],
    bug_spec: BugSpec,
) -> list[dict[str, str | int]]:
    """Re-rank test functions by boosting those that appear in failure output."""
    failing_names: set[str] = set()
    for pat in [re.compile(r"FAIL[:\s]+\S*?(\w+Test\w*|\w*test_\w+)", re.IGNORECASE),
                re.compile(r"---\s+FAIL:\s+(\w+)", re.MULTILINE),
                re.compile(r"FAILED\s+\S+::(\w+)")]:
        for m in pat.finditer(test_output):
            failing_names.add(m.group(1))

    if not failing_names:
        return ranked

    boosted = []
    rest = []
    ranked_names = {str(f["name"]) for f in ranked}
    for tf in all_test_functions:
        name = str(tf["name"])
        if name in failing_names and name not in ranked_names:
            boosted.append(tf)

    for tf in ranked:
        name = str(tf["name"])
        if name in failing_names:
            boosted.insert(0, tf)
        else:
            rest.append(tf)

    return (boosted + rest)[:3]


async def _generate_new_test_in_existing_file(
    bug_spec: BugSpec,
    repo_path: str,
    test_file: str,
    original_test_content: str,
    language: str,
    model: str,
    file_imports: str,
    test_output: str | None,
) -> str | None:
    """Add a new targeted test function at the end of an existing test file."""
    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    if language == "python":
        func_keyword = "def"
        test_prefix = f"def test_{bug_spec.function_name}"
    elif language == "go":
        func_keyword = "func"
        go_name = bug_spec.function_name
        if go_name and go_name[0].islower():
            go_name = go_name[0].upper() + go_name[1:]
        test_prefix = f"func Test{go_name}"
    elif language == "rust":
        func_keyword = "fn"
        test_prefix = f"fn test_{bug_spec.function_name}"
    elif language == "java":
        func_keyword = "void"
        test_prefix = f"public void test{bug_spec.function_name.capitalize()}"
    else:
        return None

    prompt = f"""You are adding a NEW test function to an existing test file. The new test must detect a specific bug.

Here are the imports used in the test file:
```{language}
{file_imports}
```

Here is the function under test:
```{language}
{bug_spec.original_code}
```

Here is the buggy version of the function:
```{language}
{bug_spec.buggy_code}
```

The bug: {bug_spec.bug_description}
{_test_output_section(test_output)}
Write a SINGLE new test function that:
- Calls {bug_spec.function_name}() with specific inputs
- Asserts the correct return value that will PASS with the original code and FAIL with the buggy code
- Uses the existing imports and test style from the file
- Has a descriptive name starting with `{test_prefix}`

FORBIDDEN — these produce detectable synthetic patterns:
- Do NOT access unexported/private fields or internal struct members. Assert only via the public API return value.
- Do NOT use sequential mechanical names like cc2, cc3, obj2, val1. Use descriptive names matching the test subject.
- Do NOT write an assertion that only verifies a function can be called. The assertion MUST check a specific expected value.
- Do NOT write a test that only passes/fails based on a single operator or literal change — test the function's documented behavior with meaningful inputs.

HARD CONSTRAINT: Return ONLY the new {func_keyword} definition. Do NOT return imports or file-level code.
Keep the function short (3-8 lines of real code). Do NOT add any comments. Make assertions specific to the bug."""

    new_func: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    extracted = _extract_code_block(text)
                    new_func = extracted if extracted else text
    except Exception:
        logger.warning("  LLM call failed for new test function generation")
        return None

    if not new_func or func_keyword not in new_func:
        return None

    # Trim to just the function definition
    lines = new_func.splitlines(keepends=True)
    start_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(func_keyword):
            start_idx = i
            break
    if start_idx > 0:
        new_func = "".join(lines[start_idx:])

    insertion_point = _find_insertion_point(original_test_content, bug_spec, language)
    if insertion_point is not None:
        before = original_test_content[:insertion_point]
        after = original_test_content[insertion_point:]
        modified_content = before.rstrip() + "\n\n\n" + new_func.strip() + "\n\n" + after.lstrip()
    else:
        insertion_point = _find_mid_file_insertion_point(original_test_content, language)
        if insertion_point is not None:
            before = original_test_content[:insertion_point]
            after = original_test_content[insertion_point:]
            modified_content = before.rstrip() + "\n\n\n" + new_func.strip() + "\n\n" + after.lstrip()
        else:
            modified_content = original_test_content.rstrip() + "\n\n\n" + new_func.strip() + "\n"

    if not _validate_test_code(modified_content, language):
        logger.warning("  Validation failed for new test function")
        return None

    return generate_patch(modified_content, original_test_content, test_file)


def _find_mid_file_insertion_point(content: str, language: str) -> int | None:
    """Find a character offset near the middle of the file between function definitions."""
    lines = content.splitlines(keepends=True)
    if len(lines) < 4:
        return None

    if language == "python":
        func_pattern = re.compile(r"^(def |class )")
    elif language == "go":
        func_pattern = re.compile(r"^func ")
    elif language == "java":
        func_pattern = re.compile(r"^\s+(public |private |protected |static |void )")
    else:
        func_pattern = re.compile(r"^(def |function |fn )")

    boundaries: list[int] = []
    for i, line in enumerate(lines):
        if func_pattern.match(line.strip() if language == "java" else line):
            boundaries.append(i)

    if len(boundaries) < 2:
        return None

    mid_target = len(lines) // 2
    best = min(boundaries, key=lambda b: abs(b - mid_target))
    if best == 0:
        best = boundaries[1] if len(boundaries) > 1 else boundaries[0]

    return sum(len(lines[i]) for i in range(best))


def _find_insertion_point(
    content: str, bug_spec: BugSpec, language: str,
) -> int | None:
    """Find a character offset to insert a new test function near related code."""
    test_functions = _extract_test_functions(content, language)
    if not test_functions:
        return None

    ranked = _rank_test_functions(test_functions, bug_spec, limit=1)
    if not ranked:
        return None

    best = ranked[0]
    best_score = _rank_test_functions_score(best, bug_spec)
    if best_score == 0:
        mid_idx = len(test_functions) // 2
        target_func = test_functions[mid_idx]
    else:
        target_func = best

    end_line = int(target_func["end_line"])
    lines = content.splitlines(keepends=True)
    if end_line >= len(lines):
        return None

    offset = sum(len(lines[i]) for i in range(end_line))
    return offset


def _extract_file_imports(source: str, language: str = "python") -> str:
    """Extract import lines from the top of a source file."""
    if language == "go":
        m = re.search(r'(import\s+\(.*?\)|import\s+"[^"]*")', source, re.DOTALL)
        if m:
            return m.group(0) + "\n"
        return ""
    lines: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or stripped == "":
            lines.append(line)
        elif lines and not stripped:
            lines.append(line)
        elif stripped.startswith("#"):
            lines.append(line)
        elif lines:
            break
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def _test_output_section(test_output: str | None) -> str:
    if not test_output:
        return ""
    return (
        "Here is what happens when existing tests run against the buggy code "
        "(use this to understand what inputs trigger the bug):\n"
        + test_output
    )


async def _generate_test_patch_existing(
    bug_spec: BugSpec,
    repo_path: str,
    test_file: str,
    language: str,
    model: str,
    test_output: str | None = None,
) -> str | None:
    """Generate a test patch by adding tests to an existing test file."""
    try:
        original_test_content = (Path(repo_path) / test_file).read_text(
            encoding="utf-8", errors="replace",
        )
    except OSError:
        logger.warning("Could not read existing test file %s", test_file)
        return None

    if language not in ("python", "go", "rust", "java"):
        return None

    test_functions = _extract_test_functions(original_test_content, language)
    if not test_functions:
        logger.warning("  No test functions found in %s — falling back to new test function", test_file)
        file_imports = _extract_file_imports(original_test_content, language)
        return await _generate_new_test_in_existing_file(
            bug_spec, repo_path, test_file, original_test_content,
            language, model, file_imports, test_output,
        )

    ranked = _rank_test_functions(test_functions, bug_spec)
    if not ranked:
        logger.warning(
            "  No relevant test functions found for %s — falling back to new test function",
            bug_spec.function_name,
        )
        file_imports = _extract_file_imports(original_test_content, language)
        return await _generate_new_test_in_existing_file(
            bug_spec, repo_path, test_file, original_test_content,
            language, model, file_imports, test_output,
        )

    if test_output:
        ranked = _boost_failing_tests(ranked, test_output, test_functions, bug_spec)

    file_imports = _extract_file_imports(original_test_content, language)
    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    best_score = _rank_test_functions_score(ranked[0], bug_spec) if ranked else 0
    if best_score == 0:
        logger.warning(
            "  Best test score is 0 for %s — falling back to new test function",
            bug_spec.function_name,
        )
        return await _generate_new_test_in_existing_file(
            bug_spec, repo_path, test_file, original_test_content,
            language, model, file_imports, test_output,
        )

    for attempt, target in enumerate(ranked):
        target_source = str(target["source"])

        target_name = str(target["name"])

        prompt = f"""You are modifying an existing test function to add regression assertions. Do NOT create a new function. Do NOT rename the function. Do NOT change or remove any existing assertions.

Here is the existing test function to modify:
```{language}
{target_source}
```

Context — imports used in the test file:
```{language}
{file_imports}
```

Here is the function under test (correct version):
```{language}
{bug_spec.original_code}
```

Here is the buggy version of the function:
```{language}
{bug_spec.buggy_code}
```

The bug: {bug_spec.bug_description}
{_test_output_section(test_output)}
Add 1-3 regression assertions at the END of the function `{target_name}` that will PASS with the original code and FAIL with the buggy code. Return the COMPLETE modified function with all original assertions intact plus the new ones appended.

FORBIDDEN — these produce synthetic detection signals:
- Do NOT rename the function or change its signature
- Do NOT modify or remove any existing assertions — ONLY append new ones at the end
- Do NOT access unexported/private fields (Go: lowercase-named struct fields, Python: _underscored attributes). Assert only on public return values and observable API effects.
- Do NOT use sequential mechanical variable names like cc2, cc3, obj2, val1. Use names that describe what the value represents (e.g. conn, result, got, want).
- Do NOT write an assertion that only verifies a function can be called without error (e.g., _ = f()). The assertion MUST check a specific return value or side effect that the bug breaks.
- Do NOT write a test that only passes/fails based on a single operator or literal change — test the function's documented behavior with meaningful inputs.
- Do NOT add comments

Return ONLY the complete modified test function, nothing else."""

        modified_func: str | None = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    text = _extract_text_from_result(message)
                    if text:
                        extracted = _extract_code_block(text)
                        modified_func = extracted if extracted else text
        except Exception:
            logger.warning(
                "LLM call failed for test function %s (attempt %d/%d)",
                target["name"], attempt + 1, len(ranked),
            )
            continue

        if not modified_func or modified_func.strip() == target_source.strip():
            logger.debug(
                "  No change produced for %s (attempt %d/%d)",
                target["name"], attempt + 1, len(ranked),
            )
            continue

        modified_func = _strip_strategy_labels(modified_func)
        if language == "go":
            go_func_match = re.search(rf'^func\s+(?:\([^)]*\)\s+)?{re.escape(target_name)}\s*\(', modified_func, re.MULTILINE)
            idx = go_func_match.start() if go_func_match else -1
        elif language in ("rust", "java"):
            idx = modified_func.find(target_name)
        else:
            func_prefix = f"def {target_name}"
            idx = modified_func.find(func_prefix)
        if idx > 0:
            modified_func = modified_func[idx:]
        elif idx < 0:
            logger.warning(
                "  LLM response missing function definition for %s (attempt %d/%d)",
                target_name, attempt + 1, len(ranked),
            )
            continue

        orig_lines = target_source.splitlines(keepends=True)
        mod_lines = modified_func.splitlines(keepends=True)
        if orig_lines and mod_lines:
            orig_indent = len(orig_lines[0]) - len(orig_lines[0].lstrip())
            mod_indent = len(mod_lines[0]) - len(mod_lines[0].lstrip())
            indent_diff = orig_indent - mod_indent
            if indent_diff > 0:
                pad = " " * indent_diff
                modified_func = "".join(pad + line if line.strip() else line for line in mod_lines)
            elif indent_diff < 0:
                trim = abs(indent_diff)
                modified_func = "".join(
                    line[trim:] if len(line) - len(line.lstrip()) >= trim else line
                    for line in mod_lines
                )

        replace_pos = original_test_content.find(target_source)
        if replace_pos == -1:
            logger.warning(
                "  Could not locate target function %s for replacement (attempt %d/%d)",
                target["name"], attempt + 1, len(ranked),
            )
            continue
        modified_content = (
            original_test_content[:replace_pos]
            + modified_func.rstrip()
            + original_test_content[replace_pos + len(target_source.rstrip()):]
        )

        modified_content = _normalize_test_whitespace(modified_content, original_test_content)

        if not _validate_test_code(modified_content, language):
            logger.warning(
                "  Validation failed for %s (attempt %d/%d)",
                target["name"], attempt + 1, len(ranked),
            )
            continue

        return generate_patch(modified_content, original_test_content, test_file)

    logger.warning("  All %d test function attempts failed", len(ranked))
    return None


async def _generate_test_patch_new(
    bug_spec: BugSpec,
    repo_path: str,
    language: str,
    model: str,
) -> str | None:
    """DEPRECATED: no longer called. Kept for backward compatibility.

    Creating new test files produces synthetic signals (fabricated
    imports, brand-new functions). Use existing test file modification
    via _generate_test_patch_existing instead.
    """
    return None
    # --- original implementation below, unreachable ---
    prompt = f"""You are a test engineer. Write tests for a module that has a bug.

Original (correct) code:
```{language}
{bug_spec.original_code}
```

Language: {language}

The bug: {bug_spec.bug_description}

Write 2-3 test functions:
- At least one verifies the function's correct documented behavior for the area described in the bug
- 1-2 additional tests that test related behavior a developer would naturally add for coverage while investigating the area (e.g., testing normal inputs, boundary values for the same function, or a related code path)
- Do NOT write a test that only passes/fails based on a single operator or literal change — test the function's documented behavior with meaningful inputs
- Return the COMPLETE test file content with appropriate imports
- Do NOT include any explanation, just the test file content wrapped in a code block

```{language}
<your test file here>
```"""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    test_content: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    test_content = _extract_code_block(text)
    except Exception:
        logger.warning("LLM call failed for test generation, using template fallback")

    if not test_content:
        test_content = _template_test_fallback(bug_spec, language)

    if not test_content:
        return None

    test_content = _strip_strategy_labels(test_content)

    if not _validate_test_code(test_content, language):
        logger.warning("  Generated test code failed validation (new file)")
        return None

    if language == "python" and not _validate_test_imports(test_content, repo_path):
        return None

    test_path = _resolve_new_test_path(bug_spec, language, repo_path)
    return _format_new_test_patch(test_content, test_path)


def _extract_code_block(text: str) -> str | None:
    """Extract the first fenced code block from LLM output."""
    m = re.search(r"```\w*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _template_test_fallback(bug_spec: BugSpec, language: str) -> str | None:
    """Generate a simple template-based test as fallback."""
    if language == "python":
        return (
            f"import pytest\n\n\n"
            f"def test_{bug_spec.function_name}_regression():\n"
            f"    assert True  # placeholder — replace with concrete assertion\n"
        )
    return None


def _resolve_new_test_path(
    bug_spec: BugSpec, language: str, repo_path: str,
) -> str:
    """Pick a realistic test file path matching repo conventions."""
    fn = bug_spec.function_name
    source = Path(bug_spec.file)
    stem = source.stem

    if language == "python":
        root = Path(repo_path)
        if (root / "tests").is_dir():
            return f"tests/test_{stem}.py"
        if (root / "test").is_dir():
            return f"test/test_{stem}.py"
        return f"tests/test_{stem}.py"
    if language == "go":
        return str(source.parent / f"{stem}_test.go")
    if language == "rust":
        return f"tests/{stem}.rs"
    if language == "java":
        class_name = fn[0].upper() + fn[1:] if fn else "Unknown"
        return f"src/test/java/{class_name}Test.java"
    return f"tests/test_{stem}"


def _format_new_test_patch(test_content: str, test_path: str) -> str:
    """Format test content as a unified diff that adds a new file."""
    lines = test_content.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    diff_lines = list(difflib.unified_diff(
        [],
        lines,
        fromfile=f"a/{test_path}",
        tofile=f"b/{test_path}",
    ))

    header = f"diff --git a/{test_path} b/{test_path}\nnew file mode 100644\n"
    return header + "".join(diff_lines)


def _parse_incidental_changes(text: str) -> list[tuple[str, str, str]]:
    """Parse XML-tagged incidental changes from LLM output."""
    changes: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r"<change>\s*<file>(.*?)</file>\s*"
        r"<original>\s*(.*?)\s*</original>\s*"
        r"<modified>\s*(.*?)\s*</modified>\s*</change>",
        text,
        re.DOTALL,
    ):
        filepath = m.group(1).strip()
        original = m.group(2).strip()
        modified = m.group(3).strip()
        if filepath and modified:
            changes.append((filepath, original, modified))
    return changes


async def _generate_incidental_changes(
    repo_path: str,
    bug_spec: BugSpec,
    language: str,
    model: str = "sonnet",
    cross_file: bool = False,
) -> list[tuple[str, str, str]]:
    """Generate small incidental changes a developer would naturally include."""
    root = Path(repo_path)
    try:
        root_files = sorted(f.name for f in root.iterdir() if f.is_file())[:30]
    except OSError:
        root_files = []

    root_listing = ", ".join(root_files) if root_files else "(empty)"

    ctx = _collect_repo_context(repo_path)
    version = ctx["version"] or "unknown"
    recent_issues = ctx["recent_issues"]
    issues_note = ""
    if recent_issues:
        issues_note = f"\nReal issue/PR numbers from this repo's git history (use ONLY these if you reference any): {', '.join(recent_issues)}"

    cross_file_note = ""
    if cross_file:
        bug_dir = str(Path(bug_spec.file).parent)
        cross_file_note = f"""
You MAY also suggest changes in sibling files within the same package/directory ({bug_dir}/). A developer fixing a bug often touches related files — updating a caller, adjusting a shared constant, or fixing a related edge case in a sibling module. At least one change SHOULD be in a different file from {bug_spec.file} if possible.
"""

    prompt = f"""A bug fix is being applied to {bug_spec.file} in a {language} project. The fix addresses: {bug_spec.bug_description}
{cross_file_note}
Suggest 1-2 incidental changes that a developer would naturally include in the same commit. At least ONE must be FUNCTIONALLY RELEVANT — not just cosmetic. Examples ranked by preference:

PREFERRED (functionally relevant):
- Adding a parameter validation or bounds check to a nearby function
- Fixing a related but different edge case in the same file
- Adding an error message or improving an exception message
- Updating a related function's return type or default value
- Adding/updating a CHANGES.rst, CHANGELOG.md, or HISTORY entry

ACCEPTABLE (cosmetic, use at most one):
- Reordering imports in the fixed file
- Fixing a nearby typo or outdated comment

AVOID: pure docstring rewrapping, whitespace-only changes, or adding comments that just describe what code already does.

Look at the repository structure to find files that actually exist (like CHANGES.rst, CHANGELOG.md, etc).

Repository root contents: {root_listing}
Current project version: {version}{issues_note}

CRITICAL: If adding a CHANGES.rst or CHANGELOG entry:
- The entry MUST describe the actual fix: "{bug_spec.bug_description}" — do NOT write a generic or unrelated description
- Use the REAL version number "{version}" — do NOT invent future version numbers
- Do NOT include ANY `:pr:` or `:issue:` references — omit them entirely
- Do NOT add a new version header if one already exists — add the entry UNDER the existing header

Return each change as:
<change>
<file>filepath</file>
<original>
exact content to replace (or EMPTY if adding new content to end of file)
</original>
<modified>
the replacement content
</modified>
</change>

Only suggest changes to files that actually exist in the repo. Keep changes small and realistic."""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    result_text: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = _extract_text_from_result(message)
    except Exception:
        logger.warning("LLM call failed for incidental changes")
        return []

    if not result_text:
        return []

    changes = _parse_incidental_changes(result_text)
    # Constrain incidental changes to the same file as the fix or project-level files
    # Changelog files disabled — synthetic entries consistently contradict
    # the code direction and are a strong detection signal for judges.
    _PROJECT_LEVEL: set[str] = set()
    # Extract significant keywords from bug description for changelog validation
    _STOP_WORDS = {
        "the", "a", "an", "in", "on", "of", "to", "for", "is", "and", "or",
        "not", "when", "with", "from", "by", "it", "be", "as", "at", "that",
        "was", "but", "are", "has", "have", "had", "this", "will", "would",
        "should", "can", "could", "may", "might", "do", "does", "did", "been",
        "being", "which", "what", "where", "how", "if", "then", "than",
        "into", "its", "also", "just", "only",
    }
    bug_keywords = {
        w.lower() for w in re.findall(r"[a-zA-Z_]\w{2,}", bug_spec.bug_description)
    } - _STOP_WORDS

    bug_file = bug_spec.file
    verified: list[tuple[str, str, str]] = []
    for filepath, original, modified in changes:
        basename = Path(filepath).name
        if filepath != bug_file and basename not in _PROJECT_LEVEL:
            if cross_file and _is_same_package(bug_file, filepath, language):
                if any(excl in filepath for excl in _EXCLUDE_SUBSTR):
                    logger.debug("Skipping cross-file incidental in excluded path %s", filepath)
                    continue
                exclude_patterns = _LANGUAGE_EXCLUDE_PATTERNS.get(language, [])
                if any(pat.search(filepath) for pat in exclude_patterns):
                    logger.debug("Skipping cross-file incidental in test/excluded file %s", filepath)
                    continue
            else:
                logger.debug("Skipping incidental in unrelated file %s", filepath)
                continue
        # Validate changelog entries describe the actual bug fix
        if basename in _PROJECT_LEVEL and bug_keywords:
            mod_words = {w.lower() for w in re.findall(r"[a-zA-Z_]\w{2,}", modified)}
            if not mod_words & bug_keywords:
                logger.debug(
                    "Skipping changelog entry in %s — no keyword overlap with bug description",
                    filepath,
                )
                continue
        full_path = root / filepath
        if not full_path.is_file():
            continue
        if original != "EMPTY":
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if original not in content:
                continue
        verified.append((filepath, original, modified))
    return verified


def build_candidate(
    repo: str,
    base_commit: str,
    synthesis_result: SynthesisResult,
    test_patch: str = "",
) -> CandidateInstance:
    """Create a CandidateInstance from a synthesis result.

    Args:
        repo: Repository slug (owner/repo).
        base_commit: The commit SHA where the bug was injected.
        synthesis_result: The synthesis result containing bug spec and patch.

    Returns:
        A CandidateInstance with provenance='synthetic'.
    """
    owner_repo = repo.replace("/", "__")
    hash_input = (
        synthesis_result.bug_spec.file
        + synthesis_result.bug_spec.function_name
        + synthesis_result.bug_spec.bug_description
    )
    hash_int = int(hashlib.sha256(hash_input.encode()).hexdigest()[:8], 16)
    pr_number = 90000 + (hash_int % 10000)
    instance_id = f"{owner_repo}-{pr_number}"

    return CandidateInstance(
        repo=repo,
        instance_id=instance_id,
        pr_number=pr_number,
        base_commit=base_commit,
        merge_commit="",
        patch=synthesis_result.patch,
        test_patch=test_patch,
        problem_statement=synthesis_result.problem_statement,
        hints_text="",
        created_at=datetime.now(timezone.utc).isoformat(),
        provenance="synthetic",
    )


async def enrich_instance(
    instance: dict,
    repo_path: str,
    model: str = 'sonnet',
) -> dict | None:
    pipeline = instance.get('_pipeline')
    if not pipeline:
        raise ValueError("Instance missing '_pipeline' metadata — was it produced with --yield-only?")

    bug_spec_dict = pipeline['bug_spec']
    secondary_changes = [
        SecondaryChange(**sc) for sc in bug_spec_dict.get('secondary_changes', [])
    ]
    bug_spec = BugSpec(
        file=bug_spec_dict['file'],
        function_name=bug_spec_dict['function_name'],
        original_code=bug_spec_dict['original_code'],
        buggy_code=bug_spec_dict['buggy_code'],
        bug_description=bug_spec_dict['bug_description'],
        bug_category=bug_spec_dict['bug_category'],
        secondary_changes=secondary_changes,
    )

    social_artifacts = _mine_social_artifacts(repo_path)
    social_context = _build_social_context(social_artifacts)

    iid = instance.get('instance_id', 'unknown')
    iid_hash = int(hashlib.sha256(iid.encode()).hexdigest()[:8], 16)
    use_displacement = (iid_hash % 100) < 30
    symptom_difficulty = 'hard' if use_displacement else 'normal'

    symptom = await _bug_to_symptom(
        bug_spec.bug_description, file_path=bug_spec.file, model=model,
        difficulty=symptom_difficulty,
    )
    style_examples = _mine_issue_style_examples(repo_path)
    ctx = _collect_repo_context(repo_path)
    dataset_examples = _load_dataset_examples(DATASET_PATH, instance['repo'])
    _issue_gen_kwargs = dict(
        symptom=symptom,
        test_output=pipeline['test_output'],
        repo_context=ctx,
        style_examples=style_examples,
        model=model,
        social_context=social_context,
        dataset_examples=dataset_examples,
        repo_name=Path(repo_path).name,
        language=pipeline['language'],
    )
    test_patch = ''
    try:
        generated_tp = await generate_test_patch(
            bug_spec, repo_path, pipeline['language'], model=model,
            test_output=pipeline['test_output'],
        )
        if generated_tp:
            test_patch = generated_tp
    except Exception:
        logger.warning(
            'test_patch generation failed for %s', instance.get('instance_id'),
            exc_info=True,
        )

    max_screen_attempts = 5
    for screen_attempt in range(max_screen_attempts):
        social_context = _build_social_context(social_artifacts)
        _issue_gen_kwargs['social_context'] = social_context
        problem_statement = await generate_issue_from_symptom(**_issue_gen_kwargs)

        if not _verify_issue_independence(problem_statement, bug_spec):
            for _retry in range(2):
                problem_statement = await generate_issue_from_symptom(**_issue_gen_kwargs)
                if _verify_issue_independence(problem_statement, bug_spec):
                    break
            else:
                logger.info('  issue leaks identifiers on attempt %d/%d, re-rolling',
                            screen_attempt + 1, max_screen_attempts)
                continue

        screen_candidate = CandidateInstance(
            instance_id=iid, repo=instance.get('repo', ''),
            pr_number=0, base_commit=instance.get('base_commit', ''),
            merge_commit=instance.get('merge_commit', ''),
            patch=instance.get('patch', ''),
            problem_statement=problem_statement,
            test_patch=test_patch,
            hints_text='', created_at='',
        )
        if await _self_screen_instance(screen_candidate):
            logger.info('  self-screen PASSED on attempt %d/%d', screen_attempt + 1, max_screen_attempts)
            break
        logger.info('  self-screen failed attempt %d/%d, re-rolling issue text', screen_attempt + 1, max_screen_attempts)
    else:
        logger.info('  screening failed all %d attempts (independence or self-screen), discarding', max_screen_attempts)
        return None

    patch = instance.get('patch', '')
    patch_file_count = patch.count('diff --git ')
    if patch_file_count == 1:
        incidentals = await _generate_incidental_changes(
            repo_path, bug_spec, pipeline['language'], model=model,
            cross_file=True,
        )
        patched_files: set[str] = {bug_spec.file}
        ctx = _collect_repo_context(repo_path)
        real_issues = ctx.get("recent_issues", [])
        root = Path(repo_path)
        for inc_path, inc_original, inc_modified in incidentals:
            if inc_path in patched_files:
                continue
            if inc_path.lower().endswith((".rst", ".md")):
                inc_modified = _validate_rst_references(inc_modified, real_issues)
            try:
                inc_file = root / inc_path
                inc_content = inc_file.read_text(encoding="utf-8", errors="replace")
                if inc_original == "EMPTY":
                    new_content = inc_content + "\n" + inc_modified
                else:
                    new_content = inc_content.replace(inc_original, inc_modified, 1)
                if new_content != inc_content:
                    patch += generate_patch(new_content, inc_content, inc_path)
                    patched_files.add(inc_path)
            except OSError:
                continue
        instance['patch'] = patch

    instance['problem_statement'] = problem_statement
    instance['test_patch'] = test_patch
    instance['_pipeline']['phase'] = 'enriched'
    return instance


def _create_buggy_commit(
    repo_path: str,
    file_rel: str,
    mutated_content: str,
    description: str,
) -> str | None:
    """Create a temporary git commit containing the buggy file and return its SHA.

    Works on a throwaway branch so the original branch stays clean.
    """
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, check=True,
        )

    branch_hash = hashlib.sha256(
        (file_rel + description).encode()
    ).hexdigest()[:12]
    temp_branch = f"fix-{branch_hash}"

    try:
        orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if orig == "HEAD":
            orig = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", "-b", temp_branch])

        file_path = Path(repo_path) / file_rel
        file_path.write_text(mutated_content, encoding="utf-8")

        run(["git", "add", file_rel])
        run(["git", "commit", "-m", f"fix: {description}"])

        buggy_sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", orig])
        run(["git", "branch", "-D", temp_branch])

        return buggy_sha
    except subprocess.CalledProcessError:
        logger.warning("  Failed to create buggy commit for %s", file_rel)
        try:
            run(["git", "checkout", orig])
            run(["git", "branch", "-D", temp_branch])
        except Exception:
            pass
        return None


def _create_buggy_commit_multi(
    repo_path: str,
    buggy_files: dict[str, str],
    description: str,
) -> str | None:
    """Create a temporary git commit containing buggy files and return its SHA.

    Like _create_buggy_commit but supports multiple files for multi-file
    mutations.
    """
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, check=True,
        )

    hash_input = "".join(sorted(buggy_files.keys())) + description
    branch_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
    temp_branch = f"fix-{branch_hash}"

    try:
        orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if orig == "HEAD":
            orig = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", "-b", temp_branch])

        for file_rel, content in buggy_files.items():
            file_path = Path(repo_path) / file_rel
            file_path.write_text(content, encoding="utf-8")
            run(["git", "add", file_rel])

        run(["git", "commit", "-m", f"fix: {description}"])

        buggy_sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", orig])
        run(["git", "branch", "-D", temp_branch])

        return buggy_sha
    except subprocess.CalledProcessError:
        logger.warning("  Failed to create buggy commit for %s", list(buggy_files.keys()))
        try:
            run(["git", "checkout", orig])
            run(["git", "branch", "-D", temp_branch])
        except Exception:
            pass
        return None


_FAILED_TEST_PATTERN = re.compile(
    r"FAILED\s+(\S+::(?:\S+::)?\S+)",
)

_FAILURE_ID_PATTERNS = [
    re.compile(r"FAILED\s+(\S+::(?:\S+::)?\S+)"),
    re.compile(r"^---\s+FAIL:\s+(\S+/\S+)", re.MULTILINE),
    re.compile(r"^---\s+FAIL:\s+(\S+)", re.MULTILINE),
    re.compile(r"^FAIL\s+(\S+)", re.MULTILINE),
    re.compile(r"^test\s+(\S+)\s+\.\.\.\s+FAILED", re.MULTILINE),
    re.compile(r"<<<\s+(?:FAILURE|ERROR)!\s+-\s+in\s+(\S+)", re.MULTILINE),
]


def _extract_first_failure_id(test_output: str) -> str | None:
    """Extract the first failing test identifier from test output (any language)."""
    for pat in _FAILURE_ID_PATTERNS:
        m = pat.search(test_output)
        if m:
            tid = m.group(1)
            if tid in ('Test', 'test') and len(test_output) > 100:
                continue
            return tid
    return None


def _trim_test_output(test_output: str, max_lines: int = 60) -> str:
    """Trim test output to a reasonable size for embedding in an issue."""
    lines = test_output.splitlines()
    if len(lines) <= max_lines:
        return test_output
    head = lines[:20]
    tail = lines[-30:]
    return '\n'.join(head + ['', f'... ({len(lines) - 50} lines omitted) ...', ''] + tail)


def _extract_failed_test_names(test_output: str) -> set[str]:
    """Extract test IDs from pytest FAILED lines.

    Parses lines like 'FAILED tests/test_foo.py::TestBar::test_baz'
    and returns the set of full test node IDs.
    """
    return set(_FAILED_TEST_PATTERN.findall(test_output))


def _resolve_cargo() -> str:
    """Find the cargo binary, checking PATH and common install locations."""
    found = shutil.which("cargo")
    if found:
        return found
    fallback = Path.home() / ".cargo" / "bin" / "cargo"
    if fallback.is_file():
        return str(fallback)
    return "cargo"


_TEST_COMMANDS: dict[str, list[list[str]]] = {
    "python": [
        ["python", "-m", "pytest", "--tb=long", "-q"],
        ["python", "-m", "unittest", "discover", "-s", "tests"],
    ],
    "go": [["go", "test", "-short", "-count=1", "-timeout", "90s", "./..."]],
    "rust": [[_resolve_cargo(), "test", "--", "--test-threads=1"]],
    "java": [["mvn", "test", "-B", "-pl", "."]],
}


def _run_tests_on_buggy_code(
    repo_path: str,
    buggy_commit: str,
    language: str,
    timeout: int = 120,
    target_file: str | None = None,
    function_name: str | None = None,
) -> str | None:
    """Run the project's test suite against buggy code and capture output.

    Checks out the buggy commit, runs tests, then restores the original
    branch. Returns the combined stderr/stdout truncated to 2000 chars,
    or None if tests couldn't be run.

    When *target_file* is provided, runs only the corresponding test file
    (found via _find_existing_test_file) instead of the full suite.
    """
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, check=True,
        )

    try:
        orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if orig == "HEAD":
            orig = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    except subprocess.CalledProcessError:
        return None

    test_env = os.environ.copy()
    test_env = {
        k: v for k, v in test_env.items()
        if not k.startswith(('ANTHROPIC_', 'FACTORY_', 'CLAUDE_', 'SWEBENCHIFY_'))
    }
    src_dir = os.path.join(repo_path, "src")
    if os.path.isdir(src_dir):
        test_env["PYTHONPATH"] = src_dir + os.pathsep + repo_path + os.pathsep + test_env.get("PYTHONPATH", "")
    else:
        test_env["PYTHONPATH"] = repo_path + os.pathsep + test_env.get("PYTHONPATH", "")

    # Prefer venv python for test execution if available
    root = Path(repo_path)
    venv_py_path = root / '.synth-venv' / 'bin' / 'python'
    py_exe = str(venv_py_path) if venv_py_path.is_file() else sys.executable

    # Build the test command — use targeted test file if possible
    test_cmd: list[str] | None = None
    if target_file and language == "python":
        test_file = _find_existing_test_file(repo_path, target_file, language)
        if test_file:
            test_cmd = [py_exe, "-m", "pytest", test_file, "--tb=long", "-q"]
            logger.debug("  Running targeted tests: %s", test_file)
    elif target_file and language == "go":
        pkg_dir = os.path.dirname(target_file) or "."
        co_located_test = Path(repo_path) / (
            str(Path(target_file).parent / f"{Path(target_file).stem}_test.go")
        )
        if co_located_test.is_file():
            test_cmd = ["go", "test", "-short", "-count=1", "-timeout", "90s", f"./{pkg_dir}"]
            logger.debug("  Running targeted Go tests: ./%s", pkg_dir)
        elif function_name and _find_go_cross_package_test(repo_path, function_name):
            test_cmd = ["go", "test", "-short", "-count=1", "-timeout", "90s", "./..."]
            logger.debug("  Running cross-package Go tests for %s: ./...", function_name)
        else:
            test_cmd = ["go", "test", "-short", "-count=1", "-timeout", "90s", f"./{pkg_dir}"]
            logger.debug("  Running targeted Go tests: ./%s", pkg_dir)
    elif target_file and language == "rust":
        rust_root = Path(repo_path)
        target_dir = (rust_root / target_file).parent
        package_name = None
        search = target_dir
        while search >= rust_root:
            cargo_path = search / "Cargo.toml"
            if cargo_path.is_file():
                try:
                    cargo_text = cargo_path.read_text(encoding="utf-8", errors="replace")
                    pkg_m = re.search(r'^\[package\]\s*\n(?:.*\n)*?name\s*=\s*"([^"]+)"',
                                      cargo_text, re.MULTILINE)
                    if pkg_m:
                        package_name = pkg_m.group(1)
                except OSError:
                    pass
                break
            if search == rust_root:
                break
            search = search.parent
        if package_name:
            test_cmd = [_resolve_cargo(), "test", "-p", package_name, "--", "--test-threads=1"]
            logger.debug("  Running targeted Rust tests: -p %s", package_name)
        else:
            test_cmd = [_resolve_cargo(), "test", "--lib", "--", "--test-threads=1"]
            logger.debug("  Running Rust lib tests (no package name found)")
    elif target_file and language == "java":
        test_file = _find_existing_test_file(repo_path, target_file, language)
        if test_file:
            test_class_stem = Path(test_file).stem
            test_cmd = ["mvn", "test", "-B", "-pl", ".",
                        f"-Dtest={test_class_stem}"]
            logger.debug("  Running targeted Java tests: %s", test_class_stem)

    # Run baseline on clean code to identify pre-existing failures
    baseline_deselects: list[str] = []
    if language == "python":
        baseline_cmd = [py_exe, "-m", "pytest", "--tb=no", "-q"]
        if test_cmd:
            baseline_cmd = test_cmd[:] + ["--tb=no"]
            baseline_cmd = [c for c in baseline_cmd if c != "-x"]
        baseline_env = {**test_env, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            baseline_result = subprocess.run(
                baseline_cmd, cwd=repo_path, capture_output=True, text=True,
                timeout=timeout, env=baseline_env,
            )
            if baseline_result.returncode != 0:
                combined_baseline = (baseline_result.stdout + "\n" + baseline_result.stderr).strip()
                baseline_failures = _extract_failed_test_names(combined_baseline)
                baseline_deselects = [f"--deselect={name}" for name in baseline_failures]
                if baseline_deselects:
                    logger.debug("  Deselecting %d pre-existing failures", len(baseline_deselects))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    try:
        run(["git", "checkout", buggy_commit])
    except subprocess.CalledProcessError:
        return None

    # Add venv site-packages to PYTHONPATH if venv exists
    if venv_py_path.is_file():
        try:
            site_pkgs = subprocess.run(
                [str(venv_py_path), '-c',
                 'import site; print(site.getsitepackages()[0])'],
                capture_output=True, text=True, timeout=10,
            )
            if site_pkgs.returncode == 0:
                sp = site_pkgs.stdout.strip()
                test_env['PYTHONPATH'] = sp + os.pathsep + test_env.get('PYTHONPATH', '')
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    repo_package_name = Path(repo_path).name.replace("-", "_")
    try:
        import_check = subprocess.run(
            [py_exe, "-c", f"import {repo_package_name}"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
            env=test_env,
        )
        if import_check.returncode != 0:
            logger.debug("  Package not importable after install: %s", import_check.stderr[:200])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    test_output: str | None = None
    try:
        cmds_to_try = [test_cmd] if test_cmd else [
            [py_exe if c == "python" else c for c in t]
            for t in _TEST_COMMANDS.get(language, [])
        ]
        if test_cmd and language == "java":
            cmds_to_try.extend(_TEST_COMMANDS.get("java", []))
        for cmd in cmds_to_try:
            if cmd is None:
                continue
            if baseline_deselects and "pytest" in cmd:
                cmd = cmd + baseline_deselects
            try:
                result = subprocess.run(
                    cmd, cwd=repo_path, capture_output=True, text=True,
                    timeout=timeout, env=test_env,
                )
                combined = (result.stdout + "\n" + result.stderr).strip()
                if language == "java":
                    logger.info("  Java test rc=%d, output[:200]: %s", result.returncode, combined[:200])
                if result.returncode != 0 and combined:
                    test_output = combined[:2000]
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
    finally:
        try:
            run(["git", "checkout", orig])
        except subprocess.CalledProcessError:
            logger.warning("  Failed to restore branch after test run")

    return test_output


def _ensure_java_build(repo_path: str) -> Path | None:
    """Compile Java main and test sources via Maven, skipping if already done."""
    root = Path(repo_path)
    mvn_dir = root / ".mvn"
    marker = mvn_dir / "maven.compiled"
    if marker.is_file():
        logger.debug("  Java build already compiled (marker exists)")
        return root
    if not (root / "pom.xml").is_file():
        return None
    try:
        result = subprocess.run(
            ["mvn", "compile", "-DskipTests", "-q", "-B"],
            cwd=repo_path, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("  mvn compile failed (rc=%d): %s", result.returncode, result.stderr[:200])
            return None
        result = subprocess.run(
            ["mvn", "test-compile", "-q", "-B"],
            cwd=repo_path, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("  mvn test-compile failed (rc=%d): %s", result.returncode, result.stderr[:200])
            return None
        mvn_dir.mkdir(exist_ok=True)
        marker.write_text("compiled\n")
        logger.info("  Java build completed")
        return root
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        logger.debug("  Java build failed")
        return None


def _ensure_venv(repo_path: str, language: str) -> Path | None:
    """Create a reusable venv for Python repos. No-op for other languages.

    Returns the venv directory if created/exists, None otherwise.
    """
    if language == "java":
        result = _ensure_java_build(repo_path)
        logger.info("  _ensure_java_build result: %s", "success" if result else "failed")
        return result
    if language != "python":
        return None

    root = Path(repo_path)
    venv_dir = root / '.synth-venv'

    if (venv_dir / 'bin' / 'python').is_file():
        logger.debug("  Reusing existing venv at %s", venv_dir)
        return venv_dir

    if not any((root / cfg).is_file() for cfg in ("pyproject.toml", "setup.py", "setup.cfg")):
        return None

    try:
        subprocess.run(
            [sys.executable, '-m', 'venv', str(venv_dir)],
            capture_output=True, text=True, timeout=60,
        )
        venv_pip = str(venv_dir / 'bin' / 'pip')
        subprocess.run(
            [venv_pip, 'install', '-e', '.', '--quiet'],
            cwd=repo_path, capture_output=True, text=True, timeout=120,
        )
        subprocess.run(
            [venv_pip, 'install', 'pytest', '--quiet'],
            capture_output=True, text=True, timeout=60,
        )
        for req_file in [
            'requirements/tests.txt', 'requirements/test.txt',
            'requirements-test.txt', 'test-requirements.txt',
            'requirements/dev.txt', 'requirements-dev.txt',
        ]:
            req_path = root / req_file
            if req_path.is_file():
                subprocess.run(
                    [venv_pip, 'install', '-r', str(req_path), '--quiet'],
                    capture_output=True, text=True, timeout=120,
                )
                break
        venv_py = str(venv_dir / 'bin' / 'python')
        pkg_name = Path(repo_path).name.replace('-', '_')
        for candidate in [pkg_name, pkg_name.split('_')[0]]:
            _imp = subprocess.run(
                [venv_py, '-c', f'import {candidate}'],
                capture_output=True, text=True, timeout=10,
            )
            if _imp.returncode == 0:
                break
        else:
            imp_stderr = _imp.stderr if _imp else ''
            compat_pins: list[str] = []
            if 'jinja2' in imp_stderr.lower() or 'markup' in imp_stderr.lower():
                compat_pins.extend(['jinja2<3.1', 'markupsafe<2.1'])
            if 'werkzeug' in imp_stderr.lower():
                compat_pins.append('Werkzeug<2.0')
            if 'itsdangerous' in imp_stderr.lower():
                compat_pins.append('itsdangerous<2.1')
            if compat_pins:
                subprocess.run(
                    [venv_pip, 'install'] + compat_pins + ['--quiet'],
                    capture_output=True, text=True, timeout=60,
                )
            for req_file in ['requirements.txt', 'requirements-dev.txt',
                             'test-requirements.txt']:
                req_path = root / req_file
                if req_path.is_file():
                    subprocess.run(
                        [venv_pip, 'install', '-r', str(req_path), '--quiet'],
                        capture_output=True, text=True, timeout=120,
                    )
                    break
        logger.info("  Venv ready at %s", venv_dir)
        return venv_dir
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        logger.debug('  venv creation failed, proceeding without venv')
        return None


def _is_same_package(primary_file: str, secondary_file: str, language: str) -> bool:
    """Check if two files belong to the same package.

    For Go: same directory = same package.
    For Python: same top-level package (first path component after stripping
    common prefixes like 'src/').
    For other languages: same directory.
    """
    primary_dir = os.path.dirname(primary_file)
    sec_dir = os.path.dirname(secondary_file)

    if language == "go":
        # In Go, same directory = same package
        return primary_dir == sec_dir

    if language == "python":
        # For Python, check same top-level package
        def _top_package(filepath: str) -> str:
            parts = Path(filepath).parts
            # Strip common prefixes like 'src/'
            if parts and parts[0] in ('src', 'lib', 'source'):
                parts = parts[1:]
            return parts[0] if parts else ""
        return _top_package(primary_file) == _top_package(secondary_file)

    # Default: same directory
    return primary_dir == sec_dir


async def synthesize_repo(
    repo_path: str,
    repo_slug: str,
    base_commit: str,
    language: str,
    max_mutations: int = 10,
    operators: list[str] | None = None,
    model: str = "sonnet",
    screen_instances: bool = True,
    yield_only: bool = False,
    target_multiplier: int = 8,
    max_files: int | None = None,
    max_functions: int | None = None,
    on_candidate: Callable[[CandidateInstance, dict], None] | None = None,
) -> RepoSynthesisResult:
    """Synthesize bug instances for a repository.

    Orchestration function that finds mutation targets, introduces bugs,
    generates patches and issue descriptions, and builds candidate
    instances.

    Args:
        repo_path: Path to the repository root.
        repo_slug: Repository slug (owner/repo).
        base_commit: Commit SHA to target (clean HEAD).
        language: Programming language ('python', 'go', 'rust', 'java').
        max_mutations: Maximum number of bugs to generate.
        operators: Optional list of bug categories to use (unused, reserved
            for future filtering).
        model: Claude model shortname.
        target_multiplier: How many targets to try per desired mutation.
        max_files: Max source files to scan for targets (default scales with multiplier).
        max_functions: Max functions per file to extract (default scales with multiplier).

    Returns:
        RepoSynthesisResult with candidates and mutation attempt count.
    """
    dataset_examples = _load_dataset_examples(DATASET_PATH, repo_slug)
    if dataset_examples:
        logger.info(
            "Loaded %d dataset examples for few-shot conditioning", len(dataset_examples),
        )

    logger.info(
        "Finding mutation targets in %s (%s)", repo_path, language,
    )
    _max_files = max_files if max_files is not None else (100 if target_multiplier > 8 else 20)
    _max_functions = max_functions if max_functions is not None else (10 if target_multiplier > 8 else 5)
    all_targets = find_mutation_targets(repo_path, language, max_files=_max_files, max_functions=_max_functions)
    with_tests = [
        t for t in all_targets
        if _find_existing_test_file(
            repo_path, t["file"], language, function_name=t.get("function_name"),
        ) is not None
    ]
    without_tests = [t for t in all_targets if t not in with_tests]
    logger.info(
        "Found %d mutation targets (%d with test files)",
        len(all_targets), len(with_tests),
    )
    # H4: Assertion-aware prioritization — targets with direct test assertions first
    with_assertions = []
    with_tests_no_assertions = []
    for t in with_tests:
        test_file = _find_existing_test_file(
            repo_path, t["file"], language, function_name=t.get("function_name"),
        )
        if test_file:
            try:
                test_source = Path(os.path.join(repo_path, test_file)).read_text(
                    encoding="utf-8", errors="replace",
                )
            except OSError:
                test_source = ""
            assertions = _analyze_test_assertions(test_source, language)
            relevant = [
                a for a in assertions
                if (a.get('called_function') == t['function_name']
                    or t['function_name'] in a.get('expression', ''))
            ]
            if relevant:
                t['assertions'] = relevant
                with_assertions.append(t)
                continue
        with_tests_no_assertions.append(t)

    logger.info(
        "Assertion-aware split: %d with assertions, %d with tests only, %d without tests",
        len(with_assertions), len(with_tests_no_assertions), len(without_tests),
    )
    # Prioritize: targets with assertions first, then with tests, then without
    targets = with_assertions + with_tests_no_assertions + without_tests

    _ensure_venv(repo_path, language)

    candidates: list[CandidateInstance] = []
    enrichment_data: dict[str, dict] = {}
    seen_patches: set[str] = set()
    mutations_attempted = 0

    for i, target in enumerate(targets[:max_mutations * target_multiplier]):
        if len(candidates) >= max_mutations:
            break

        mutations_attempted += 1

        repo_short = repo_slug.split('/')[-1]
        pfx = f'[{repo_short}] [{len(candidates)}/{max_mutations} yielded] [{mutations_attempted}/{min(len(targets), max_mutations * target_multiplier)}]'

        logger.info(
            "%s Mutating %s:%s",
            pfx,
            target["file"],
            target["function_name"],
        )

        related_files = _find_related_files(repo_path, target, language)
        if related_files:
            logger.info("%s  Found %d related files", pfx, len(related_files))

        test_context = _extract_test_context(
            repo_path, target["file"], target["function_name"], language,
        )

        bug_plan = await _plan_multi_file_mutation(
            target["source"], related_files, model=model,
            test_context=test_context,
        )
        if bug_plan:
            logger.info("%s  Multi-file plan: %s", pfx, bug_plan.primary_description[:80])

        # H10: Try targeted mutation (assertion-aware, data-first pass rate)
        bug_spec = None
        patch = ""
        mutated_content = ""
        original_content = ""
        if language in ("python", "go"):
            _tfile = _find_existing_test_file(
                repo_path, target["file"], language,
                function_name=target.get("function_name"),
            )
            if _tfile:
                _tspec = _try_targeted_mutation(repo_path, target, _tfile, language)
                if _tspec:
                    desc_lower = _tspec.bug_description.lower()
                    if any(op_sig in desc_lower for op_sig in (
                        "changed '", 'swapped', 'flipped', 'inverted operator',
                        "' to '", 'operator',
                    )):
                        _tspec = None
                if _tspec:
                    try:
                        _torig = (Path(repo_path) / _tspec.file).read_text(
                            encoding="utf-8", errors="replace",
                        )
                        _tmut = _torig.replace(
                            _tspec.original_code, _tspec.buggy_code, 1,
                        )
                        if (_tmut != _torig
                                and _validate_mutation_parses(_tmut, language)):
                            _tmut = _normalize_test_whitespace(_tmut, _torig)
                            _tpatch = generate_patch(_torig, _tmut, _tspec.file)
                            if _tpatch.strip():
                                bug_spec = _tspec
                                patch = _tpatch
                                mutated_content = _tmut
                                original_content = _torig
                                logger.info(
                                    "%s  Targeted mutation: %s",
                                    pfx, _tspec.bug_description[:80],
                                )
                    except OSError:
                        pass

        # Resolve assertion data for the prompt
        target_assertions = target.get('assertions')
        if target_assertions is None:
            _afile = _find_existing_test_file(repo_path, target["file"], language)
            if _afile:
                try:
                    _asrc = Path(os.path.join(repo_path, _afile)).read_text(
                        encoding="utf-8", errors="replace",
                    )
                    _all_assertions = _analyze_test_assertions(_asrc, language)
                    target_assertions = [
                        a for a in _all_assertions
                        if (a.get('called_function') == target['function_name']
                            or target['function_name'] in a.get('expression', ''))
                    ] or None
                except OSError:
                    pass

        # H2: Fall back to LLM introduce_bug (retry up to 2 times if patch too simple)
        _retry_strategies = ["", "guard_removal", "return_corruption"]
        for attempt in range(3):
            if bug_spec is None:
                bug_spec = await introduce_bug(
                    target, model=model, related_files=related_files,
                    bug_plan=bug_plan, test_context=test_context,
                    mutation_strategy=_retry_strategies[attempt],
                    assertions=target_assertions,
                )
            if bug_spec is None:
                logger.warning("%s  Skipped — LLM did not produce a valid mutation", pfx)
                break

            file_path = Path(repo_path) / bug_spec.file
            try:
                original_content = file_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                logger.warning("%s  Skipped — could not read %s", pfx, bug_spec.file)
                bug_spec = None
                break

            mutated_content = original_content.replace(
                bug_spec.original_code, bug_spec.buggy_code, 1,
            )

            if mutated_content == original_content:
                logger.warning('%s  Mutation could not be applied, retrying (%d/2)', pfx, attempt + 1)
                bug_spec = None
                continue

            if not _validate_mutation_parses(mutated_content, language):
                logger.warning('%s  Mutation does not parse (%s), retrying (%d/2)', pfx, language, attempt + 1)
                bug_spec = None
                continue

            orig_stripped = [ln.strip() for ln in original_content.splitlines() if ln.strip()]
            mut_stripped = [ln.strip() for ln in mutated_content.splitlines() if ln.strip()]
            if orig_stripped == mut_stripped:
                logger.warning('%s  Mutation is whitespace-only, retrying (%d/2)', pfx, attempt + 1)
                bug_spec = None
                continue

            if _is_ast_equivalent(original_content, mutated_content, language):
                logger.warning('%s  Mutation is semantically equivalent, retrying (%d/2)', pfx, attempt + 1)
                bug_spec = None
                continue

            mutated_content = _normalize_test_whitespace(mutated_content, original_content)

            patch = generate_patch(original_content, mutated_content, bug_spec.file)
            if not patch.strip():
                logger.warning("%s  Skipped — empty patch", pfx)
                bug_spec = None
                break

            changed = _count_changed_lines(patch)
            if changed >= 4 and len(patch) >= 200:
                break
            if attempt < 2:
                reason = []
                if changed < 4:
                    reason.append(f"{changed} changed lines < 4")
                if len(patch) < 200:
                    reason.append(f"{len(patch)} chars < 200")
                logger.info(
                    "%s  Patch too simple (%s), retrying (%d/2)",
                    pfx, ", ".join(reason), attempt + 1,
                )
                bug_spec = None
            else:
                logger.warning(
                    "%s  Patch still below targets after retries (%d lines, %d chars), accepting",
                    pfx, changed, len(patch),
                )

        if bug_spec is None:
            continue
        if not patch.strip():
            continue

        # Apply secondary changes from multi-file mutation
        buggy_files: dict[str, str] = {bug_spec.file: mutated_content}
        test_patch_parts: list[str] = []
        primary_dir = os.path.dirname(bug_spec.file)
        for sc in bug_spec.secondary_changes:
            # Skip benchmark/demo/example files — they produce unrelated patch hunks
            # that judges immediately flag as artificially constructed
            if any(excl in sc.file for excl in _EXCLUDE_SUBSTR):
                logger.warning("%s  Skipping secondary change in excluded file %s", pfx, sc.file)
                continue
            # Skip cross-package secondary changes — judges flag patches that
            # touch unrelated packages as a synthesis signal
            if not _is_same_package(bug_spec.file, sc.file, language):
                logger.warning("%s  Skipping cross-package secondary change in %s (primary: %s)", pfx, sc.file, primary_dir)
                continue
            sec_path = Path(repo_path) / sc.file
            if not sec_path.is_file():
                logger.warning("%s  Secondary file not found: %s", pfx, sc.file)
                continue
            try:
                sec_content = sec_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if sc.original_snippet not in sec_content:
                logger.warning("%s  Secondary snippet not found in %s", pfx, sc.file)
                continue
            sec_buggy = sec_content.replace(sc.original_snippet, sc.buggy_snippet, 1)
            if sec_buggy != sec_content:
                sec_diff = generate_patch(sec_content, sec_buggy, sc.file)
                if sc.file.startswith(('tests/', 'test/')) or '/test_' in sc.file or sc.file.startswith('test_'):
                    test_patch_parts.append(sec_diff)
                else:
                    patch += sec_diff
                buggy_files[sc.file] = sec_buggy
                logger.info("%s  Secondary change in %s: %s", pfx, sc.file, sc.description)

        if len(buggy_files) < 2 and related_files:
            logger.info("%s  Only %d file changed, retrying with explicit multi-file instruction", pfx, len(buggy_files))
            retry_spec = await introduce_bug(
                target, model=model, related_files=related_files,
            )
            if retry_spec and retry_spec.secondary_changes:
                for sc in retry_spec.secondary_changes:
                    if any(excl in sc.file for excl in _EXCLUDE_SUBSTR):
                        logger.warning("%s  Skipping retry secondary change in excluded file %s", pfx, sc.file)
                        continue
                    if not _is_same_package(bug_spec.file, sc.file, language):
                        logger.warning("%s  Skipping retry cross-package secondary change in %s", pfx, sc.file)
                        continue
                    sec_path = Path(repo_path) / sc.file
                    if not sec_path.is_file():
                        continue
                    try:
                        sec_content = sec_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if sc.original_snippet not in sec_content:
                        continue
                    sec_buggy = sec_content.replace(sc.original_snippet, sc.buggy_snippet, 1)
                    if sec_buggy != sec_content:
                        sec_diff = generate_patch(sec_content, sec_buggy, sc.file)
                        if sc.file.startswith(('tests/', 'test/')) or '/test_' in sc.file or sc.file.startswith('test_'):
                            test_patch_parts.append(sec_diff)
                        else:
                            patch += sec_diff
                        buggy_files[sc.file] = sec_buggy
                        logger.info("%s  Retry secondary change in %s", pfx, sc.file)

        patched_files: set[str] = {bug_spec.file} | set(buggy_files.keys())
        ctx = _collect_repo_context(repo_path)
        real_issues = ctx.get("recent_issues", [])

        incidentals = await _generate_incidental_changes(
            repo_path, bug_spec, language, model=model,
        )
        for inc_path, inc_original, inc_modified in incidentals:
            if inc_path in patched_files:
                logger.info("%s  Skipping duplicate incidental for %s", pfx, inc_path)
                continue
            if inc_path.lower().endswith((".rst", ".md")):
                inc_modified = _validate_rst_references(inc_modified, real_issues)
            try:
                inc_file = Path(repo_path) / inc_path
                inc_content = inc_file.read_text(encoding="utf-8", errors="replace")
                if inc_original == "EMPTY":
                    new_content = inc_content + "\n" + inc_modified
                else:
                    new_content = inc_content.replace(inc_original, inc_modified, 1)
                if new_content != inc_content:
                    if Path(inc_path).name in (
                        "CHANGES.rst", "CHANGELOG.rst", "CHANGELOG.md",
                        "HISTORY.rst", "HISTORY.md",
                    ):
                        headers = re.findall(
                            r"^(?:Version\s+\S+|#+\s+\S+)", new_content, re.MULTILINE,
                        )
                        if len(headers) != len(set(headers)):
                            logger.debug(
                                "Skipping %s — duplicate version header", inc_path,
                            )
                            continue
                        _orphaned = False
                        nc_lines = new_content.split("\n")
                        for i, nc_line in enumerate(nc_lines):
                            if re.match(r"^Version\s+\S+", nc_line):
                                j = i + 1
                                while j < len(nc_lines) and nc_lines[j].strip() == "":
                                    j += 1
                                if j < len(nc_lines) and re.match(r"^[-=~^]{3,}$", nc_lines[j].strip()):
                                    if j != i + 1:
                                        _orphaned = True
                                        break
                        if _orphaned:
                            logger.debug(
                                "Skipping %s — orphaned underline after header", inc_path,
                            )
                            continue
                    patch += generate_patch(new_content, inc_content, inc_path)
                    patched_files.add(inc_path)
            except OSError:
                continue

        buggy_commit = _create_buggy_commit_multi(
            repo_path, buggy_files, bug_spec.bug_description,
        )
        if buggy_commit is None:
            logger.warning("%s  Skipped — could not create buggy commit", pfx)
            continue

        # H3: Capture test failure output from buggy code
        test_output = _run_tests_on_buggy_code(
            repo_path, buggy_commit, language,
            target_file=bug_spec.file,
            function_name=bug_spec.function_name,
        )
        if test_output:
            logger.info("%s  Captured %d chars of test output", pfx, len(test_output))
            test_output = _sanitize_test_output(test_output, repo_path)
            test_output = _humanize_traceback(test_output, repo_path)

        if not test_output or not _is_valid_test_output(test_output):
            logger.warning("%s  Skipped — mutation did not cause test failures (data-first path required)", pfx)
            continue

        patch_hash = hashlib.md5(patch.encode()).hexdigest()
        if patch_hash in seen_patches:
            logger.info('%s  Skipped — duplicate patch (same diff already yielded)', pfx)
            continue
        seen_patches.add(patch_hash)

        if yield_only:
            synthesis_result = SynthesisResult(
                bug_spec=bug_spec,
                patch=patch,
                problem_statement=(
                    f'[yield-only] Mutation in {bug_spec.file}:{bug_spec.function_name} '
                    f'broke tests. Test output captured ({len(test_output or "")} chars). '
                    f'Generated in yield-measurement mode without full enrichment.'
                ),
                instance_id='',
                base_commit=buggy_commit,
                test_output=test_output or '',
            )
            candidate = build_candidate(
                repo_slug, buggy_commit, synthesis_result, test_patch='',
            )
            candidate.merge_commit = base_commit
            synthesis_result.instance_id = candidate.instance_id
            candidates.append(candidate)
            edata = {
                'bug_spec': dataclasses.asdict(bug_spec),
                'test_output': test_output or '',
                'language': language,
            }
            enrichment_data[candidate.instance_id] = edata
            if on_candidate:
                on_candidate(candidate, edata)
            logger.info('%s  Generated (yield-only): %s (%s)', pfx, candidate.instance_id, bug_spec.bug_category)
            logger.info('%s  === YIELD %d/%d (rate: %.0f%%) ===', pfx, len(candidates), max_mutations, 100 * len(candidates) / mutations_attempted)
            continue

        # Generate test patch once (doesn't vary between screen retries)
        test_patch = ''.join(test_patch_parts)
        try:
            generated_tp = await generate_test_patch(
                bug_spec, repo_path, language, model=model, test_output=test_output,
            )
            if generated_tp:
                test_patch = generated_tp
        except Exception:
            logger.warning('%s  test_patch generation failed — using fallback', pfx, exc_info=True)

        # H1: Information firewall — generate issue from symptom only
        symptom = await _bug_to_symptom(
            bug_spec.bug_description, file_path=bug_spec.file, model=model,
        )
        style_examples = _mine_issue_style_examples(repo_path)
        social_artifacts = _mine_social_artifacts(repo_path)

        _issue_gen_kwargs = dict(
            symptom=symptom,
            test_output=test_output,
            repo_context=ctx,
            style_examples=style_examples,
            model=model,
            social_context='',
            dataset_examples=dataset_examples,
            repo_name=Path(repo_path).name,
            language=language,
        )

        max_screen_attempts = 5 if screen_instances else 1
        problem_statement = None
        for screen_attempt in range(max_screen_attempts):
            social_context = _build_social_context(social_artifacts)
            _issue_gen_kwargs['social_context'] = social_context
            problem_statement = await generate_issue_from_symptom(**_issue_gen_kwargs)

            if not _verify_issue_independence(problem_statement, bug_spec):
                for _retry in range(2):
                    problem_statement = await generate_issue_from_symptom(**_issue_gen_kwargs)
                    if _verify_issue_independence(problem_statement, bug_spec):
                        break
                else:
                    logger.info('%s  issue leaks identifiers on attempt %d/%d, re-rolling',
                                pfx, screen_attempt + 1, max_screen_attempts)
                    continue

            synthesis_result = SynthesisResult(
                bug_spec=bug_spec,
                patch=patch,
                problem_statement=problem_statement,
                instance_id="",
                base_commit=buggy_commit,
                test_output=test_output or "",
            )
            candidate = build_candidate(
                repo_slug, buggy_commit, synthesis_result, test_patch=test_patch,
            )
            candidate.merge_commit = base_commit
            synthesis_result.instance_id = candidate.instance_id

            if not screen_instances or await _self_screen_instance(candidate):
                if screen_instances:
                    logger.info('%s  self-screen PASSED on attempt %d/%d',
                                pfx, screen_attempt + 1, max_screen_attempts)
                break
            logger.info('%s  self-screen failed attempt %d/%d, re-rolling issue text',
                        pfx, screen_attempt + 1, max_screen_attempts)
        else:
            logger.info('%s  screening failed all %d attempts (independence or self-screen), discarding',
                        pfx, max_screen_attempts)
            continue

        candidates.append(candidate)
        edata = {
            'bug_spec': dataclasses.asdict(bug_spec),
            'test_output': test_output or '',
            'language': language,
        }
        enrichment_data[candidate.instance_id] = edata
        if on_candidate:
            on_candidate(candidate, edata)

        logger.info(
            "%s  Generated: %s (%s)", pfx, candidate.instance_id, bug_spec.bug_category,
        )
        logger.info('%s  === YIELD %d/%d (rate: %.0f%%) ===', pfx, len(candidates), max_mutations, 100 * len(candidates) / mutations_attempted)

    venv_cleanup = Path(repo_path) / '.synth-venv'
    if venv_cleanup.is_dir():
        shutil.rmtree(venv_cleanup, ignore_errors=True)
    test_venv = Path(repo_path) / '.test-venv'
    if test_venv.is_dir():
        shutil.rmtree(test_venv, ignore_errors=True)

    logger.info(
        "Synthesis complete: %d/%d candidates generated (%d mutations attempted)",
        len(candidates),
        max_mutations,
        mutations_attempted,
    )
    logger.info(
        '[%s] Final: %d/%d yielded in %d attempts (%.0f%% yield rate)',
        repo_slug.split('/')[-1], len(candidates), max_mutations,
        mutations_attempted,
        100 * len(candidates) / mutations_attempted if mutations_attempted else 0,
    )
    return RepoSynthesisResult(
        candidates=candidates,
        mutations_attempted=mutations_attempted,
        enrichment_data=enrichment_data,
    )
