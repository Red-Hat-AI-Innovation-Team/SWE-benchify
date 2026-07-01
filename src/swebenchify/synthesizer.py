"""LLM-based synthetic bug generation for SWE-bench instances.

Uses Claude to introduce realistic bugs into source code, generate gold
fix patches, and produce corresponding issue reports. Language-agnostic:
works across Python, Go, Rust, and Java using simple text-based function
detection (not AST parsing).
"""

from __future__ import annotations

import ast
import dataclasses
import difflib
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from claude_code_sdk import ClaudeCodeOptions, ResultMessage, query
except ModuleNotFoundError:  # allow import for tests without the SDK installed
    ClaudeCodeOptions = None  # type: ignore[assignment,misc]
    ResultMessage = None  # type: ignore[assignment,misc]
    query = None  # type: ignore[assignment]

from swebenchify.models import CandidateInstance

logger = logging.getLogger(__name__)

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
}

_LANGUAGE_EXCLUDE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"(^|/)tests?/"),
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
    """Load real issue examples from the SWE-benchify dataset JSONL file.

    Filters to instances matching the target repo_slug and randomly
    samples n problem_statement texts.
    """
    try:
        path = Path(dataset_path)
        if not path.is_file():
            return []
        matching: list[str] = []
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
        if not matching:
            return []
        return random.sample(matching, min(n, len(matching)))
    except OSError:
        return []


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


def _extract_go_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract function bodies from Go source using brace counting."""
    functions: list[dict[str, str | int]] = []
    pat = _FUNC_PATTERNS["go"]
    i = 0
    while i < len(lines):
        m = pat.match(lines[i])
        if m:
            name = m.group("name")
            start = i
            brace_count = 0
            found_open = False
            while i < len(lines):
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                i += 1
                if found_open and brace_count == 0:
                    break
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


def _extract_rust_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract function bodies from Rust source using brace counting."""
    functions: list[dict[str, str | int]] = []
    pat = _FUNC_PATTERNS["rust"]
    i = 0
    while i < len(lines):
        m = pat.match(lines[i])
        if m:
            name = m.group("name")
            start = i
            brace_count = 0
            found_open = False
            while i < len(lines):
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                i += 1
                if found_open and brace_count == 0:
                    break
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


def _extract_java_functions(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract method bodies from Java source using brace counting."""
    functions: list[dict[str, str | int]] = []
    pat = _FUNC_PATTERNS["java"]
    i = 0
    while i < len(lines):
        m = pat.match(lines[i])
        if m:
            name = m.group("name")
            start = i
            brace_count = 0
            found_open = False
            while i < len(lines):
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                i += 1
                if found_open and brace_count == 0:
                    break
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

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
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

            for func in functions[:max_functions]:
                source_lines = func["source"].strip().splitlines()
                if len(source_lines) < 8:
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
            line_num = int(parts[1]) - 1
            _add_file_snippet(rel_path, line_num)

    return related


async def _plan_multi_file_mutation(
    target_func_code: str,
    related_files: list[dict[str, str]],
    model: str = "sonnet",
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

Plan a coordinated bug. Return your plan in this format:

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

    # Replace macOS /Users/<username>/... paths with neutral /home/user/...
    result = re.sub(r"/Users/[^/\s]+/", "/home/user/", result)

    # Neutralize synth-related tmp paths
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]*synth-test[a-zA-Z0-9_-]*/", "/tmp/test-env/", result)
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]*synth[a-zA-Z0-9_-]*/", "/tmp/test-env/", result)

    # Strip remote-factory and .factory-worktrees paths
    result = re.sub(r"[^\s]*remote-factory[^\s]*/", "/home/user/project/", result)
    result = re.sub(r"[^\s]*\.factory-worktrees/[^\s/]+/", "/home/user/project/", result)

    # Strip cachedir lines with synth/factory paths
    result = re.sub(r"cachedir:.*(?:synth|factory).*\n?", "", result)

    return result


def _humanize_traceback(test_output: str, repo_path: str) -> str:
    """Transform raw test output paths to look like a user's environment."""
    if not test_output:
        return ""

    repo_name = Path(repo_path).name
    username = random.choice(_FAKE_USERNAMES)
    home_path = f"/home/{username}/projects/{repo_name}/"

    result = test_output
    result = re.sub(r"/tmp/[a-zA-Z0-9_-]+/", home_path, result)
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
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
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
) -> BugSpec | None:
    """Use Claude to introduce a realistic bug into a function.

    Args:
        target: Dict from find_mutation_targets with file, function_name,
            source, language keys.
        model: Claude model shortname ('sonnet', 'haiku', 'opus').
        related_files: Optional list of dicts with 'file' and 'snippet'
            for files that reference this function.

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

    prompt = f"""You are a code mutation expert. Given the following {language} function, introduce a subtle, realistic bug — the kind a developer might actually make during a refactoring or late-night coding session.

