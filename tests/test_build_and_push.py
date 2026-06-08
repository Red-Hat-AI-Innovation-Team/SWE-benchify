"""Tests for scripts/build_and_push_images.py.

Docker subprocess calls are mocked so these tests run without a Docker daemon.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from swebenchify.models import GoEnvironmentSpec, compute_env_spec_hash

_script = Path(__file__).resolve().parent.parent / "scripts" / "build_and_push_images.py"
_spec_obj = importlib.util.spec_from_file_location("build_and_push_images", _script)
_mod = importlib.util.module_from_spec(_spec_obj)  # type: ignore[arg-type]
_spec_obj.loader.exec_module(_mod)  # type: ignore[union-attr]

_load_specs = _mod._load_specs
_image_name = _mod._image_name
_build_image = _mod._build_image
_push_image = _mod._push_image
main = _mod.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**overrides) -> GoEnvironmentSpec:
    defaults = dict(
        go_version="1.22",
        build_cmd="",
        test_cmd="",
        module_mode="modules",
        goflags="",
        system_dependencies=[],
    )
    defaults.update(overrides)
    return GoEnvironmentSpec(**defaults)


def _write_spec(specs_dir: Path, spec: GoEnvironmentSpec) -> str:
    """Write a spec JSON file named by its hash. Returns the hash."""
    h = compute_env_spec_hash(spec)
    data = {
        "language": spec.language,
        "go_version": spec.go_version,
        "build_cmd": spec.build_cmd,
        "test_cmd": spec.test_cmd,
        "module_mode": spec.module_mode,
        "goflags": spec.goflags,
        "system_dependencies": spec.system_dependencies,
    }
    (specs_dir / f"{h}.json").write_text(json.dumps(data))
    return h


def _write_instances(path: Path, instances: list[dict]) -> None:
    with open(path, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")


def _make_instance(
    repo: str = "owner/repo",
    instance_id: str = "owner__repo-1",
    env_spec_hash: str = "",
    image_name: str | None = None,
    repo_language: str = "go",
) -> dict:
    d: dict = {
        "repo": repo,
        "instance_id": instance_id,
        "env_spec_hash": env_spec_hash,
        "repo_language": repo_language,
    }
    if image_name is not None:
        d["image_name"] = image_name
    return d


# ---------------------------------------------------------------------------
# _load_specs
# ---------------------------------------------------------------------------

class TestLoadSpecs:
    def test_loads_valid_spec(self, tmp_path: Path) -> None:
        spec = _spec(go_version="1.23")
        h = _write_spec(tmp_path, spec)
        result = _load_specs(tmp_path)
        assert h in result
        assert result[h].go_version == "1.23"
        assert result[h].env_spec_hash == h

    def test_skips_misnamed_spec(self, tmp_path: Path) -> None:
        data = {
            "language": "go", "go_version": "1.23", "build_cmd": "",
            "test_cmd": "", "module_mode": "modules", "goflags": "",
            "system_dependencies": [],
        }
        (tmp_path / "wrong_name.json").write_text(json.dumps(data))
        result = _load_specs(tmp_path)
        assert len(result) == 0

    def test_loads_multiple_specs(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, _spec(go_version="1.22"))
        _write_spec(tmp_path, _spec(go_version="1.23"))
        result = _load_specs(tmp_path)
        assert len(result) == 2

    def test_ignores_non_json_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not a spec")
        _write_spec(tmp_path, _spec(go_version="1.22"))
        result = _load_specs(tmp_path)
        assert len(result) == 1

    def test_loads_vendored_spec(self, tmp_path: Path) -> None:
        spec = _spec(
            go_version="1.26.0",
            build_cmd="make all",
            test_cmd="make test",
            module_mode="vendored",
            goflags="-mod=vendor",
        )
        h = _write_spec(tmp_path, spec)
        result = _load_specs(tmp_path)
        assert result[h].module_mode == "vendored"
        assert result[h].goflags == "-mod=vendor"


# ---------------------------------------------------------------------------
# _image_name
# ---------------------------------------------------------------------------

class TestImageName:
    def test_basic(self) -> None:
        assert _image_name("kubernetes/kubernetes", "ff85eb477eda1234") == \
            "swebenchify-go-kubernetes__kubernetes-ff85eb477eda"

    def test_lowercases_repo(self) -> None:
        assert _image_name("Owner/Repo", "abc123def456") == \
            "swebenchify-go-owner__repo-abc123def456"


# ---------------------------------------------------------------------------
# _build_image
# ---------------------------------------------------------------------------

class TestBuildImage:
    @patch.object(_mod, "subprocess")
    def test_success(self, mock_subprocess) -> None:
        mock_subprocess.run.return_value.returncode = 0
        assert _build_image(_spec(), "test-image") is True
        cmd = mock_subprocess.run.call_args[0][0]
        assert cmd[0] == "docker"
        assert "build" in cmd
        assert "-t" in cmd
        assert "test-image" in cmd

    @patch.object(_mod, "subprocess")
    def test_failure(self, mock_subprocess) -> None:
        mock_subprocess.run.return_value.returncode = 1
        mock_subprocess.run.return_value.stderr = "build error"
        assert _build_image(_spec(), "test-image") is False


# ---------------------------------------------------------------------------
# _push_image
# ---------------------------------------------------------------------------

class TestPushImage:
    @patch.object(_mod, "subprocess")
    def test_success(self, mock_subprocess) -> None:
        mock_subprocess.run.return_value.returncode = 0
        assert _push_image("local", "remote") is True
        assert mock_subprocess.run.call_count == 2  # tag + push

    @patch.object(_mod, "subprocess")
    def test_tag_failure(self, mock_subprocess) -> None:
        mock_subprocess.run.return_value.returncode = 1
        mock_subprocess.run.return_value.stderr = "tag error"
        assert _push_image("local", "remote") is False
        assert mock_subprocess.run.call_count == 1  # only tag, no push

    @patch.object(_mod, "subprocess")
    def test_push_failure(self, mock_subprocess) -> None:
        results = iter([
            type("R", (), {"returncode": 0, "stderr": ""})(),  # tag ok
            type("R", (), {"returncode": 1, "stderr": "push err"})(),  # push fail
        ])
        mock_subprocess.run.side_effect = lambda *a, **kw: next(results)
        assert _push_image("local", "remote") is False


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

class TestMain:
    def test_dry_run_success(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = _spec(go_version="1.22")
        h = _write_spec(specs_dir, spec)
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(env_spec_hash=h),
            _make_instance(instance_id="owner__repo-2", env_spec_hash=h),
        ])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(specs_dir),
            "--dry-run",
        ])
        assert rc == 0

    def test_nothing_to_do(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(image_name="already-set", env_spec_hash="abc123"),
        ])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(specs_dir),
            "--dry-run",
        ])
        assert rc == 0

    def test_missing_spec_fails(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(env_spec_hash="nonexistent_hash"),
        ])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(specs_dir),
            "--dry-run",
        ])
        assert rc == 1

    def test_skips_python_instances(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(repo_language="python", env_spec_hash="some_hash"),
        ])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(specs_dir),
            "--dry-run",
        ])
        assert rc == 0

    def test_skips_instances_without_hash(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(env_spec_hash=""),
        ])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(specs_dir),
            "--dry-run",
        ])
        assert rc == 0

    def test_missing_specs_dir_fails(self, tmp_path: Path) -> None:
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [_make_instance()])
        rc = main([
            "--instances", str(instances_path),
            "--specs-dir", str(tmp_path / "nonexistent"),
        ])
        assert rc == 2

    def test_build_and_push(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = _spec(go_version="1.22")
        h = _write_spec(specs_dir, spec)
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [_make_instance(env_spec_hash=h)])
        with patch.object(_mod, "_build_image", return_value=True) as mock_build, \
             patch.object(_mod, "_push_image", return_value=True) as mock_push:
            rc = main([
                "--instances", str(instances_path),
                "--specs-dir", str(specs_dir),
                "--registry", "ghcr.io/test",
            ])
        assert rc == 0
        mock_build.assert_called_once()
        mock_push.assert_called_once()
        _, remote = mock_push.call_args[0]
        assert remote.startswith("ghcr.io/test/swebenchify-go-")

    def test_update_jsonl(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = _spec(go_version="1.22")
        h = _write_spec(specs_dir, spec)
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(instance_id="owner__repo-1", env_spec_hash=h),
            _make_instance(instance_id="owner__repo-2", env_spec_hash=h,
                           image_name="already-set"),
        ])
        with patch.object(_mod, "_build_image", return_value=True), \
             patch.object(_mod, "_push_image", return_value=True):
            rc = main([
                "--instances", str(instances_path),
                "--specs-dir", str(specs_dir),
                "--registry", "ghcr.io/test",
                "--update-jsonl",
            ])
        assert rc == 0
        updated = [json.loads(line) for line in instances_path.read_text().splitlines()]
        assert updated[0]["image_name"].startswith("ghcr.io/test/")
        assert updated[1]["image_name"] == "already-set"

    def test_build_failure_exits_nonzero(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = _spec(go_version="1.22")
        h = _write_spec(specs_dir, spec)
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [_make_instance(env_spec_hash=h)])
        with patch.object(_mod, "_build_image", return_value=False), \
             patch.object(_mod, "_push_image", return_value=True) as mock_push:
            rc = main([
                "--instances", str(instances_path),
                "--specs-dir", str(specs_dir),
                "--registry", "ghcr.io/test",
            ])
        assert rc == 1
        mock_push.assert_not_called()

    def test_groups_instances_by_hash(self, tmp_path: Path) -> None:
        """Multiple instances sharing the same env_spec_hash produce one image."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = _spec(go_version="1.22")
        h = _write_spec(specs_dir, spec)
        instances_path = tmp_path / "instances.jsonl"
        _write_instances(instances_path, [
            _make_instance(instance_id=f"owner__repo-{i}", env_spec_hash=h)
            for i in range(5)
        ])
        with patch.object(_mod, "_build_image", return_value=True) as mb, \
             patch.object(_mod, "_push_image", return_value=True):
            rc = main([
                "--instances", str(instances_path),
                "--specs-dir", str(specs_dir),
                "--registry", "ghcr.io/test",
            ])
        assert rc == 0
        mb.assert_called_once()
