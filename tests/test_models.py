"""Tests for swebenchify.models — model definitions and fixture parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from swebenchify.models import (
    CandidateInstance,
    CandidatePR,
    EnvironmentSpec,
    Repository,
    RepoVersion,
    TaskInstance,
    ValidationResult,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FLASK_JSONL = FIXTURES_DIR / "swebench_flask.jsonl"

# The fields that every SWE-bench instance must have, matching the
# TaskInstance dataclass and the swebench.harness.constants schema.
SWEBENCH_REQUIRED_FIELDS = {
    "repo",
    "instance_id",
    "base_commit",
    "patch",
    "test_patch",
    "problem_statement",
    "hints_text",
    "created_at",
    "version",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "environment_setup_commit",
}

# instance_id format: {owner}__{repo}-{pr_number}
INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+__[A-Za-z0-9_-]+-\d+$")


class TestRepository:
    def test_properties(self) -> None:
        repo = Repository(full_name="pallets/flask")
        assert repo.owner == "pallets"
        assert repo.name == "flask"
        assert repo.slug == "pallets__flask"

    def test_access_token_default(self) -> None:
        repo = Repository(full_name="django/django")
        assert repo.access_token is None


class TestCandidatePR:
    def test_construction(self) -> None:
        pr = CandidatePR(
            repo="pallets/flask",
            pr_number=4045,
            title="Test PR",
            body="Fixes #123",
            base_commit="abc123",
            merge_commit="def456",
            diff_url="https://github.com/pallets/flask/pull/4045.diff",
            resolved_issues=[123],
            created_at="2021-05-13T21:32:41Z",
            merged_at="2021-05-14T10:00:00Z",
        )
        assert pr.pr_number == 4045
        assert pr.resolved_issues == [123]


class TestCandidateInstance:
    def test_default_resolved_issues(self) -> None:
        inst = CandidateInstance(
            repo="pallets/flask",
            instance_id="pallets__flask-4045",
            pr_number=4045,
            base_commit="abc",
            merge_commit="def",
            patch=None,
            test_patch=None,
            problem_statement=None,
            hints_text=None,
            created_at="2021-01-01T00:00:00Z",
        )
        assert inst.resolved_issues == []


class TestEnvironmentSpec:
    def test_defaults(self) -> None:
        spec = EnvironmentSpec(
            language="python",
            language_version="3.11",
            package_manager="pip",
            install_cmd="pip install -e .",
            test_cmd="pytest",
        )
        assert spec.pre_install == []
        assert spec.system_dependencies == []


class TestRepoVersion:
    def test_construction(self) -> None:
        rv = RepoVersion(repo="pallets/flask", commit="abc123", version="2.0")
        assert rv.version == "2.0"


class TestValidationResult:
    def test_defaults(self) -> None:
        vr = ValidationResult(status="valid")
        assert vr.FAIL_TO_PASS == []
        assert vr.PASS_TO_PASS == []
        assert vr.error_message is None

    def test_valid_with_tests(self) -> None:
        vr = ValidationResult(
            status="valid",
            FAIL_TO_PASS=["test_foo", "test_bar"],
            PASS_TO_PASS=["test_baz"],
        )
        assert len(vr.FAIL_TO_PASS) == 2


class TestTaskInstance:
    def test_environment_setup_commit_default(self) -> None:
        ti = TaskInstance(
            repo="pallets/flask",
            instance_id="pallets__flask-4045",
            base_commit="abc",
            patch="diff ...",
            test_patch="diff ...",
            problem_statement="Fix the bug",
            hints_text="",
            created_at="2021-01-01T00:00:00Z",
            version="2.0",
            FAIL_TO_PASS='["test_foo"]',
            PASS_TO_PASS='["test_bar"]',
        )
        assert ti.environment_setup_commit is None


class TestSWEbenchFlaskFixture:
    """Tests that load and verify the swebench_flask.jsonl fixture."""

    @pytest.fixture
    def flask_instances(self) -> list[dict]:
        """Load all instances from the Flask JSONL fixture."""
        instances = []
        with open(FLASK_JSONL) as f:
            for line in f:
                line = line.strip()
                if line:
                    instances.append(json.loads(line))
        return instances

    def test_fixture_has_11_instances(self, flask_instances: list[dict]) -> None:
        """The Flask fixture should contain exactly 11 instances."""
        assert len(flask_instances) == 11

    def test_all_instances_have_required_fields(self, flask_instances: list[dict]) -> None:
        """Every instance must have all SWE-bench required fields."""
        for instance in flask_instances:
            missing = SWEBENCH_REQUIRED_FIELDS - set(instance.keys())
            assert not missing, (
                f"Instance {instance.get('instance_id', '?')} missing fields: {missing}"
            )

    def test_instance_id_format(self, flask_instances: list[dict]) -> None:
        """instance_id must match {owner}__{repo}-{pr_number} format."""
        for instance in flask_instances:
            iid = instance["instance_id"]
            assert INSTANCE_ID_PATTERN.match(iid), (
                f"instance_id {iid!r} does not match expected pattern"
            )

    def test_instance_id_matches_repo(self, flask_instances: list[dict]) -> None:
        """instance_id prefix should match the repo slug."""
        for instance in flask_instances:
            repo = instance["repo"]
            iid = instance["instance_id"]
            expected_prefix = repo.replace("/", "__") + "-"
            assert iid.startswith(expected_prefix), (
                f"instance_id {iid!r} does not start with {expected_prefix!r}"
            )

    def test_all_repos_are_flask(self, flask_instances: list[dict]) -> None:
        """All instances in this fixture should be from pallets/flask."""
        for instance in flask_instances:
            assert instance["repo"] == "pallets/flask"

    def test_fail_to_pass_is_json_list(self, flask_instances: list[dict]) -> None:
        """FAIL_TO_PASS should be a JSON-encoded list of test identifiers."""
        for instance in flask_instances:
            ftp = instance["FAIL_TO_PASS"]
            parsed = json.loads(ftp)
            assert isinstance(parsed, list), (
                f"FAIL_TO_PASS for {instance['instance_id']} is not a list"
            )
            assert len(parsed) >= 1, (
                f"FAIL_TO_PASS for {instance['instance_id']} is empty"
            )

    def test_pass_to_pass_is_json_list(self, flask_instances: list[dict]) -> None:
        """PASS_TO_PASS should be a JSON-encoded list."""
        for instance in flask_instances:
            ptp = instance["PASS_TO_PASS"]
            parsed = json.loads(ptp)
            assert isinstance(parsed, list), (
                f"PASS_TO_PASS for {instance['instance_id']} is not a list"
            )

    def test_patches_are_nonempty(self, flask_instances: list[dict]) -> None:
        """Both patch and test_patch should be non-empty strings."""
        for instance in flask_instances:
            assert instance["patch"], (
                f"patch is empty for {instance['instance_id']}"
            )
            assert instance["test_patch"], (
                f"test_patch is empty for {instance['instance_id']}"
            )


class TestTaskInstanceFreshnessFields:
    """fix_merge_date, provenance, and link_confidence on TaskInstance."""

    def _make(self, **overrides) -> "TaskInstance":
        from swebenchify.models import TaskInstance
        defaults = dict(
            repo="pallets/flask",
            instance_id="pallets__flask-1",
            base_commit="abc",
            patch="diff\n",
            test_patch="diff\n",
            problem_statement="fix",
            hints_text="",
            created_at="2024-01-01T00:00:00Z",
            version="2.3",
            FAIL_TO_PASS="[]",
            PASS_TO_PASS="[]",
        )
        defaults.update(overrides)
        return TaskInstance(**defaults)

    def test_fix_merge_date_defaults_none(self) -> None:
        assert self._make().fix_merge_date is None

    def test_fix_merge_date_can_be_set(self) -> None:
        inst = self._make(fix_merge_date="2024-01-02T12:00:00Z")
        assert inst.fix_merge_date == "2024-01-02T12:00:00Z"

    def test_provenance_defaults_public_upstream(self) -> None:
        assert self._make().provenance == "public_upstream"

    def test_provenance_can_be_internal(self) -> None:
        assert self._make(provenance="internal").provenance == "internal"

    def test_link_confidence_defaults_zero(self) -> None:
        assert self._make().link_confidence == 0.0

    def test_link_confidence_can_be_set(self) -> None:
        assert self._make(link_confidence=0.9).link_confidence == 0.9

    def test_fields_in_asdict(self) -> None:
        import json
        from dataclasses import asdict
        inst = self._make(
            fix_merge_date="2024-01-02T12:00:00Z",
            provenance="public_upstream",
            link_confidence=1.0,
        )
        d = asdict(inst)
        serialised = json.dumps(d)
        assert "fix_merge_date" in d
        assert "provenance" in d
        assert "link_confidence" in d
        assert isinstance(serialised, str)
