"""Core domain model dataclasses for SWE-benchify.

Based on SPEC.md Section 4. These dataclasses represent the entities that
flow through the pipeline stages.
"""

from __future__ import annotations

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
    system_dependencies: list[str] = field(default_factory=list)


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