PREFERRED bug types (choose one):
- Type confusion: use a similar but wrong type (str where bytes expected, list where tuple needed, int where float, TextIO where BinaryIO)
- Wrong method: call a similar method on the same object (.items() vs .values(), .append() vs .extend(), .read() vs .readline())
- Incomplete refactoring: rename a variable in some places but not all, or update a function signature without updating all callers
- Wrong argument order: swap two arguments of the same type in a function call
- Stale reference: use an old variable name that was valid before a rename

AVOID these (too easy to detect as artificial):
- Simple condition inversions (> to <, True to False)
- Removing or commenting out a single line
- Changing a single character in a string literal
- Off-by-one errors in simple ranges

The bug must look like something that would happen during a real refactoring or API migration, not a deliberate sabotage.

CRITICAL CONSTRAINTS on bug subtlety:
- The bug MUST NOT break the function's basic contract. If the function adds two numbers, don't make it subtract — that would be caught immediately by any test.
- The bug should only manifest with specific inputs, edge cases, or unusual conditions. Think: boundary values, empty collections, negative numbers, Unicode strings, concurrent access, large inputs.
- The bug must be plausible as something that would survive a typical CI suite. If the existing test suite would trivially catch it, the bug is too obvious.
- Prefer bugs in error handling paths, edge case branches, or rarely-exercised code paths over bugs in the main happy path.

Here is the function:

```{language}
{source}
```
{related_context}
{bug_plan_context}

Return your response in EXACTLY this format:

<bug_category>category name here</bug_category>

<bug_description>One sentence describing what the bug does, under what conditions it manifests, and why existing tests wouldn't catch it</bug_description>

<buggy_code>
The COMPLETE modified function with ONLY the bug introduced. Include ALL lines of the original function. The bug should affect 2-3 related lines, not just one. Do NOT add incidental improvements (docstring fixes, variable renames, type hints) — only the bug mutation.
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
- The bug must be subtle — it should compile/parse correctly
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
    if not hasattr(message, "content") or not message.content:
        return None
    parts: list[str] = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts) if parts else None


