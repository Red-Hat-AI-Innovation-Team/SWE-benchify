"""Tests for swebenchify.emitter -- JSONL emission (Stage 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebenchify.emitter import emit_dataset, load_dataset
from swebenchify.models import TaskInstance


def _make_instance(**overrides) -> TaskInstance:
    """Build a TaskInstance with sensible defaults."""
    defaults = {
        "repo": "owner/repo",
        "instance_id": "owner__repo-1",
        "base_commit": "abc123",
        "patch": "diff --git a/foo.py b/foo.py",
        "test_patch": "diff --git a/test_foo.py b/test_foo.py",
        "problem_statement": "Fix the bug in foo",
        "hints_text": "",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "FAIL_TO_PASS": json.dumps(["test_foo"]),
        "PASS_TO_PASS": json.dumps(["test_bar"]),
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


class TestEmitDataset:
    """Tests for emit_dataset writing valid JSONL."""

    def test_writes_repo_file(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        repo_file = tmp_path / "owner__repo-task-instances.jsonl"
        assert repo_file.exists()

    def test_writes_all_file(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path))
        all_file = tmp_path / "all-task-instances.jsonl"
        assert all_file.exists()

    def test_repo_file_contains_valid_jsonl(self, tmp_path: Path) -> None:
        instances = [
            _make_instance(instance_id="owner__repo-1"),
            _make_instance(instance_id="owner__repo-2"),
        ]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        repo_file = tmp_path / "owner__repo-task-instances.jsonl"
        lines = repo_file.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "instance_id" in obj
            assert "repo" in obj

    def test_each_line_has_expected_fields(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        repo_file = tmp_path / "owner__repo-task-instances.jsonl"
        obj = json.loads(repo_file.read_text().strip())
        expected_fields = {
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
        assert expected_fields <= set(obj.keys())

    def test_append_mode_for_all_file(self, tmp_path: Path) -> None:
        inst1 = [_make_instance(instance_id="owner__repo-1")]
        inst2 = [_make_instance(instance_id="owner__repo-2")]
        emit_dataset(inst1, str(tmp_path))
        emit_dataset(inst2, str(tmp_path))
        all_file = tmp_path / "all-task-instances.jsonl"
        lines = all_file.read_text().strip().splitlines()
        assert len(lines) == 2
        ids = [json.loads(line)["instance_id"] for line in lines]
        assert ids == ["owner__repo-1", "owner__repo-2"]

    def test_no_repo_slug_skips_repo_file(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path), repo_slug=None)
        # all-file should exist
        assert (tmp_path / "all-task-instances.jsonl").exists()
        # no repo-specific file
        jsonl_files = list(tmp_path.glob("*-task-instances.jsonl"))
        # only all-task-instances.jsonl
        assert all("all-task" in f.name for f in jsonl_files)

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "nested" / "output"
        instances = [_make_instance()]
        emit_dataset(instances, str(output_dir))
        assert output_dir.exists()
        assert (output_dir / "all-task-instances.jsonl").exists()

    def test_empty_instances_writes_empty_file(self, tmp_path: Path) -> None:
        emit_dataset([], str(tmp_path), repo_slug="owner__repo")
        repo_file = tmp_path / "owner__repo-task-instances.jsonl"
        assert repo_file.exists()
        assert repo_file.read_text() == ""


class TestLoadDataset:
    """Tests for load_dataset reading JSONL files."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        instances = [
            _make_instance(instance_id="owner__repo-1"),
            _make_instance(instance_id="owner__repo-2"),
        ]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        loaded = load_dataset(
            str(tmp_path / "owner__repo-task-instances.jsonl")
        )
        assert len(loaded) == 2
        assert loaded[0]["instance_id"] == "owner__repo-1"
        assert loaded[1]["instance_id"] == "owner__repo-2"

    def test_loaded_data_has_all_fields(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        loaded = load_dataset(
            str(tmp_path / "owner__repo-task-instances.jsonl")
        )
        obj = loaded[0]
        assert obj["repo"] == "owner/repo"
        assert obj["FAIL_TO_PASS"] == json.dumps(["test_foo"])
        assert obj["PASS_TO_PASS"] == json.dumps(["test_bar"])

    def test_load_empty_file(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        loaded = load_dataset(str(empty_file))
        assert loaded == []

    def test_load_file_with_blank_lines(self, tmp_path: Path) -> None:
        instances = [_make_instance()]
        emit_dataset(instances, str(tmp_path), repo_slug="owner__repo")
        # Append a blank line
        repo_file = tmp_path / "owner__repo-task-instances.jsonl"
        with open(repo_file, "a") as f:
            f.write("\n\n")
        loaded = load_dataset(str(repo_file))
        assert len(loaded) == 1


class TestLoadProductMap:
    """Tests for load_product_map()."""

    def test_returns_dict(self) -> None:
        from swebenchify.emitter import load_product_map
        result = load_product_map()
        assert isinstance(result, dict)

    def test_contains_kubectl_entry(self) -> None:
        from swebenchify.emitter import load_product_map
        m = load_product_map()
        assert "kubernetes/kubectl" in m
        assert m["kubernetes/kubectl"] == "OpenShift"

    def test_contains_etcd_entry(self) -> None:
        from swebenchify.emitter import load_product_map
        m = load_product_map()
        assert "etcd-io/etcd" in m

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        from swebenchify.emitter import load_product_map
        result = load_product_map(tmp_path / "nonexistent.json")
        assert result == {}

    def test_custom_path(self, tmp_path: Path) -> None:
        import json as _json
        from swebenchify.emitter import load_product_map
        p = tmp_path / "custom.json"
        p.write_text(_json.dumps({"my/repo": "MyProduct"}))
        result = load_product_map(p)
        assert result["my/repo"] == "MyProduct"


class TestSegmentationColumns:
    """Segmentation columns flow through emit_dataset via asdict()."""

    def test_segmentation_fields_in_jsonl(self, tmp_path: Path) -> None:
        inst = _make_instance(
            repo_language="go",
            product="OpenShift",
            n_fail_to_pass=2,
            patch_lines=50,
            files_touched=3,
            cross_file=True,
            env_spec_hash="abc" * 21,
            n_runs=3,
            flake_count=1,
            quarantined_tests=["pkg.TestFlaky"],
        )
        emit_dataset([inst], str(tmp_path), repo_slug="owner__repo")
        data = load_dataset(str(tmp_path / "owner__repo-task-instances.jsonl"))
        assert len(data) == 1
        row = data[0]
        assert row["repo_language"] == "go"
        assert row["product"] == "OpenShift"
        assert row["n_fail_to_pass"] == 2
        assert row["patch_lines"] == 50
        assert row["files_touched"] == 3
        assert row["cross_file"] is True
        assert row["n_runs"] == 3
        assert row["flake_count"] == 1
        assert row["quarantined_tests"] == ["pkg.TestFlaky"]

    def test_cross_file_false_when_one_file(self, tmp_path: Path) -> None:
        inst = _make_instance(files_touched=1, cross_file=False)
        emit_dataset([inst], str(tmp_path), repo_slug="owner__repo")
        data = load_dataset(str(tmp_path / "owner__repo-task-instances.jsonl"))
        assert data[0]["cross_file"] is False

    def test_defaults_are_sensible(self, tmp_path: Path) -> None:
        inst = _make_instance()
        emit_dataset([inst], str(tmp_path), repo_slug="owner__repo")
        data = load_dataset(str(tmp_path / "owner__repo-task-instances.jsonl"))
        row = data[0]
        assert row["repo_language"] is None
        assert row["product"] is None
        assert row["n_fail_to_pass"] == 0
        assert row["n_runs"] == 1
        assert row["quarantined_tests"] == []
