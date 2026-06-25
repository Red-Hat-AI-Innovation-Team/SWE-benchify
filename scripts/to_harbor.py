"""Convert SWE-benchify JSONL dataset to Harbor task directories.

Language-agnostic: reads environment configuration from env-spec JSON files
(keyed by env_spec_hash) or synthesizes defaults from instance metadata.
Adding a new language requires only a new env spec -- zero code changes.

Usage:
    uv run python scripts/to_harbor.py \\
        --input output/rh-v1/all-task-instances.jsonl \\
        --output output/harbor-tasks \\
        [--env-specs DIR] [--limit N] [--instance-id ID] [--overwrite]
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent


# ── EnvironmentConfig: unified, language-agnostic env spec ──────


# Default base Docker images per language.  Looked up by
# "{language}:{language_version}" so the version can use any tag
# the upstream registry supports (e.g. "3.11-slim", "1.24.3").
_DEFAULT_BASE_IMAGES: dict[str, str] = {
    "go": "golang:{version}",
    "python": "python:{version}-slim",
}

# Packages that are always installed (git, patch needed for every language).
_CORE_SYSTEM_DEPS = ["git", "patch"]

# Default test commands when no env spec exists.
_DEFAULT_TEST_CMDS: dict[str, str] = {
    "go": "go test -json -count=1 {test_scope}",
    "python": "python -m pytest -xvs {test_scope}",
}

# Test output format implied by language (used by the embedded F2P checker).
_DEFAULT_TEST_OUTPUT_FORMATS: dict[str, str] = {
    "go": "go-json",
    "python": "pytest-verbose",
}


@dataclass
class EnvironmentConfig:
    """Unified environment configuration for any language.

    Built from three sources (in priority order):
      1. Loaded env spec file (from --env-specs directory)
      2. Instance metadata (repo_language, version, etc.)
      3. Language defaults (base image patterns, core deps)
    """

    language: str
    language_version: str
    base_image: str  # fully resolved, e.g. "golang:1.24.3"
    system_dependencies: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    pre_install: list[str] = field(default_factory=list)
    install_cmd: str = ""  # e.g. "pip install -e ." or ""
    extra_packages: list[str] = field(default_factory=list)  # pip packages, etc.
    test_cmd: str = ""  # e.g. "go test -json -count=1 ./..."
    test_output_format: str = ""  # "go-json", "pytest-verbose"
    build_cmd: str = ""  # optional pre-test build step


def _spec_val(spec: dict | None, *keys: str, default=""):
    """Return the first truthy value from *spec* for the given keys, or *default*."""
    if not spec:
        return default
    for k in keys:
        v = spec.get(k)
        if v:
            return v
    return default


def _spec_list(spec: dict | None, *keys: str) -> list:
    """Return the first non-empty list from *spec* for the given keys."""
    if not spec:
        return []
    for k in keys:
        v = spec.get(k)
        if v:
            return list(v)
    return []


def build_env_config(
    inst: dict,
    spec: dict | None,
) -> EnvironmentConfig:
    """Build an EnvironmentConfig from an env spec file and instance metadata."""
    lang = inst.get("repo_language", "python").lower()

    # Language version: spec → instance metadata → hardcoded default
    lang_ver = _spec_val(spec, "language_version", "go_version")
    if not lang_ver:
        raw_ver = inst.get("version", "")
        if lang == "go" and raw_ver:
            lang_ver = raw_ver.split("-")[0]
        else:
            lang_ver = {"go": "1.22", "python": "3.11"}.get(lang, "latest")

    # Base image
    base_image = _spec_val(spec, "base_image")
    if not base_image:
        pattern = _DEFAULT_BASE_IMAGES.get(lang, f"{lang}:{'{version}'}")
        base_image = pattern.format(version=lang_ver)

    # Env vars (subsumes goflags)
    env_vars: dict[str, str] = dict(spec.get("env_vars", {})) if spec else {}
    if spec and spec.get("goflags") and "GOFLAGS" not in env_vars:
        env_vars["GOFLAGS"] = spec["goflags"]

    # Install command
    install_cmd = _spec_val(spec, "install_cmd")
    if not install_cmd and lang == "python":
        install_cmd = "pip install -e . 2>/dev/null || pip install . 2>/dev/null || true"

    # Extra packages
    extra_packages = _spec_list(spec, "extra_packages", "pip_packages")
    if lang == "python" and "pytest" not in " ".join(extra_packages):
        extra_packages = ["pytest"] + extra_packages

    return EnvironmentConfig(
        language=lang,
        language_version=lang_ver,
        base_image=base_image,
        system_dependencies=_spec_list(spec, "system_dependencies"),
        env_vars=env_vars,
        pre_install=_spec_list(spec, "pre_install"),
        install_cmd=install_cmd,
        extra_packages=extra_packages,
        test_cmd=_spec_val(spec, "test_cmd") or _DEFAULT_TEST_CMDS.get(lang, ""),
        test_output_format=_spec_val(spec, "test_output_format") or _DEFAULT_TEST_OUTPUT_FORMATS.get(lang, "pytest-verbose"),
        build_cmd=_spec_val(spec, "build_cmd"),
    )


# ── Env spec loading ────────────────────────────────────────────


def load_env_spec(env_spec_hash: str, env_specs_dir: Path) -> dict | None:
    """Load an env spec JSON file by its content hash.

    Searches in order:
      1. {env_specs_dir}/{hash}.json
      2. {env_specs_dir}/go-specs/{hash}.json  (backward compat)
    """
    for subdir in [env_specs_dir, env_specs_dir / "go-specs"]:
        spec_file = subdir / f"{env_spec_hash}.json"
        if spec_file.exists():
            return json.loads(spec_file.read_text())
    return None


# ── Helpers ─────────────────────────────────────────────────────


def load_instances(path: str) -> list[dict]:
    instances = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def decode_f2p(value) -> list[str]:
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def estimate_difficulty(inst: dict) -> str:
    patch_lines = inst.get("patch_lines", 0)
    files_touched = inst.get("files_touched", 0)
    if files_touched > 3 or patch_lines > 200:
        return "hard"
    if files_touched > 1 or patch_lines > 50:
        return "medium"
    return "easy"


def affected_packages_go(test_patch: str) -> list[str]:
    """Extract Go package paths affected by the test patch."""
    pkgs = set()
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        pkg_dir = str(Path(path).parent)
        if pkg_dir == ".":
            pkgs.add("./...")
        else:
            pkgs.add(f"./{pkg_dir}/...")
    return sorted(pkgs) if pkgs else ["./..."]


def test_files_from_patch(test_patch: str) -> list[str]:
    """Extract test file paths from a unified diff."""
    files = []
    for line in test_patch.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m and m.group(1) != "/dev/null":
            files.append(m.group(1))
    return files


def compute_test_scope(inst: dict, env: EnvironmentConfig) -> str:
    """Compute the test scope string appropriate for the language.

    Go: package glob paths from test_patch diff headers.
    Python: test file paths from test_patch.
    Others: "." (run everything).
    """
    test_patch = inst.get("test_patch", "")
    if env.language == "go":
        return " ".join(affected_packages_go(test_patch))
    if env.language == "python":
        files = test_files_from_patch(test_patch)
        return " ".join(shlex.quote(f) for f in files) if files else "."
    return "."


# ── File generators ─────────────────────────────────────────────


def gen_task_toml(inst: dict) -> str:
    instance_id = inst["instance_id"]
    repo = inst["repo"]
    lang = inst.get("repo_language", "unknown")
    difficulty = estimate_difficulty(inst)
    product = inst.get("product") or ""

    keywords = ["swe-bench", "debugging", lang]
    if product:
        keywords.append(product.lower())
    keywords_str = ", ".join(f'"{k}"' for k in keywords)

    return dedent(f"""\
        schema_version = "1.0"

        [task]
        name = "swebenchify/{instance_id}"
        description = "Fix a bug in {repo} ({lang})"
        authors = [
            {{ name = "Red Hat AI Innovation Team" }},
        ]
        keywords = [{keywords_str}]

        [metadata]
        difficulty = "{difficulty}"
        category = "debugging"
        repo_language = "{lang}"
        repo = "{repo}"
        product = "{product}"

        [verifier]
        network_mode = "public"
        timeout_sec = 3000

        [agent]
        network_mode = "public"
        timeout_sec = 3000

        [environment]
        build_timeout_sec = 1800.0
    """)


def gen_instruction_md(inst: dict) -> str:
    problem = inst.get("problem_statement", "").strip()
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    hints = (inst.get("hints_text") or "").strip()

    parts = [problem, ""]
    parts.append(f"**Repository:** `{repo}`")
    parts.append(f"**Base commit:** `{base_commit}`")
    if hints:
        parts.append("")
        parts.append("## Hints")
        parts.append("")
        parts.append(hints)

    return "\n".join(parts) + "\n"


def gen_dockerfile(inst: dict, env: EnvironmentConfig) -> str:
    """Generate a Dockerfile from the unified EnvironmentConfig.

    Works for any language -- all language-specific knowledge is in the
    EnvironmentConfig, not in if/else branches here.
    """
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    lines: list[str] = []

    # Base image
    lines.append(f"FROM {env.base_image}")
    lines.append("")

    # Core system deps (git, patch) + language-specific system deps
    all_sys_deps = list(_CORE_SYSTEM_DEPS)
    # Add build-essential for Python (needed for C extensions)
    if env.language == "python":
        all_sys_deps.append("build-essential")
    for dep in env.system_dependencies:
        if dep not in all_sys_deps:
            all_sys_deps.append(dep)
    pkgs = " ".join(all_sys_deps)
    lines.append("RUN apt-get update -qq && \\")
    lines.append(f"    apt-get install -y --no-install-recommends {pkgs} && \\")
    lines.append("    rm -rf /var/lib/apt/lists/*")

    # Pre-install commands
    for cmd in env.pre_install:
        lines.append("")
        lines.append(f"RUN {cmd}")

    # Environment variables
    for var_name, var_value in sorted(env.env_vars.items()):
        if var_value:
            lines.append(f'ENV {var_name}="{var_value}"')

    # Extra packages (pip packages, etc.)
    if env.extra_packages:
        lines.append("")
        if env.language == "python":
            pkg_list = " ".join(shlex.quote(p) for p in env.extra_packages)
            lines.append(f"RUN pip install --no-cache-dir {pkg_list}")
        # For other languages, extra_packages can be handled by
        # language-specific install commands in the env spec.

    # Clone repo at base_commit
    lines.append("")
    lines.append(f"RUN git clone https://github.com/{repo}.git /testbed && \\")
    lines.append(f"    cd /testbed && git checkout {base_commit}")
    lines.append("")
    lines.append("WORKDIR /testbed")
    lines.append("RUN mkdir -p /logs/verifier")

    return "\n".join(lines) + "\n"


def gen_test_sh(inst: dict, env: EnvironmentConfig) -> str:
    """Generate test.sh with an embedded multi-format F2P checker.

    Works for any language.  The test command and output format come from
    the EnvironmentConfig; the embedded Python F2P checker handles
    go-json and pytest-verbose formats.
    """
    test_patch = inst.get("test_patch", "")
    f2p = decode_f2p(inst.get("FAIL_TO_PASS", "[]"))
    f2p_json = json.dumps(f2p)
    test_scope = compute_test_scope(inst, env)

    # Resolve {test_scope} placeholder in test_cmd
    test_cmd = env.test_cmd.replace("{test_scope}", test_scope)
    # If test_cmd has no placeholder and we have a scope, append it
    # (for Go default "go test -json -count=1 {test_scope}")
    # The placeholder was already resolved above; nothing more to do.

    # Build the install section
    install_lines = ""
    if env.install_cmd:
        install_lines = f"""
