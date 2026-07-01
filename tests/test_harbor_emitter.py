"""Tests for swebenchify.harbor_emitter -- Harbor task directory emission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swebenchify.harbor_emitter import HarborTaskGenerator
from swebenchify.models import TaskInstance


def _make_instance(**overrides: Any) -> TaskInstance:
    defaults: dict[str, Any] = {
        "repo": "owner/repo",
        "instance_id": "owner__repo-1",
        "base_commit": "abc123",
        "patch": "diff --git a/foo.go b/foo.go\n--- a/foo.go\n+++ b/foo.go\n@@ -1 +1 @@\n-old\n+new",
        "test_patch": "diff --git a/foo_test.go b/foo_test.go",
        "problem_statement": "Fix the bug in foo",
        "hints_text": "",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "FAIL_TO_PASS": json.dumps(["TestFoo"]),
        "PASS_TO_PASS": json.dumps(["TestBar"]),
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


class TestHarborTaskGenerator:
    def test_generate_all_produces_task_directory(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        generated = gen.generate_all(tmp_path)
        assert generated == ["owner__repo-1"]
        task_dir = tmp_path / "owner__repo-1"
        assert task_dir.is_dir()

    def test_task_directory_structure(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        task_dir = tmp_path / "owner__repo-1"
        assert (task_dir / "instruction.md").exists()
        assert (task_dir / "task.toml").exists()
        assert (task_dir / "environment" / "Dockerfile").exists()
        assert (task_dir / "solution" / "solve.sh").exists()
        assert (task_dir / "tests" / "test.sh").exists()
        assert (task_dir / "tests" / "config.json").exists()
        assert (task_dir / "tests" / "test.patch").exists()

    def test_go_template_renders_without_error(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        generated = gen.generate_all(tmp_path)
        assert len(generated) == 1
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "go test -v" in test_sh
        assert "{test_command}" not in test_sh

    def test_python_template_renders_without_error(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="python")
        gen = HarborTaskGenerator(instances=[inst])
        generated = gen.generate_all(tmp_path)
        assert len(generated) == 1
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "pytest" in test_sh
        assert "{test_command}" not in test_sh

    def test_rendered_test_sh_has_literal_braces(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "|| {" in test_sh
        assert "results = {}" in test_sh
        assert "report = {" in test_sh
        assert "${test_name}" in test_sh

    def test_multiple_instances(self, tmp_path: Path) -> None:
        instances = [
            _make_instance(instance_id="owner__repo-1", repo_language="go"),
            _make_instance(instance_id="owner__repo-2", repo_language="python"),
        ]
        gen = HarborTaskGenerator(instances=instances)
        generated = gen.generate_all(tmp_path)
        assert len(generated) == 2
        assert (tmp_path / "owner__repo-1").is_dir()
        assert (tmp_path / "owner__repo-2").is_dir()

    def test_solve_sh_contains_patch(self, tmp_path: Path) -> None:
        patch = "diff --git a/x.go b/x.go\n+fixed"
        inst = _make_instance(repo_language="go", patch=patch)
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        solve = (tmp_path / "owner__repo-1" / "solution" / "solve.sh").read_text()
        assert patch in solve

    def test_dockerfile_contains_repo(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        dockerfile = (tmp_path / "owner__repo-1" / "environment" / "Dockerfile").read_text()
        assert "owner/repo" in dockerfile
        assert "abc123" in dockerfile

    def test_python_dockerfile_has_default_pip_install_without_env_spec(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="python")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        dockerfile = (tmp_path / "owner__repo-1" / "environment" / "Dockerfile").read_text()
        assert "pip install -e" in dockerfile
        assert "pip install pytest" in dockerfile

    def test_go_dockerfile_has_mod_download_without_env_spec(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="go")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        dockerfile = (tmp_path / "owner__repo-1" / "environment" / "Dockerfile").read_text()
        assert "go mod download" in dockerfile

    def test_java_template_renders_without_error(self, tmp_path: Path) -> None:
        inst = _make_instance(
            repo_language="java",
            test_patch="diff --git a/src/test/java/com/pkg/FooTest.java b/src/test/java/com/pkg/FooTest.java",
            FAIL_TO_PASS=json.dumps(["com.pkg.FooTest"]),
            PASS_TO_PASS=json.dumps(["com.pkg.BarTest"]),
        )
        gen = HarborTaskGenerator(instances=[inst])
        generated = gen.generate_all(tmp_path)
        assert len(generated) == 1
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "mvn test -B" in test_sh
        assert "{test_command}" not in test_sh

    def test_rust_template_renders_without_error(self, tmp_path: Path) -> None:
        inst = _make_instance(
            repo_language="rust",
            test_patch="diff --git a/src/lib.rs b/src/lib.rs",
            FAIL_TO_PASS=json.dumps(["module::test_foo"]),
            PASS_TO_PASS=json.dumps(["module::test_bar"]),
        )
        gen = HarborTaskGenerator(instances=[inst])
        generated = gen.generate_all(tmp_path)
        assert len(generated) == 1
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "cargo test" in test_sh
        assert "{test_command}" not in test_sh

    def test_java_test_command_has_mvn_test_with_scope(self, tmp_path: Path) -> None:
        inst = _make_instance(
            repo_language="java",
            test_patch="diff --git a/src/test/java/com/pkg/FooTest.java b/src/test/java/com/pkg/FooTest.java",
        )
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "mvn test -B" in test_sh

    def test_rust_test_command_is_cargo_test(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="rust")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "cargo test 2>&1" in test_sh

    def test_write_test_sh_routes_to_correct_template(self, tmp_path: Path) -> None:
        languages_and_markers = [
            ("go", "--- PASS:"),
            ("python", "PASSED"),
            ("java", "Tests run:"),
            ("rust", "test "),
        ]
        for lang, marker in languages_and_markers:
            inst = _make_instance(instance_id=f"owner__repo-{lang}", repo_language=lang)
            gen = HarborTaskGenerator(instances=[inst])
            gen.generate_all(tmp_path)
            test_sh = (tmp_path / f"owner__repo-{lang}" / "tests" / "test.sh").read_text()
            assert marker in test_sh, f"Expected '{marker}' in {lang} test.sh"

    def test_java_template_has_maven_parsing(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="java")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "Failures:" in test_sh
        assert "Errors:" in test_sh
        assert "BUILD FAILURE" in test_sh or "COMPILATION ERROR" in test_sh

    def test_rust_template_has_cargo_parsing(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="rust")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        test_sh = (tmp_path / "owner__repo-1" / "tests" / "test.sh").read_text()
        assert "... ok" in test_sh or "ok" in test_sh
        assert "FAILED" in test_sh
        assert "error[E" in test_sh or "error\\[E" in test_sh

    def test_java_dockerfile_has_mvn_resolve_without_env_spec(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="java")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        dockerfile = (tmp_path / "owner__repo-1" / "environment" / "Dockerfile").read_text()
        assert "mvn dependency:resolve" in dockerfile

    def test_rust_dockerfile_has_cargo_fetch_without_env_spec(self, tmp_path: Path) -> None:
        inst = _make_instance(repo_language="rust")
        gen = HarborTaskGenerator(instances=[inst])
        gen.generate_all(tmp_path)
        dockerfile = (tmp_path / "owner__repo-1" / "environment" / "Dockerfile").read_text()
        assert "cargo fetch" in dockerfile

    def test_empty_instances_returns_empty(self, tmp_path: Path) -> None:
        gen = HarborTaskGenerator(instances=[])
        generated = gen.generate_all(tmp_path)
        assert generated == []
