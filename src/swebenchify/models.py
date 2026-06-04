"""Core domain model dataclasses for SWE-benchify.

Based on SPEC.md Section 4. These dataclasses represent the entities that
flow through the pipeline stages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class Repository:
    """A GitHub repository to process."""

    full_name: str  # "owner/repo"
    access_token: str | None = None

    @property
    def owner(self) -> str:
        return self.full_name.split("/")[0]

    @property
    def name(self) -> str:
        return self.full_name.split("/")[1]

    @property
    def slug(self) -> str:
        return self.full_name.replace("/", "__")


@dataclass
class CandidatePR:
    """A merged pull request that references at least one issue."""

    repo: str
    pr_number: int
    title: str
    body: str | None
    base_commit: str
    merge_commit: str
    diff_url: str
    resolved_issues: list[int]
    created_at: str
    merged_at: str
    link_confidence: float = 0.0  # confidence this PR resolves a tracked issue


@dataclass
class CandidateInstance:
    """A CandidatePR augmented with extracted patches and problem statement."""

    repo: str
    instance_id: str  # "{owner}__{repo}-{pr_number}"
    pr_number: int
    base_commit: str
    merge_commit: str
    patch: str | None  # gold patch
    test_patch: str | None  # test patch
    problem_statement: str | None
    hints_text: str | None
    created_at: str
    resolved_issues: list[int] = field(default_factory=list)


@dataclass
class EnvironmentSpec:
    """Build and test configuration discovered by the agent for a specific
    repository version."""

    language: str
    language_version: str
    package_manager: str
    install_cmd: str
    test_cmd: str
    pre_install: list[str] = field(default_factory=list)
    pip_packages: list[str] = field(default_factory=list)
    system_dependencies: list[str] = field(default_factory=list)


@dataclass
class GoEnvironmentSpec:
    """Build and test configuration for a Go repository version.

    Discovered by the Go branch of the Environment Discovery Agent.
    The ``env_spec_hash`` field is a stable content hash computed from all
    other fields — it acts as the cache key for per-``(repo, era)`` images
    and the spec registry.
    """

    language: str = "go"
    go_version: str = ""           # from go.mod "go" directive, e.g. "1.22"
    build_cmd: str = ""            # e.g. "make build" or "go build ./..."
    test_cmd: str = ""             # e.g. "go test ./pkg/..." or "make test"
    module_mode: str = "modules"   # "modules" | "vendored"
    goflags: str = ""              # e.g. "-mod=vendor"
    system_dependencies: list[str] = field(default_factory=list)
    env_spec_hash: str = ""        # populated by compute_env_spec_hash()


def compute_env_spec_hash(spec: GoEnvironmentSpec) -> str:
    """Return a stable SHA-256 hex digest of a GoEnvironmentSpec.

    All fields except ``env_spec_hash`` itself are included. The digest is
    computed over a sorted JSON serialisation so field insertion order does
    not affect the result.
    """
    payload = {
        "language": spec.language,
        "go_version": spec.go_version,
        "build_cmd": spec.build_cmd,
        "test_cmd": spec.test_cmd,
        "module_mode": spec.module_mode,
        "goflags": spec.goflags,
        "system_dependencies": sorted(spec.system_dependencies),
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode()).hexdigest()


# Type alias used by pipeline code that accepts either language's spec.
AnyEnvironmentSpec = EnvironmentSpec | GoEnvironmentSpec


@dataclass
class RepoVersion:
    """Version of a repository at a specific commit."""

    repo: str
    commit: str
    version: str


@dataclass
class ValidationResult:
    """Output of the validation agent for one candidate instance."""

    status: str  # "valid", "invalid", "error"
    FAIL_TO_PASS: list[str] = field(default_factory=list)
    PASS_TO_PASS: list[str] = field(default_factory=list)
    error_message: str | None = None
    compiled: bool = True          # False if the patch caused a build failure
    pre_fix_log: str | None = None   # raw test output before applying gold patch
    post_fix_log: str | None = None  # raw test output after applying gold patch
    n_runs: int = 1                  # number of validation runs performed
    flake_count: int = 0             # number of tests quarantined as flaky
    quarantined_tests: list[str] = field(default_factory=list)


@dataclass
class TaskInstance:
    """A validated benchmark instance conforming to the SWE-bench schema."""

    repo: str
    instance_id: str
    base_commit: str
    patch: str
    test_patch: str
    problem_statement: str
    hints_text: str
    created_at: str
    version: str
    FAIL_TO_PASS: str  # JSON-encoded list (SWE-bench convention)
    PASS_TO_PASS: str  # JSON-encoded list (SWE-bench convention)
    environment_setup_commit: str | None = None
    image_name: str | None = None  # Docker image used for Go validation


@dataclass
class QualityScore:
    """LLM judge quality assessment for a benchmark instance."""

    coherence: int  # 1-5: problem statement describes what the patch fixes
    specificity: int  # 1-5: problem statement is specific enough to act on
    leakage_risk: str  # "none", "low", "high"
    difficulty: str  # "easy", "medium", "hard"
    recommendation: str  # "include", "review", "exclude"
    reasoning: str


@dataclass
class EvalResult:
    """Result of running a coding agent on a benchmark instance."""

    instance_id: str
    resolved: bool
    agent_patch: str | None = None
    tests_passed: list[str] = field(default_factory=list)
    tests_failed: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    error_message: str | None = None