# Install project
{env.install_cmd}
"""

    return f"""#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo {shlex.quote(test_patch)} > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff
{install_lines}
# Run tests and capture output
{test_cmd} 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "{env.test_output_format}")
f2p = {f2p_json}

def parse_go_json(text):
    results = {{}}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {{"pass": "passed", "fail": "failed", "skip": "skipped"}}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {{}}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {{"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {{
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {{OUTPUT_FORMAT}}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    \"\"\"Check if an expected test ID matches any result in the parsed output.\"\"\"
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {{len(missing)}}/{{len(f2p)}} tests still failing: {{missing}}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="{env.test_output_format}" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${{exit_code}}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${{exit_code}}"
"""


def gen_solve_sh(inst: dict) -> str:
    patch = (inst.get("patch") or "").strip()
    return f"""#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
{patch}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
"""


# ── Main converter ──────────────────────────────────────────────


def generate_task(
    inst: dict,
    output_dir: Path,
    env_specs_dir: Path,
    overwrite: bool = False,
) -> Path:
    instance_id = inst["instance_id"]
    task_dir = output_dir / instance_id

    if task_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Already exists: {task_dir}")
        shutil.rmtree(task_dir)

    env_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"
    solution_dir = task_dir / "solution"

    env_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    solution_dir.mkdir(parents=True)

    # Load env spec if available (any language, not just Go)
    spec: dict | None = None
    env_hash = inst.get("env_spec_hash")
    if env_hash:
        spec = load_env_spec(env_hash, env_specs_dir)

    # Build unified environment config
    env = build_env_config(inst, spec)

    # task.toml
    (task_dir / "task.toml").write_text(gen_task_toml(inst))

    # instruction.md
    (task_dir / "instruction.md").write_text(gen_instruction_md(inst))

    # environment/Dockerfile
    (env_dir / "Dockerfile").write_text(gen_dockerfile(inst, env))

    # tests/test.sh
    test_sh = gen_test_sh(inst, env)
    test_sh_path = tests_dir / "test.sh"
    test_sh_path.write_text(test_sh)
    test_sh_path.chmod(test_sh_path.stat().st_mode | stat.S_IEXEC)

    # tests/config.json
    (tests_dir / "config.json").write_text(json.dumps(inst, indent=2))

    # solution/solve.sh
    solve_sh_path = solution_dir / "solve.sh"
    solve_sh_path.write_text(gen_solve_sh(inst))
    solve_sh_path.chmod(solve_sh_path.stat().st_mode | stat.S_IEXEC)

    return task_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert SWE-benchify JSONL to Harbor task directories"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input JSONL file (e.g. output/rh-v1/all-task-instances.jsonl)",
    )
    parser.add_argument(
        "--output", "-o",
        default="output/harbor-tasks",
        help="Output directory for Harbor tasks (default: output/harbor-tasks)",
    )
    parser.add_argument(
        "--env-specs",
        default=None,
        help=(
            "Directory containing env spec JSON files ({hash}.json). "
            "Falls back to data/ relative to repo root.  Also searches "
            "a go-specs/ subdirectory for backward compatibility."
        ),
    )
    # Backward-compat alias (hidden)
    parser.add_argument("--data-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to generate")
    parser.add_argument("--instance-id", type=str, default=None, help="Generate a single task")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing task dirs")
    args = parser.parse_args()

    # Resolve env specs directory
    if args.env_specs:
        env_specs_dir = Path(args.env_specs)
    elif args.data_dir:
        # Backward compat: --data-dir pointed at the parent of go-specs/
        env_specs_dir = Path(args.data_dir)
    else:
        repo_root = Path(__file__).resolve().parent.parent
        env_specs_dir = repo_root / "data"

    instances = load_instances(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
        if not instances:
            print(f"Instance not found: {args.instance_id}", file=sys.stderr)
            sys.exit(1)

    if args.limit:
        instances = instances[:args.limit]

    print(f"Converting {len(instances)} instances to Harbor tasks in {output_dir} ...")

    ok = 0
    failed = 0
    for idx, inst in enumerate(instances, 1):
        iid = inst["instance_id"]
        try:
            task_dir = generate_task(inst, output_dir, env_specs_dir, overwrite=args.overwrite)
            print(f"[{idx}/{len(instances)}] OK   {iid}")
            ok += 1
        except Exception as e:
            print(f"[{idx}/{len(instances)}] FAIL {iid}: {e}")
            failed += 1

    print(f"\nDone. Success: {ok}  Failures: {failed}")


if __name__ == "__main__":
    main()
