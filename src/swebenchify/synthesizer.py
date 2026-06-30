"""LLM-based synthetic bug generation for SWE-bench instances.

Uses Claude to introduce realistic bugs into source code, generate gold
fix patches, and produce corresponding issue reports. Language-agnostic:
works across Python, Go, Rust, and Java using simple text-based function
detection (not AST parsing).
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import logging
import os
import re
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
}

_LANGUAGE_EXCLUDE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"(^|/)tests?/"),
        re.compile(r"(^|/)__init__\.py$"),
        re.compile(r"(^|/)setup\.py$"),
        re.compile(r"(^|/)conftest\.py$"),
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


@dataclasses.dataclass
class BugSpec:
    """Specification for a synthetic bug to introduce."""

    file: str
    function_name: str
    original_code: str
    buggy_code: str
    bug_description: str
    bug_category: str


@dataclasses.dataclass
class SynthesisResult:
    """Result of synthesizing a single bug instance."""

    bug_spec: BugSpec
    patch: str
    problem_statement: str
    instance_id: str
    base_commit: str


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
                return targets

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lines = content.splitlines()
            functions = extractor(lines)

            for func in functions[:max_functions]:
                targets.append({
                    "file": rel_path,
                    "function_name": func["function_name"],
                    "source": func["source"],
                    "language": language,
                    "start_line": func["start_line"],
                    "end_line": func["end_line"],
                })

    return targets


def _is_rust_test_module(path: Path) -> bool:
    """Check if a Rust file is entirely a test module (#[cfg(test)])."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        stripped = content.strip()
        return stripped.startswith("#[cfg(test)]")
    except OSError:
        return False


async def introduce_bug(
    target: dict,
    model: str = "sonnet",
) -> BugSpec | None:
    """Use Claude to introduce a realistic bug into a function.

    Args:
        target: Dict from find_mutation_targets with file, function_name,
            source, language keys.
        model: Claude model shortname ('sonnet', 'haiku', 'opus').

    Returns:
        BugSpec if successful, None if the LLM fails to produce a valid
        mutation.
    """
    language = target["language"]
    function_name = target["function_name"]
    source = target["source"]

    prompt = f"""You are a code mutation expert. Given the following {language} function, introduce ONE subtle, realistic bug. The bug should be the kind a developer might actually make — NOT a trivial syntax error.

Categories include: off-by-one errors, wrong variable usage, missing null/bounds check, incorrect operator, swapped arguments, wrong return value, missing edge case handling, incorrect string formatting, race condition setup, wrong comparison.

Here is the function:

```{language}
{source}
```

Return your response in EXACTLY this format:

<bug_category>category name here</bug_category>

<bug_description>One sentence describing what the bug does and why it's subtle</bug_description>

<buggy_code>
The COMPLETE modified function with the bug introduced. Include ALL lines of the original function.
</buggy_code>

IMPORTANT:
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

    if buggy_code == target["source"]:
        logger.warning("LLM returned identical code — no bug introduced")
        return None

    category = cat_match.group(1).strip() if cat_match else "unknown"
    description = desc_match.group(1).strip() if desc_match else "Bug introduced in function"

    return BugSpec(
        file=target["file"],
        function_name=target["function_name"],
        original_code=target["source"],
        buggy_code=buggy_code,
        bug_description=description,
        bug_category=category,
    )


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


async def generate_issue_description(
    bug_spec: BugSpec,
    test_output: str | None = None,
    model: str = "sonnet",
) -> str:
    """Generate a realistic GitHub issue description for a bug.

    Args:
        bug_spec: The bug specification.
        test_output: Optional test output showing the failure.
        model: Claude model shortname.

    Returns:
        Issue description text.
    """
    test_context = ""
    if test_output:
        test_context = f"\n\nTests show:\n```\n{test_output[:2000]}\n```"

    prompt = f"""Write a GitHub issue report for a bug. The bug is in the file `{bug_spec.file}`, function `{bug_spec.function_name}`.

The bug manifests as: {bug_spec.bug_description}{test_context}

Write as a user reporting the problem:
- Describe the observed (incorrect) behavior
- Describe the expected (correct) behavior
- Include steps to reproduce if applicable
- Use a descriptive title

Do NOT mention the fix or the root cause code change. Do NOT reference specific line numbers. Write naturally as a user would.

Format your response as a GitHub issue with a title line starting with "## " followed by the body."""

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
        logger.warning(
            "LLM call failed for issue description, using fallback"
        )

    if result_text:
        return result_text

    return (
        f"## Bug in {bug_spec.file}\n\n"
        f"There appears to be an issue in `{bug_spec.function_name}`: "
        f"{bug_spec.bug_description}"
    )


def build_candidate(
    repo: str,
    base_commit: str,
    synthesis_result: SynthesisResult,
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
    short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
    instance_id = f"{owner_repo}-synth-{short_hash}"

    return CandidateInstance(
        repo=repo,
        instance_id=instance_id,
        pr_number=0,
        base_commit=base_commit,
        merge_commit="",
        patch=synthesis_result.patch,
        test_patch="",
        problem_statement=synthesis_result.problem_statement,
        hints_text="",
        created_at=datetime.now(timezone.utc).isoformat(),
        provenance="synthetic",
    )


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
        base_commit: Commit SHA to target.
        language: Programming language ('python', 'go', 'rust', 'java').
        max_mutations: Maximum number of bugs to generate.
        operators: Optional list of bug categories to use (unused, reserved
            for future filtering).
        model: Claude model shortname.

    Returns:
        List of CandidateInstance objects.
    """
    logger.info(
        "Finding mutation targets in %s (%s)", repo_path, language,
    )
    targets = find_mutation_targets(repo_path, language)
    logger.info("Found %d mutation targets", len(targets))

    candidates: list[CandidateInstance] = []

    for i, target in enumerate(targets):
        if len(candidates) >= max_mutations:
            break

        logger.info(
            "[%d/%d] Mutating %s:%s",
            i + 1,
            min(len(targets), max_mutations),
            target["file"],
            target["function_name"],
        )

        bug_spec = await introduce_bug(target, model=model)
        if bug_spec is None:
            logger.warning("  Skipped — LLM did not produce a valid mutation")
            continue

        file_path = Path(repo_path) / bug_spec.file
        try:
            original_content = file_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            logger.warning("  Skipped — could not read %s", bug_spec.file)
            continue

        mutated_content = original_content.replace(
            bug_spec.original_code, bug_spec.buggy_code, 1,
        )

        if mutated_content == original_content:
            logger.warning("  Skipped — could not apply mutation to file")
            continue

        patch = generate_patch(original_content, mutated_content, bug_spec.file)
        if not patch.strip():
            logger.warning("  Skipped — empty patch")
            continue

        problem_statement = await generate_issue_description(
            bug_spec, model=model,
        )

        synthesis_result = SynthesisResult(
            bug_spec=bug_spec,
            patch=patch,
            problem_statement=problem_statement,
            instance_id="",
            base_commit=base_commit,
        )

        candidate = build_candidate(repo_slug, base_commit, synthesis_result)
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
