"""Tests for swebenchify.extractor -- patch extraction and splitting."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from swebenchify.extractor import (
    is_test_file,
    load_candidates,
    save_candidates,
    split_patch,
)
from swebenchify.models import CandidateInstance


class TestIsTestFile:
    """Test the test-file detection heuristic."""

    def test_tests_directory(self) -> None:
        assert is_test_file("tests/test_app.py") is True

    def test_test_directory(self) -> None:
        assert is_test_file("test/conftest.py") is True

    def test_e2e_directory(self) -> None:
        assert is_test_file("e2e/login.spec.ts") is True

    def test_regular_source_file(self) -> None:
        assert is_test_file("src/utils.py") is False

    def test_testing_directory(self) -> None:
        assert is_test_file("src/testing/helpers.py") is True

    def test_test_prefix_file(self) -> None:
        assert is_test_file("test_something.py") is True

    def test_test_suffix_file(self) -> None:
        assert is_test_file("something_test.py") is True

    def test_dot_test_file(self) -> None:
        assert is_test_file("component.test.tsx") is True

    def test_spec_file(self) -> None:
        assert is_test_file("component.spec.ts") is True

    def test_underscore_spec_file(self) -> None:
        assert is_test_file("app_spec.rb") is True

    def test_nested_tests_dir(self) -> None:
        assert is_test_file("src/mypackage/tests/test_core.py") is True

    def test_regular_nested_file(self) -> None:
        assert is_test_file("src/mypackage/core.py") is False

    def test_case_insensitive_directory(self) -> None:
        # Directories are compared case-insensitively
        assert is_test_file("Tests/test_app.py") is True

    def test_no_false_positive_on_partial_match(self) -> None:
        """A file in a directory named 'testing_utils' should NOT match
        since 'testing_utils' is not in the test dir set."""
        # But 'testing' IS in the set, so only exact component matches count.
        # 'testing_utils' as a component won't match 'testing'
        assert is_test_file("testing_utils/helper.py") is False

    def test_java_src_test_directory(self) -> None:
        assert is_test_file("src/test/java/com/example/FooTest.java") is True

    def test_java_src_main_directory(self) -> None:
        assert is_test_file("src/main/java/com/example/Foo.java") is False


class TestIsTestFileGo:
    """Go-specific test-file detection rules."""

    def test_go_test_file_suffix(self) -> None:
        assert is_test_file("pkg/foo_test.go") is True

    def test_go_inpackage_test(self) -> None:
        assert is_test_file("pkg/util/bar_test.go") is True

    def test_go_test_file_in_root(self) -> None:
        assert is_test_file("main_test.go") is True

    def test_go_regular_source(self) -> None:
        assert is_test_file("pkg/util/bar.go") is False

    def test_go_testdata_directory(self) -> None:
        assert is_test_file("pkg/testdata/fixture.json") is True

    def test_go_testdata_nested(self) -> None:
        assert is_test_file("cmd/kubectl/testdata/golden/out.txt") is True

    def test_go_testdata_in_middle(self) -> None:
        assert is_test_file("internal/testdata/schema.yaml") is True

    def test_go_false_positive_latest(self) -> None:
        # "latest" is not a test directory name (no substring matching)
        assert is_test_file("staging/latest.go") is False

    def test_go_false_positive_contest(self) -> None:
        assert is_test_file("internal/contest.go") is False

    def test_go_false_positive_attestation(self) -> None:
        assert is_test_file("attestation/verify.go") is False

    def test_go_false_positive_interested(self) -> None:
        assert is_test_file("interested/helper.go") is False

    def test_go_split_correctly_classifies_test_file(self) -> None:
        """_test.go files go into test patch, not gold patch."""
        import textwrap
        diff = textwrap.dedent("""\
            diff --git a/pkg/server/handler.go b/pkg/server/handler.go
            --- a/pkg/server/handler.go
            +++ b/pkg/server/handler.go
            @@ -1,2 +1,3 @@
             package server
            +// fixed
             func Handle() {}
            diff --git a/pkg/server/handler_test.go b/pkg/server/handler_test.go
            --- a/pkg/server/handler_test.go
            +++ b/pkg/server/handler_test.go
            @@ -1,2 +1,3 @@
             package server
            +// new test
             func TestHandle(t *testing.T) {}
        """)
        gold, test = split_patch(diff)
        assert gold is not None
        assert "handler.go" in gold
        assert "handler_test.go" not in gold
        assert test is not None
        assert "handler_test.go" in test


class TestIsTestFileRust:
    """Rust-specific test-file detection rules."""

    def test_rust_integration_tests_dir(self) -> None:
        assert is_test_file("tests/test_pool.rs") is True

    def test_rust_test_suffix_file(self) -> None:
        assert is_test_file("src/pool_test.rs") is True

    def test_rust_regular_source(self) -> None:
        assert is_test_file("src/pool.rs") is False

    def test_rust_lib_with_inline_tests(self) -> None:
        assert is_test_file("src/lib.rs") is False

    def test_rust_main_source(self) -> None:
        assert is_test_file("src/main.rs") is False

    def test_rust_benches_dir(self) -> None:
        assert is_test_file("benches/bench_pool.rs") is False

    def test_rust_testdata(self) -> None:
        assert is_test_file("testdata/fixture.toml") is True


class TestSplitPatch:
    """Test splitting a unified diff into gold and test patches."""

    SYNTHETIC_DIFF = textwrap.dedent("""\
        diff --git a/src/app.py b/src/app.py
        --- a/src/app.py
        +++ b/src/app.py
        @@ -1,3 +1,4 @@
         import os
        +import sys

         def main():
        diff --git a/tests/test_app.py b/tests/test_app.py
        --- a/tests/test_app.py
        +++ b/tests/test_app.py
        @@ -1,3 +1,5 @@
         import pytest
        +from app import main
        +

         def test_main():
    """)

    def test_split_separates_test_and_gold(self) -> None:
        gold, test = split_patch(self.SYNTHETIC_DIFF)
        assert gold is not None
        assert test is not None
        assert "src/app.py" in gold
        assert "tests/test_app.py" not in gold
        assert "tests/test_app.py" in test
        assert "src/app.py" not in test

    def test_gold_only_diff(self) -> None:
        diff = textwrap.dedent("""\
            diff --git a/src/core.py b/src/core.py
            --- a/src/core.py
            +++ b/src/core.py
            @@ -1,2 +1,3 @@
             x = 1
            +y = 2
             z = 3
        """)
        gold, test = split_patch(diff)
        assert gold is not None
        assert test is None
        assert "src/core.py" in gold

    def test_test_only_diff(self) -> None:
        diff = textwrap.dedent("""\
            diff --git a/tests/test_core.py b/tests/test_core.py
            --- a/tests/test_core.py
            +++ b/tests/test_core.py
            @@ -1,2 +1,3 @@
             def test_a():
            +    pass
                 assert True
        """)
        gold, test = split_patch(diff)
        assert gold is None
        assert test is not None
        assert "tests/test_core.py" in test

    def test_empty_diff(self) -> None:
        gold, test = split_patch("")
        assert gold is None
        assert test is None

    def test_none_diff(self) -> None:
        gold, test = split_patch(None)
        assert gold is None
        assert test is None


class TestCandidateInstanceJsonlRoundTrip:
    """Test JSONL serialization and deserialization of CandidateInstance."""

    @pytest.fixture
    def sample_candidates(self) -> list[CandidateInstance]:
        return [
            CandidateInstance(
                repo="pallets/flask",
                instance_id="pallets__flask-4045",
                pr_number=4045,
                base_commit="abc123",
                merge_commit="def456",
                patch="diff --git a/src/flask/app.py b/src/flask/app.py\n+x = 1\n",
                test_patch="diff --git a/tests/test_app.py b/tests/test_app.py\n+assert True\n",
                problem_statement="Fix the dot notation bug\nDetails here.",
                hints_text="Have you tried checking blueprints?",
                created_at="2021-05-13T21:32:41Z",
                resolved_issues=[4044],
            ),
            CandidateInstance(
                repo="django/django",
                instance_id="django__django-12345",
                pr_number=12345,
                base_commit="111aaa",
                merge_commit="222bbb",
                patch=None,
                test_patch=None,
                problem_statement=None,
                hints_text=None,
                created_at="2020-06-15T12:00:00Z",
                resolved_issues=[12340, 12341],
            ),
            CandidateInstance(
                repo="openshift/origin",
                instance_id="openshift__origin-99",
                pr_number=99,
                base_commit="ccc333",
                merge_commit="ddd444",
                patch="diff --git a/pkg/fix.go b/pkg/fix.go\n+fixed\n",
                test_patch="diff --git a/pkg/fix_test.go b/pkg/fix_test.go\n+test\n",
                problem_statement="OCPBUGS-1234 crash on startup",
                hints_text=None,
                created_at="2025-06-01T00:00:00Z",
                resolved_issues=[],
                resolved_jira_issues=["OCPBUGS-1234"],
            ),
        ]

    def test_round_trip(
        self, sample_candidates: list[CandidateInstance], tmp_path: Path
    ) -> None:
        path = str(tmp_path / "candidates.jsonl")
        save_candidates(sample_candidates, path)
        loaded = load_candidates(path)

        assert len(loaded) == len(sample_candidates)
        for original, restored in zip(sample_candidates, loaded):
            assert restored.repo == original.repo
            assert restored.instance_id == original.instance_id
            assert restored.pr_number == original.pr_number
            assert restored.base_commit == original.base_commit
            assert restored.merge_commit == original.merge_commit
            assert restored.patch == original.patch
            assert restored.test_patch == original.test_patch
            assert restored.problem_statement == original.problem_statement
            assert restored.hints_text == original.hints_text
            assert restored.created_at == original.created_at
            assert restored.resolved_issues == original.resolved_issues
            assert restored.resolved_jira_issues == original.resolved_jira_issues

    def test_jsonl_format(
        self, sample_candidates: list[CandidateInstance], tmp_path: Path
    ) -> None:
        """Each line should be valid JSON with expected fields."""
        path = str(tmp_path / "candidates.jsonl")
        save_candidates(sample_candidates, path)

        with open(path) as f:
            lines = [raw.strip() for raw in f if raw.strip()]

        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "instance_id" in data
            assert "patch" in data
            assert "test_patch" in data
            assert "problem_statement" in data

    def test_empty_list(self, tmp_path: Path) -> None:
        path = str(tmp_path / "empty.jsonl")
        save_candidates([], path)
        loaded = load_candidates(path)
        assert loaded == []


class TestMergedAtPropagation:
    """merged_at and link_confidence flow from CandidatePR → CandidateInstance."""

    def _make_pr(self, **overrides):
        from swebenchify.models import CandidatePR
        defaults = dict(
            repo="pallets/flask",
            pr_number=1,
            title="fix thing",
            body=None,
            base_commit="abc",
            merge_commit="def",
            diff_url="https://github.com/pallets/flask/pull/1.diff",
            resolved_issues=[1],
            created_at="2024-01-01T00:00:00Z",
            merged_at="2024-01-02T12:00:00Z",
            link_confidence=0.9,
        )
        defaults.update(overrides)
        return CandidatePR(**defaults)

    def test_merged_at_default_on_candidate_instance(self) -> None:
        from swebenchify.models import CandidateInstance
        inst = CandidateInstance(
            repo="r", instance_id="i", pr_number=1,
            base_commit="a", merge_commit="b",
            patch=None, test_patch=None,
            problem_statement=None, hints_text=None,
            created_at="2024-01-01T00:00:00Z",
        )
        assert inst.merged_at == ""
        assert inst.link_confidence == 0.0

    def test_merged_at_survives_jsonl_round_trip(self, tmp_path: Path) -> None:
        from swebenchify.models import CandidateInstance
        inst = CandidateInstance(
            repo="pallets/flask",
            instance_id="pallets__flask-1",
            pr_number=1,
            base_commit="abc",
            merge_commit="def",
            patch=None,
            test_patch=None,
            problem_statement=None,
            hints_text=None,
            created_at="2024-01-01T00:00:00Z",
            merged_at="2024-01-02T12:00:00Z",
            link_confidence=0.95,
        )
        path = str(tmp_path / "test.jsonl")
        save_candidates([inst], path)
        loaded = load_candidates(path)
        assert loaded[0].merged_at == "2024-01-02T12:00:00Z"
        assert loaded[0].link_confidence == 0.95


class TestRustInlineTestSplitting:
    """Test hunk-level splitting for Rust inline #[cfg(test)] blocks."""

    MIXED_RS_DIFF = textwrap.dedent("""\
        diff --git a/src/lib.rs b/src/lib.rs
        --- a/src/lib.rs
        +++ b/src/lib.rs
        @@ -10,3 +10,7 @@ impl Foo
         pub fn add(a: i32, b: i32) -> i32 {
        -    a + b + 1
        +    a + b
        +}
        +
        +pub fn multiply(a: i32, b: i32) -> i32 {
        +    a * b
         }
        @@ -50,3 +54,7 @@ mod tests
             use super::*;
        +    #[test]
        +    fn test_add() {
        +        assert_eq!(add(2, 3), 5);
        +    }
             // existing
         }
    """)

    def test_extracts_inline_test_hunk(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        backend = get_backend("rust")
        assert backend is not None
        new_gold, new_test = refine_patch_split(self.MIXED_RS_DIFF, None, backend)
        assert new_gold is not None
        assert new_test is not None
        assert "multiply" in new_gold
        assert "mod tests" not in new_gold
        assert "test_add" in new_test

    def test_preserves_existing_test_patch(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        existing_test = textwrap.dedent("""\
            diff --git a/tests/integration.rs b/tests/integration.rs
            --- a/tests/integration.rs
            +++ b/tests/integration.rs
            @@ -1,2 +1,4 @@
             use my_crate::add;
            +#[test]
            +fn test_integration() {}
        """)
        backend = get_backend("rust")
        assert backend is not None
        new_gold, new_test = refine_patch_split(self.MIXED_RS_DIFF, existing_test, backend)
        assert new_test is not None
        assert "integration.rs" in new_test
        assert "test_add" in new_test

    def test_gold_only_rs_unchanged(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        gold = textwrap.dedent("""\
            diff --git a/src/lib.rs b/src/lib.rs
            --- a/src/lib.rs
            +++ b/src/lib.rs
            @@ -10,3 +10,5 @@ impl Foo
             pub fn add(a: i32, b: i32) -> i32 {
            -    a + b + 1
            +    a + b
             }
        """)
        backend = get_backend("rust")
        assert backend is not None
        new_gold, new_test = refine_patch_split(gold, None, backend)
        assert new_gold is not None
        assert new_test is None
        assert "add" in new_gold

    def test_non_rs_file_unchanged(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        gold = textwrap.dedent("""\
            diff --git a/src/main.py b/src/main.py
            --- a/src/main.py
            +++ b/src/main.py
            @@ -1,2 +1,3 @@
             x = 1
            +y = 2
             z = 3
        """)
        backend = get_backend("rust")
        assert backend is not None
        new_gold, new_test = refine_patch_split(gold, None, backend)
        assert new_gold is not None
        assert new_test is None

    def test_no_backend_callback_passthrough(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        go_backend = get_backend("go")
        assert go_backend is not None
        new_gold, new_test = refine_patch_split(self.MIXED_RS_DIFF, None, go_backend)
        assert new_gold == self.MIXED_RS_DIFF
        assert new_test is None

    def test_cfg_test_in_context_line(self) -> None:
        from swebenchify.backends import get_backend, refine_patch_split
        gold = textwrap.dedent("""\
            diff --git a/src/parser.rs b/src/parser.rs
            --- a/src/parser.rs
            +++ b/src/parser.rs
            @@ -100,3 +100,3 @@ fn parse
             fn parse() -> Result<()> {
            -    todo!()
            +    Ok(())
             }
            @@ -200,4 +200,8 @@ fn helper
             #[cfg(test)]
             mod tests {
                 use super::*;
            +    #[test]
            +    fn test_parse() {
            +        assert!(parse().is_ok());
            +    }
             }
        """)
        backend = get_backend("rust")
        assert backend is not None
        new_gold, new_test = refine_patch_split(gold, None, backend)
        assert new_gold is not None
        assert new_test is not None
        assert "parse" in new_gold
        assert "test_parse" in new_test