def _count_changed_lines(patch: str) -> int:
    """Count the number of added/removed lines in a unified diff."""
    count = 0
    for line in patch.splitlines():
        if line.startswith(("---", "+++")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def _parse_bug_response(text: str, target: dict) -> BugSpec | None:
    """Parse LLM response to extract bug specification."""
    cat_match = re.search(
        r"<bug_category>\s*(.*?)\s*</bug_category>", text, re.DOTALL
    )
    desc_match = re.search(
        r"<bug_description>\s*(.*?)\s*</bug_description>", text, re.DOTALL
    )
    code_match = re.search(
        r"<buggy_code>\s*(.*?)\s*</buggy_code>", text, re.DOTALL
    )

    if not code_match:
        logger.warning("Could not parse buggy_code from LLM response")
        return None

    buggy_code = code_match.group(1).strip()
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

    category = cat_match.group(1).strip() if cat_match else "unknown"
    description = desc_match.group(1).strip() if desc_match else "Bug introduced in function"

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
    return "".join(diff)


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

    return artifacts


def _build_social_context(artifacts: dict[str, list[str]]) -> str:
    """Build social context string from mined artifacts."""
    return ''
    templates: list[str] = []

    if artifacts.get('shas'):
        sha = random.choice(artifacts['shas'])
        templates.append(f'cc {sha}')
    if artifacts.get('contributors'):
        contributor = random.choice(artifacts['contributors'])
        templates.append(f'cc @{contributor}')
    if artifacts.get('issues'):
        issue_num = random.choice(artifacts['issues'])
        templates.append(f'see also #{issue_num}')

    # Deduplicate to avoid template-like repetition
    templates = list(dict.fromkeys(templates))

    if not templates:
        return ""

    count = random.choices([0, 1], weights=[1, 3])[0]
    if count == 0:
        return ""

    selected = random.sample(templates, min(count, len(templates)))
    return "\n\n" + "\n".join(selected)


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


async def _bug_to_symptom(bug_description: str, file_path: str = '', model: str = "sonnet") -> str:
    """Convert a code-level bug description to a user-facing symptom.

    Strips technical details (operator names, variable names, condition
    specifics) and returns only what a user would observe.
    """
    file_context = ''
    if file_path:
        module = Path(file_path).stem
        file_context = f'\nThe bug is in the {module} module ({file_path}). The symptom MUST be about {module} functionality specifically.'

    prompt = f"""Convert this developer-level bug description into a user-facing symptom. Keep the FUNCTIONAL AREA (what part of the system is affected — e.g., "time duration handling", "CLI startup", "RST link parsing") but remove the specific code-level fix details (no operator names like `>=`, no variable names, no exact condition logic).

Bug description: {bug_description}
{file_context}

Return ONLY the symptom in one sentence. Examples:
- "split() instead of rsplit() in custom Sphinx role parser" → "RST documentation rendering breaks certain link syntax"
- "timedelta(minutes=value) should be timedelta(seconds=value)" → "time duration handling uses wrong units, causing timeouts or delays"
- "inverted boolean in error handler catches wrong exception type" → "error handling catches the wrong exception type, masking real errors"
- "off-by-one in loop causes missing last element" → "list processing skips the last item"

The symptom MUST stay in the same domain as the bug — if the bug is about Sphinx role parsing, the symptom must be about documentation rendering, not something generic like "incorrect results".

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


def _is_valid_test_output(test_output: str) -> bool:
    """Check if test output contains a real test failure, not a setup error."""
    stripped = test_output.strip()
    if len(stripped) < 100:
        return False
    head = stripped[:500]
    if 'ModuleNotFoundError' in head:
        return False
    failure_signals = ('FAILED', 'AssertionError', 'Error', 'ERRORS', 'Traceback')
    if not any(sig in stripped for sig in failure_signals):
        return False
    return True


async def generate_issue_from_symptom(
    symptom: str,
    test_output: str | None = None,
    repo_context: dict | None = None,
    style_examples: list[str] | None = None,
    model: str = "sonnet",
    social_context: str = "",
    dataset_examples: list[str] | None = None,
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
    ctx = repo_context or {
        "version": "", "lang_version": "", "os_info": random.choice(_OS_CHOICES),
    }

    version = ctx.get("version", "") or "latest main branch"
    lang_version = ctx.get("lang_version", "") or "3.11"
    os_info = ctx.get("os_info", "") or random.choice(_OS_CHOICES)

    general_area = symptom.split(".")[0] if "." in symptom else symptom

    if test_output and not _is_valid_test_output(test_output):
        logger.warning("Test output appears to be a setup error, falling back to LLM-generated issue")
        test_output = None

    if test_output:
        m = _FAILED_TEST_PATTERN.search(test_output)
        if not m:
            test_output = None
        else:
            test_id = m.group(1)
            _ISSUE_OPENERS = [
                'This test started failing after a recent update.',
                'Getting unexpected test failures.',
                'Noticed this is broken while working on something else.',
                'Tests are failing on this branch.',
                'Ran into this failure, not sure what changed.',
                '',
            ]
            opener = random.choice(_ISSUE_OPENERS)
            parts = [test_id, '']
            if opener:
                parts.append(opener)
                parts.append('')
            parts.append(f'```\n{test_output}\n```')
            parts.append('')
            parts.append(f'Environment: {version}, Python {lang_version}')
            recent = (repo_context or {}).get('recent_issues', [])
            if recent and random.random() < 0.9:
                ref = random.choice(recent)
                ref_styles = [
                    f'Related to {ref}',
                    f'See {ref}',
                    f'Might be related to {ref}',
                    f'cf. {ref}',
                    f'Possibly a regression from {ref}',
                ]
                parts.append(random.choice(ref_styles))
            issue = '\n'.join(parts)
            return issue

    if dataset_examples:
        examples_text = "\n\n".join(
            f"--- Example {i + 1} ---\n{ex}" for i, ex in enumerate(dataset_examples)
        )
        prompt = f"""Here are {len(dataset_examples)} real GitHub issues from this project:

{examples_text}

Write a GitHub issue for a bug matching the style, length, and tone of the examples above EXACTLY.

The bug manifests as: {symptom}
{social_context}

RULES:
- Match the examples' writing style precisely — if they're technical and direct, be technical and direct
- Match the examples' length — most are 200-800 characters
- Include code snippets if the examples do
- Do NOT use phrases like 'I've been banging my head', 'Is this expected?', 'Has anyone else hit this?', or other frustrated-developer language unless the examples use it
- Start with a title line starting with '## '"""
    else:
        char_budget = random.randint(300, 1000)

        style_section = ""
        if style_examples:
            examples_text = "\n".join(f"  - {t}" for t in style_examples[:3])
            style_section = f"\n\nHere are real issues from this project. Match their length and tone exactly:\n{examples_text}\n"
        else:
            style_section = "\n\nWrite a short, frustrated bug report. No headers. No structured format. Just describe the problem like a developer posting quickly.\n"

        prompt = f"""Write a GitHub issue report for a bug. A user observed this symptom: {symptom}

Your ENTIRE response must be under {char_budget} characters. Be CONCISE — real bug reports are short.

You are a frustrated user who hit this problem. You do NOT know the root cause, the specific code involved, or the fix. You only know what broke from the outside.

Environment context:
- Package version: {version}
- Python/language version: {lang_version}
- OS: {os_info}
{style_section}
Do NOT mention specific source file names, function names, line numbers, or the exact code fix.

Format: start with "## " title, then the body."""

    resolved_model = MODEL_MAP.get(model, model)

    options = ClaudeCodeOptions(
        max_turns=1,
        model=resolved_model,
    )

    result_text_full: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text_full = _extract_text_from_result(message)
    except Exception:
        logger.warning(
            "LLM call failed for issue description, using fallback"
        )

    if not result_text_full:
        fallback = (
            f"Seeing an issue with {general_area} — {symptom}. "
            f"Running on {os_info}, version {version}. Anyone else hit this?"
        )
        if social_context:
            fallback += social_context
        return fallback

    result_text_full = _enforce_banned_openers(result_text_full)

    if len(result_text_full) > 1500:
        result_text_full = _truncate_issue(result_text_full)

    if social_context:
        result_text_full += social_context

    return result_text_full


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


def _find_existing_test_file(
    repo_path: str, source_file: str, language: str,
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
            str(source_path.parent / f"test_{stem}.py"),
        ]
        if source_path.parent.parts:
            candidates.append(
                f"tests/{'/'.join(source_path.parent.parts)}/test_{stem}.py"
            )
        for c in candidates:
            if (root / c).is_file():
                return c
        # Fuzzy match: any test file in tests/ whose name contains the stem
        for test_dir_name in ("tests", "test"):
            tests_dir = root / test_dir_name
            if tests_dir.is_dir():
                for f in tests_dir.rglob("*.py"):
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
            for test_dir_name in ("tests", "test"):
                for sub in search_dirs:
                    pkg_test_dir = root / test_dir_name / sub
                    if pkg_test_dir.is_dir():
                        for f in sorted(pkg_test_dir.glob("test_*.py")):
                            return str(f.relative_to(root))
    elif language == "go":
        test_file = str(source_path.parent / f"{stem}_test.go")
        if (root / test_file).is_file():
            return test_file
    elif language == "rust":
        rust_candidates = [
            f"tests/{stem}.rs",
            str(source_path.parent / f"{stem}_test.rs"),
        ]
        for c in rust_candidates:
            if (root / c).is_file():
                return c
    elif language == "java":
        java_path = str(source_path)
        test_path = java_path.replace(
            "src/main/java/", "src/test/java/"
        ).replace(f"{stem}.java", f"{stem}Test.java")
        if (root / test_path).is_file():
            return test_path

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

    for f, content in test_files:
        if specific_pat.search(content):
            return str(f.relative_to(root))

    if parent_pat is not None:
        for f, content in test_files:
            if parent_pat.search(content):
                return str(f.relative_to(root))

    return None


async def generate_test_patch(
    bug_spec: BugSpec,
    repo_path: str,
    language: str,
    model: str = "sonnet",
) -> str | None:
    """Generate a test patch that exposes a synthetic bug.

    Only modifies existing test files. If no existing test file can be
    found, returns None — creating new test files produces detectable
    synthetic patterns (fabricated imports, brand-new functions).
    """
    existing_test = _find_existing_test_file(repo_path, bug_spec.file, language)

    if existing_test:
        return await _generate_test_patch_existing(
            bug_spec, repo_path, existing_test, language, model,
        )
    logger.warning(
        "  No existing test file found for %s — skipping test patch generation",
        bug_spec.file,
    )
    return None


def _count_test_functions(code: str) -> int:
    """Count the number of test function definitions in Python code."""
    return len(re.findall(r'^\s*def\s+test_\w+', code, re.MULTILINE))


async def _generate_test_patch_existing(
    bug_spec: BugSpec,
    repo_path: str,
    test_file: str,
    language: str,
    model: str,
) -> str | None:
    """Generate a test patch by adding tests to an existing test file."""
    try:
        original_test_content = (Path(repo_path) / test_file).read_text(
            encoding="utf-8", errors="replace",
        )
    except OSError:
        logger.warning("Could not read existing test file %s", test_file)
        return None

    prompt = f"""You are modifying an existing test file to add regression coverage. Here is the current test file:

```{language}
{original_test_content}
```

A bug was introduced in the code. Here is the original (correct) function:
```{language}
{bug_spec.original_code}
```

Here is the buggy function:
```{language}
{bug_spec.buggy_code}
```

The bug: {bug_spec.bug_description}

HARD CONSTRAINT: You MUST NOT add any new `def test_` functions. You can ONLY modify existing test functions by:
- Adding 1-2 `assert` statements to an existing test function that already tests related behavior
- Adding a new case to an existing `@pytest.mark.parametrize` decorator

Find the most closely related existing test function and add assertions there. At least one added assertion must PASS against the original code and FAIL against the buggy code.

Requirements:
- Follow the existing test style and conventions in the file
- Use the same imports, fixtures, and test patterns already present
- Do NOT add comments explaining your changes
- Do NOT add new test functions — this will be validated and rejected

Return the COMPLETE modified test file."""

    resolved_model = MODEL_MAP.get(model, model)
    options = ClaudeCodeOptions(max_turns=1, model=resolved_model)

    modified_content: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = _extract_text_from_result(message)
                if text:
                    extracted = _extract_code_block(text)
                    modified_content = extracted if extracted else text
    except Exception:
        logger.warning("LLM call failed for existing-file test generation")
        return None

    if not modified_content or modified_content.strip() == original_test_content.strip():
        return None

    if len(modified_content) < len(original_test_content) * 0.5:
        logger.warning(
            "  Generated test code too short (%d chars vs %d original) — likely truncated",
            len(modified_content), len(original_test_content),
        )
        return None

    modified_content = _strip_strategy_labels(modified_content)
    modified_content = _normalize_test_whitespace(modified_content, original_test_content)

    if not _validate_test_code(modified_content, language):
        logger.warning("  Generated test code failed validation")
        return None

    if language == "python" and not _validate_test_imports(modified_content, repo_path):
        return None

    if language == 'python':
        original_test_count = _count_test_functions(original_test_content)
        modified_test_count = _count_test_functions(modified_content)
        if modified_test_count > original_test_count:
            logger.warning(
                '  Test patch adds %d new test function(s) — rejecting to avoid detection',
                modified_test_count - original_test_count,
            )
            return None

    # generate_patch diffs mutated→original; swap args so we get original→modified
    return generate_patch(modified_content, original_test_content, test_file)


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

Buggy code:
```{language}
{bug_spec.buggy_code}
```

Language: {language}

The bug: {bug_spec.bug_description}

Write 2-3 test functions:
- At least one PASSES against the original and FAILS against the buggy code (the regression test)
- 1-2 additional tests that PASS against BOTH versions — these test related behavior that a developer would naturally add for coverage while investigating the area (e.g., testing normal inputs, boundary values for the same function, or a related code path)
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

    prompt = f"""A bug fix is being applied to {bug_spec.file} in a {language} project. The fix addresses: {bug_spec.bug_description}

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
    temp_branch = f"synth-temp-{branch_hash}"

    try:
        orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if orig == "HEAD":
            orig = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", "-b", temp_branch])

        file_path = Path(repo_path) / file_rel
        file_path.write_text(mutated_content, encoding="utf-8")

        run(["git", "add", file_rel])
        run(["git", "commit", "-m", f"synth: {description}"])

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
    temp_branch = f"synth-temp-{branch_hash}"

    try:
        orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if orig == "HEAD":
            orig = run(["git", "rev-parse", "HEAD"]).stdout.strip()

        run(["git", "checkout", "-b", temp_branch])

        for file_rel, content in buggy_files.items():
            file_path = Path(repo_path) / file_rel
            file_path.write_text(content, encoding="utf-8")
            run(["git", "add", file_rel])

        run(["git", "commit", "-m", f"synth: {description}"])

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


def _extract_failed_test_names(test_output: str) -> set[str]:
    """Extract test IDs from pytest FAILED lines.

    Parses lines like 'FAILED tests/test_foo.py::TestBar::test_baz'
    and returns the set of full test node IDs.
    """
    return set(_FAILED_TEST_PATTERN.findall(test_output))


_TEST_COMMANDS: dict[str, list[list[str]]] = {
    "python": [
        ["python", "-m", "pytest", "--tb=long", "-q"],
        ["python", "-m", "unittest", "discover", "-s", "tests"],
    ],
    "go": [["go", "test", "./..."]],
    "rust": [["cargo", "test"]],
    "java": [["mvn", "test", "-q"]],
}


def _run_tests_on_buggy_code(
    repo_path: str,
    buggy_commit: str,
    language: str,
    timeout: int = 120,
    target_file: str | None = None,
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

    # Build the test command — use targeted test file if possible
    test_cmd: list[str] | None = None
    if target_file and language == "python":
        test_file = _find_existing_test_file(repo_path, target_file, language)
        if test_file:
            test_cmd = [sys.executable, "-m", "pytest", test_file, "--tb=long", "-q"]
            logger.debug("  Running targeted tests: %s", test_file)

    # Run baseline on clean code to identify pre-existing failures
    baseline_deselects: list[str] = []
    if language == "python":
        baseline_cmd = [sys.executable, "-m", "pytest", "--tb=no", "-q"]
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

    # Install the target package so imports resolve during test runs
    root = Path(repo_path)
    if any((root / cfg).is_file() for cfg in ("pyproject.toml", "setup.py", "setup.cfg")):
        installed = False
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
                cwd=repo_path, capture_output=True, text=True, timeout=120,
            )
            installed = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            pass
        if not installed:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet", "--no-deps"],
                    cwd=repo_path, capture_output=True, text=True, timeout=60,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                logger.debug("  pip install -e . failed, proceeding anyway")

    repo_package_name = Path(repo_path).name.replace("-", "_")
    try:
        import_check = subprocess.run(
            [sys.executable, "-c", f"import {repo_package_name}"],
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
            [sys.executable if c == "python" else c for c in t]
            for t in _TEST_COMMANDS.get(language, [])
        ]
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


async def synthesize_repo(
    repo_path: str,
    repo_slug: str,
    base_commit: str,
    language: str,
    max_mutations: int = 10,
    operators: list[str] | None = None,
    model: str = "sonnet",
) -> list[CandidateInstance]:
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

    Returns:
        List of CandidateInstance objects.
    """
    dataset_examples = _load_dataset_examples(DATASET_PATH, repo_slug)
    if dataset_examples:
        logger.info(
            "Loaded %d dataset examples for few-shot conditioning", len(dataset_examples),
        )

    logger.info(
        "Finding mutation targets in %s (%s)", repo_path, language,
    )
    all_targets = find_mutation_targets(repo_path, language)
    # Pre-filter to targets with existing test files to avoid wasted LLM calls
    targets = [
        t for t in all_targets
        if _find_existing_test_file(repo_path, t["file"], language) is not None
    ]
    logger.info(
        "Found %d mutation targets (%d with test files)",
        len(all_targets), len(targets),
    )
    if not targets:
        targets = all_targets
        logger.warning("No targets with test files, falling back to all targets")

    candidates: list[CandidateInstance] = []

    for i, target in enumerate(targets[:max_mutations * 8]):
        if len(candidates) >= max_mutations:
            break

        logger.info(
            "[%d/%d] Mutating %s:%s",
            i + 1,
            min(len(targets), max_mutations * 8),
            target["file"],
            target["function_name"],
        )

        related_files = _find_related_files(repo_path, target, language)
        if related_files:
            logger.info("  Found %d related files", len(related_files))

        bug_plan = await _plan_multi_file_mutation(
            target["source"], related_files, model=model,
        )
        if bug_plan:
            logger.info("  Multi-file plan: %s", bug_plan.primary_description[:80])

        # H2: retry introduce_bug up to 2 times if patch is too simple
        bug_spec = None
        patch = ""
        mutated_content = ""
        original_content = ""
        for attempt in range(3):
            bug_spec = await introduce_bug(
                target, model=model, related_files=related_files,
                bug_plan=bug_plan,
            )
            if bug_spec is None:
                logger.warning("  Skipped — LLM did not produce a valid mutation")
                break

            file_path = Path(repo_path) / bug_spec.file
            try:
                original_content = file_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                logger.warning("  Skipped — could not read %s", bug_spec.file)
                bug_spec = None
                break

            mutated_content = original_content.replace(
                bug_spec.original_code, bug_spec.buggy_code, 1,
            )

            if mutated_content == original_content:
                logger.warning('  Mutation could not be applied, retrying (%d/2)', attempt + 1)
                bug_spec = None
                continue

            if not _validate_mutation_parses(mutated_content, language):
                logger.warning('  Mutation does not parse (%s), retrying (%d/2)', language, attempt + 1)
                bug_spec = None
                continue

            orig_stripped = [ln.strip() for ln in original_content.splitlines() if ln.strip()]
            mut_stripped = [ln.strip() for ln in mutated_content.splitlines() if ln.strip()]
            if orig_stripped == mut_stripped:
                logger.warning('  Mutation is whitespace-only, retrying (%d/2)', attempt + 1)
                bug_spec = None
                continue

            mutated_content = _normalize_test_whitespace(mutated_content, original_content)

            patch = generate_patch(original_content, mutated_content, bug_spec.file)
            if not patch.strip():
                logger.warning("  Skipped — empty patch")
                bug_spec = None
                break

            changed = _count_changed_lines(patch)
            if changed >= 2 and len(patch) >= 100:
                break
            if attempt < 2:
                reason = []
                if changed < 2:
                    reason.append(f"{changed} changed lines < 2")
                if len(patch) < 100:
                    reason.append(f"{len(patch)} chars < 100")
                logger.info(
                    "  Patch too simple (%s), retrying (%d/2)",
                    ", ".join(reason), attempt + 1,
                )
                bug_spec = None
            else:
                logger.warning(
                    "  Patch still below targets after retries (%d lines, %d chars), accepting",
                    changed, len(patch),
                )

        if bug_spec is None:
            continue
        if not patch.strip():
            continue

        # Apply secondary changes from multi-file mutation
        buggy_files: dict[str, str] = {bug_spec.file: mutated_content}
        for sc in bug_spec.secondary_changes:
            sec_path = Path(repo_path) / sc.file
            if not sec_path.is_file():
                logger.warning("  Secondary file not found: %s", sc.file)
                continue
            try:
                sec_content = sec_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if sc.original_snippet not in sec_content:
                logger.warning("  Secondary snippet not found in %s", sc.file)
                continue
            sec_buggy = sec_content.replace(sc.original_snippet, sc.buggy_snippet, 1)
            if sec_buggy != sec_content:
                patch += generate_patch(sec_content, sec_buggy, sc.file)
                buggy_files[sc.file] = sec_buggy
                logger.info("  Secondary change in %s: %s", sc.file, sc.description)

        if len(buggy_files) < 2 and related_files:
            logger.info("  Only %d file changed, retrying with explicit multi-file instruction", len(buggy_files))
            retry_spec = await introduce_bug(
                target, model=model, related_files=related_files,
            )
            if retry_spec and retry_spec.secondary_changes:
                for sc in retry_spec.secondary_changes:
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
                        patch += generate_patch(sec_content, sec_buggy, sc.file)
                        buggy_files[sc.file] = sec_buggy
                        logger.info("  Retry secondary change in %s", sc.file)

        patched_files: set[str] = {bug_spec.file} | set(buggy_files.keys())
        ctx = _collect_repo_context(repo_path)
        real_issues = ctx.get("recent_issues", [])

        incidentals = await _generate_incidental_changes(
            repo_path, bug_spec, language, model=model,
        )
        for inc_path, inc_original, inc_modified in incidentals:
            if inc_path in patched_files:
                logger.info("  Skipping duplicate incidental for %s", inc_path)
                continue
            # Validate RST references in changelog files
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
                    # Reject CHANGES.rst edits that create duplicate version headers
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
                        # Reject edits where underline is separated from header by blank lines
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
            logger.warning("  Skipped — could not create buggy commit")
            continue

        # H3: Capture test failure output from buggy code
        test_output = _run_tests_on_buggy_code(
            repo_path, buggy_commit, language,
            target_file=bug_spec.file,
        )
        if test_output:
            logger.info("  Captured %d chars of test output", len(test_output))
            test_output = _sanitize_test_output(test_output, repo_path)
            test_output = _humanize_traceback(test_output, repo_path)

        if not test_output or not _is_valid_test_output(test_output):
            logger.warning("  Skipped — mutation did not cause test failures (data-first path required)")
            continue

        # H2: Mine social artifacts and build social context
        social_artifacts = _mine_social_artifacts(repo_path)
        social_context = _build_social_context(social_artifacts)

        # H1: Information firewall — generate issue from symptom only
        symptom = await _bug_to_symptom(bug_spec.bug_description, file_path=bug_spec.file, model=model)
        style_examples = _mine_issue_style_examples(repo_path)
        problem_statement = await generate_issue_from_symptom(
            symptom=symptom,
            test_output=test_output,
            repo_context=ctx,
            style_examples=style_examples,
            model=model,
            social_context=social_context,
            dataset_examples=dataset_examples,
        )

        test_patch = await generate_test_patch(
            bug_spec, repo_path, language, model=model,
        ) or ''

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
        candidates.append(candidate)

        logger.info(
            "  Generated: %s (%s)", candidate.instance_id, bug_spec.bug_category,
        )

    logger.info(
        "Synthesis complete: %d/%d candidates generated",
        len(candidates),
        max_mutations,
    )
    return candidates
