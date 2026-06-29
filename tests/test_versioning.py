"""Tests for swebenchify.versioning -- mechanical version detection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from swebenchify.versioning import (
    _from_cargo_toml,
    _from_package_json,
    _from_pyproject,
    _from_setup_cfg,
    _from_setup_py,
    _to_major_minor,
    detect_version,
)


class TestToMajorMinor:
    """Test _to_major_minor conversion."""

    def test_full_semver(self) -> None:
        assert _to_major_minor("2.3.1") == "2.3"

    def test_v_prefix(self) -> None:
        assert _to_major_minor("v1.0.0") == "1.0"

    def test_already_major_minor(self) -> None:
        assert _to_major_minor("3.14") == "3.14"

    def test_four_part_version(self) -> None:
        assert _to_major_minor("1.2.3.4") == "1.2"

    def test_single_number(self) -> None:
        # No major.minor pattern, returns as-is (stripped of v)
        assert _to_major_minor("42") == "42"


class TestFromPyproject:
    """Test _from_pyproject extraction."""

    def test_project_version(self) -> None:
        content = '[project]\nname = "foo"\nversion = "1.2.3"\n'
        assert _from_pyproject(content) == "1.2.3"

    def test_poetry_version(self) -> None:
        content = '[tool.poetry]\nname = "bar"\nversion = "4.5.6"\n'
        assert _from_pyproject(content) == "4.5.6"

    def test_project_takes_precedence_over_poetry(self) -> None:
        content = (
            '[project]\nname = "foo"\nversion = "1.0.0"\n\n'
            '[tool.poetry]\nname = "foo"\nversion = "2.0.0"\n'
        )
        assert _from_pyproject(content) == "1.0.0"

    def test_no_version(self) -> None:
        content = '[project]\nname = "foo"\n'
        assert _from_pyproject(content) is None

    def test_none_content(self) -> None:
        assert _from_pyproject(None) is None

    def test_single_quotes(self) -> None:
        content = "[project]\nname = 'foo'\nversion = '3.2.1'\n"
        assert _from_pyproject(content) == "3.2.1"


class TestFromSetupCfg:
    """Test _from_setup_cfg extraction."""

    def test_metadata_version(self) -> None:
        content = "[metadata]\nname = foo\nversion = 2.0.1\n"
        assert _from_setup_cfg(content) == "2.0.1"

    def test_no_version(self) -> None:
        content = "[metadata]\nname = foo\n"
        assert _from_setup_cfg(content) is None

    def test_none_content(self) -> None:
        assert _from_setup_cfg(None) is None

    def test_no_metadata_section(self) -> None:
        content = "[options]\ninstall_requires = requests\n"
        assert _from_setup_cfg(content) is None


class TestFromSetupPy:
    """Test _from_setup_py extraction."""

    def test_version_string(self) -> None:
        content = 'setup(\n    name="foo",\n    version="1.0",\n)\n'
        assert _from_setup_py(content) == "1.0"

    def test_single_quotes(self) -> None:
        content = "setup(\n    name='foo',\n    version='2.3.4',\n)\n"
        assert _from_setup_py(content) == "2.3.4"

    def test_no_version(self) -> None:
        content = 'setup(\n    name="foo",\n)\n'
        assert _from_setup_py(content) is None

    def test_none_content(self) -> None:
        assert _from_setup_py(None) is None


class TestFromPackageJson:
    """Test _from_package_json extraction."""

    def test_valid_json(self) -> None:
        content = json.dumps({"name": "my-pkg", "version": "3.1.4"})
        assert _from_package_json(content) == "3.1.4"

    def test_no_version_key(self) -> None:
        content = json.dumps({"name": "my-pkg"})
        assert _from_package_json(content) is None

    def test_bad_json(self) -> None:
        assert _from_package_json("{bad json") is None

    def test_none_content(self) -> None:
        assert _from_package_json(None) is None

    def test_empty_string(self) -> None:
        assert _from_package_json("") is None


class TestFromCargoToml:
    """Test _from_cargo_toml extraction."""

    def test_package_version(self) -> None:
        content = '[package]\nname = "my-crate"\nversion = "0.5.2"\n'
        assert _from_cargo_toml(content) == "0.5.2"

    def test_no_version(self) -> None:
        content = '[package]\nname = "my-crate"\n'
        assert _from_cargo_toml(content) is None

    def test_none_content(self) -> None:
        assert _from_cargo_toml(None) is None

    def test_no_package_section(self) -> None:
        content = '[dependencies]\nserde = "1.0"\n'
        assert _from_cargo_toml(content) is None


class TestDetectVersion:
    """Test detect_version with a real temp directory."""

    def test_detects_from_pyproject_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "test-pkg"\nversion = "2.3.1"\n'
            )
            result = detect_version(tmpdir)
            assert result == "2.3"

    def test_detects_from_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = Path(tmpdir) / "package.json"
            pkg_json.write_text(json.dumps({"name": "test", "version": "5.6.7"}))
            result = detect_version(tmpdir)
            assert result == "5.6"

    def test_returns_none_when_no_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = detect_version(tmpdir)
            assert result is None

    def test_priority_order(self) -> None:
        """pyproject.toml should take priority over setup.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "foo"\nversion = "1.0.0"\n'
            )
            setup_py = Path(tmpdir) / "setup.py"
            setup_py.write_text('setup(name="foo", version="9.9.9")\n')
            result = detect_version(tmpdir)
            assert result == "1.0"

    def test_falls_through_to_setup_py(self) -> None:
        """When pyproject.toml has no version, falls through to setup.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text('[project]\nname = "foo"\n')
            setup_py = Path(tmpdir) / "setup.py"
            setup_py.write_text('setup(name="foo", version="7.8.9")\n')
            result = detect_version(tmpdir)
            assert result == "7.8"
