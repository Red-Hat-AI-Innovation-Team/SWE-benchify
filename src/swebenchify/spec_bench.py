"""Docker spec generation benchmark (Phase 1.1).

Compares agent-generated environment specs against SWE-bench's
manually authored MAP_REPO_VERSION_TO_SPECS entries.

Ground truth format (from swebench.harness.constants):
    MAP_REPO_VERSION_TO_SPECS[repo_name][version] = {
        "python": "3.9",           # Python version
        "packages": "pytest",      # conda/requirements file ref
        "install": "pip install -e .",  # install command
        "pip_packages": [...],     # pinned pip dependencies (optional)
        "test_cmd": "pytest -rA",  # test command
        "pre_install": [...],      # pre-install bash commands (optional)
    }
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

GROUND_TRUTH_FIELDS = ("python", "install", "test_cmd", "pip_packages", "pre_install", "packages")


@dataclass
class FieldScore:
    """Score for a single field comparison."""

    field: str
    match: bool
    generated: str | None
    expected: str | None
    detail: str = ""


@dataclass
class SpecScore:
    """Comparison result for one (repo, version) spec."""

    repo: str
    version: str
    field_scores: list[FieldScore] = field(default_factory=list)
    overall: float = 0.0

    @property
    def matched_fields(self) -> int:
        return sum(1 for f in self.field_scores if f.match)

    @property
    def total_fields(self) -> int:
        return len(self.field_scores)

    def summary(self) -> str:
        lines = [f"{self.repo} v{self.version}: {self.overall:.0%} ({self.matched_fields}/{self.total_fields} fields)"]
        for fs in self.field_scores:
            status = "MATCH" if fs.match else "MISS"
            lines.append(f"  [{status}] {fs.field}: {fs.detail}")
        return "\n".join(lines)


@dataclass
class BenchmarkResult:
    """Aggregate result for a spec generation benchmark run."""

    scores: list[SpecScore] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.overall for s in self.scores) / len(self.scores)

    @property
    def field_match_rates(self) -> dict[str, float]:
        rates: dict[str, list[bool]] = {}
        for score in self.scores:
            for fs in score.field_scores:
                rates.setdefault(fs.field, []).append(fs.match)
        return {f: sum(v) / len(v) for f, v in rates.items() if v}

    def summary(self) -> str:
        lines = [
            f"Spec Benchmark: {len(self.scores)} versions, overall score: {self.overall_score:.1%}",
            "",
            "Per-field match rates:",
        ]
        for f, rate in sorted(self.field_match_rates.items()):
            lines.append(f"  {f}: {rate:.0%}")
        lines.append("")
        for s in self.scores:
            lines.append(s.summary())
        return "\n".join(lines)


def load_ground_truth(repo: str) -> dict[str, dict]:
    """Load ground truth specs for a repo from SWE-bench constants.

    Returns {version: spec_dict} or empty dict if repo not found.
    """
    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
    except ImportError:
        logger.error("swebench not installed — cannot load ground truth")
        return {}

    return dict(MAP_REPO_VERSION_TO_SPECS.get(repo, {}))


def normalize_python_version(v: str | None) -> str | None:
    """Normalize a Python version string for comparison.

    "3.11.4" -> "3.11", "3.9.0" -> "3.9", "3" -> "3"
    """
    if v is None:
        return None
    v = v.strip()
    m = re.match(r"(\d+\.\d+)", v)
    return m.group(1) if m else v


def normalize_install_cmd(cmd: str | None) -> str | None:
    """Normalize an install command for comparison.

    Strips whitespace, normalizes pip invocations.
    """
    if cmd is None:
        return None
    cmd = cmd.strip()
    cmd = re.sub(r"\s+", " ", cmd)
    cmd = cmd.replace("pip install", "python -m pip install")
    cmd = re.sub(r"python -m python -m", "python -m", cmd)
    return cmd


def normalize_test_cmd(cmd: str | None) -> str | None:
    """Normalize a test command for comparison.

    Extracts the core command, ignoring flags that don't affect semantics.
    """
    if cmd is None:
        return None
    cmd = cmd.strip()
    cmd = re.sub(r"\s+", " ", cmd)
    return cmd


def extract_test_runner(cmd: str | None) -> str | None:
    """Extract the test runner name from a test command.

    "pytest -rA --tb=no" -> "pytest"
    "python -m pytest tests/ -x" -> "pytest"
    "tox --current-env -epy39 -v --" -> "tox"
    """
    if cmd is None:
        return None
    cmd = cmd.strip()
    if "pytest" in cmd:
        return "pytest"
    if "tox" in cmd:
        return "tox"
    if "unittest" in cmd:
        return "unittest"
    parts = cmd.split()
    return parts[0] if parts else None


def normalize_pip_packages(pkgs: list[str] | None) -> set[str]:
    """Normalize pip package specs to {name: version} for comparison.

    Returns a set of lowercase package names (ignoring versions for
    the name-match check).
    """
    if not pkgs:
        return set()
    names = set()
    for pkg in pkgs:
        name = re.split(r"[=<>!~]", pkg.strip())[0].lower().replace("-", "_")
        if name:
            names.add(name)
    return names


def compare_python_version(generated: str | None, expected: str | None) -> FieldScore:
    """Compare Python versions."""
    gen = normalize_python_version(generated)
    exp = normalize_python_version(expected)
    match = gen == exp
    return FieldScore(
        field="python",
        match=match,
        generated=gen,
        expected=exp,
        detail=f"gen={gen} exp={exp}" if not match else f"{gen}",
    )


def compare_install_cmd(generated: str | None, expected: str | None) -> FieldScore:
    """Compare install commands.

    Checks for functional equivalence: both use pip editable install,
    or both use the same install method.
    """
    gen = normalize_install_cmd(generated)
    exp = normalize_install_cmd(expected)

    if gen is None and exp is None:
        return FieldScore(field="install", match=True, generated=gen, expected=exp, detail="both None")

    if gen is None or exp is None:
        return FieldScore(field="install", match=False, generated=gen, expected=exp, detail=f"gen={gen} exp={exp}")

    exact_match = gen == exp
    if exact_match:
        return FieldScore(field="install", match=True, generated=gen, expected=exp, detail="exact match")

    gen_editable = "-e " in gen or "--editable" in gen
    exp_editable = "-e " in exp or "--editable" in exp
    both_pip = "pip install" in gen and "pip install" in exp

    functional_match = both_pip and gen_editable == exp_editable
    return FieldScore(
        field="install",
        match=functional_match,
        generated=gen,
        expected=exp,
        detail="functional match (both pip editable)" if functional_match else f"gen={gen} exp={exp}",
    )


def compare_test_cmd(generated: str | None, expected: str | None) -> FieldScore:
    """Compare test commands.

    Primary check: same test runner (pytest, tox, etc.)
    Secondary: flag compatibility.
    """
    gen_runner = extract_test_runner(generated)
    exp_runner = extract_test_runner(expected)

    if gen_runner is None and exp_runner is None:
        return FieldScore(field="test_cmd", match=True, generated=generated, expected=expected, detail="both None")

    runner_match = gen_runner == exp_runner
    gen_norm = normalize_test_cmd(generated)
    exp_norm = normalize_test_cmd(expected)
    exact_match = gen_norm == exp_norm

    return FieldScore(
        field="test_cmd",
        match=runner_match,
        generated=generated,
        expected=expected,
        detail="exact match" if exact_match else (
            f"same runner ({gen_runner})" if runner_match else f"different runners: gen={gen_runner} exp={exp_runner}"
        ),
    )


def compare_pip_packages(
    generated: list[str] | None, expected: list[str] | None
) -> FieldScore:
    """Compare pip package lists.

    Checks package name overlap (ignoring version pinning).
    Match if >=80% of expected packages are present in generated.
    """
    gen_names = normalize_pip_packages(generated)
    exp_names = normalize_pip_packages(expected)

    if not exp_names and not gen_names:
        return FieldScore(
            field="pip_packages", match=True,
            generated=str(generated), expected=str(expected),
            detail="both empty",
        )

    if not exp_names:
        return FieldScore(
            field="pip_packages", match=True,
            generated=str(gen_names), expected="(none)",
            detail="no expected packages to match",
        )

    if not gen_names:
        return FieldScore(
            field="pip_packages", match=False,
            generated="(none)", expected=str(exp_names),
            detail=f"missing all {len(exp_names)} expected packages",
        )

    overlap = gen_names & exp_names
    coverage = len(overlap) / len(exp_names)
    missing = exp_names - gen_names
    extra = gen_names - exp_names

    match = coverage >= 0.8
    detail_parts = [f"{len(overlap)}/{len(exp_names)} expected packages covered ({coverage:.0%})"]
    if missing:
        detail_parts.append(f"missing: {sorted(missing)}")
    if extra:
        detail_parts.append(f"extra: {sorted(extra)}")

    return FieldScore(
        field="pip_packages",
        match=match,
        generated=str(sorted(gen_names)),
        expected=str(sorted(exp_names)),
        detail="; ".join(detail_parts),
    )


def compare_pre_install(
    generated: list[str] | None, expected: list[str] | None
) -> FieldScore:
    """Compare pre-install commands."""
    gen = generated or []
    exp = expected or []

    if not gen and not exp:
        return FieldScore(field="pre_install", match=True, generated="[]", expected="[]", detail="both empty")

    match = set(gen) == set(exp)
    return FieldScore(
        field="pre_install",
        match=match,
        generated=str(gen),
        expected=str(exp),
        detail="match" if match else f"gen={gen} exp={exp}",
    )


def score_spec(
    generated: dict,
    expected: dict,
    repo: str,
    version: str,
) -> SpecScore:
    """Score a generated spec against the ground truth.

    Args:
        generated: Agent-generated spec dict. Expected keys match our
            EnvironmentSpec: language_version, install_cmd, test_cmd,
            plus optional pip_packages, pre_install.
        expected: SWE-bench ground truth spec dict with keys:
            python, install, test_cmd, pip_packages, pre_install, packages.
        repo: Repository name (e.g. "pallets/flask").
        version: Version string (e.g. "2.3").

    Returns:
        SpecScore with per-field comparison results.
    """
    field_scores = []

    gen_python = generated.get("language_version") or generated.get("python")
    exp_python = expected.get("python")
    field_scores.append(compare_python_version(gen_python, exp_python))

    gen_install = generated.get("install_cmd") or generated.get("install")
    exp_install = expected.get("install")
    field_scores.append(compare_install_cmd(gen_install, exp_install))

    gen_test = generated.get("test_cmd")
    exp_test = expected.get("test_cmd")
    field_scores.append(compare_test_cmd(gen_test, exp_test))

    gen_pip = generated.get("pip_packages")
    exp_pip = expected.get("pip_packages")
    field_scores.append(compare_pip_packages(gen_pip, exp_pip))

    gen_pre = generated.get("pre_install")
    exp_pre = expected.get("pre_install")
    field_scores.append(compare_pre_install(gen_pre, exp_pre))

    overall = sum(1 for f in field_scores if f.match) / len(field_scores) if field_scores else 0.0

    return SpecScore(
        repo=repo,
        version=version,
        field_scores=field_scores,
        overall=overall,
    )


def benchmark_specs(
    generated_specs: dict[str, dict],
    repo: str,
    ground_truth: dict[str, dict] | None = None,
) -> BenchmarkResult:
    """Run the spec benchmark for a repository.

    Args:
        generated_specs: {version: generated_spec_dict} from agent discovery.
        repo: Repository name.
        ground_truth: Optional override for ground truth specs.
            If None, loaded from swebench constants.

    Returns:
        BenchmarkResult with per-version scores.
    """
    if ground_truth is None:
        ground_truth = load_ground_truth(repo)

    if not ground_truth:
        logger.warning("No ground truth available for %s", repo)
        return BenchmarkResult()

    scores = []
    for version in sorted(ground_truth.keys()):
        if version not in generated_specs:
            logger.warning("No generated spec for %s v%s — skipping", repo, version)
            continue
        score = score_spec(
            generated=generated_specs[version],
            expected=ground_truth[version],
            repo=repo,
            version=version,
        )
        scores.append(score)

    return BenchmarkResult(scores=scores)


def env_spec_to_bench_dict(env_spec) -> dict:
    """Convert an EnvironmentSpec dataclass to a dict suitable for benchmarking.

    Bridges between our EnvironmentSpec model and the comparison functions
    which expect plain dicts with SWE-bench-compatible keys.
    """
    from swebenchify.models import EnvironmentSpec

    if isinstance(env_spec, EnvironmentSpec):
        return {
            "python": env_spec.language_version,
            "install": env_spec.install_cmd,
            "test_cmd": env_spec.test_cmd,
            "pre_install": env_spec.pre_install,
            "language_version": env_spec.language_version,
            "install_cmd": env_spec.install_cmd,
        }
    if isinstance(env_spec, dict):
        return env_spec
    raise TypeError(f"Expected EnvironmentSpec or dict, got {type(env_spec)}")
