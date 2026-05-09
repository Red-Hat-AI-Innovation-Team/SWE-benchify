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
