"""Tests for swebenchify.pipeline -- pipeline controller."""

from __future__ import annotations

import inspect

import pytest


class TestPipelineImports:
    """Verify the pipeline module imports correctly and exposes the right API."""

    def test_run_pipeline_importable(self) -> None:
        from swebenchify.pipeline import run_pipeline

        assert callable(run_pipeline)

    def test_run_repo_pipeline_importable(self) -> None:
        from swebenchify.pipeline import run_repo_pipeline

        assert callable(run_repo_pipeline)

    def test_run_pipeline_is_async(self) -> None:
        from swebenchify.pipeline import run_pipeline

        assert inspect.iscoroutinefunction(run_pipeline)

    def test_run_repo_pipeline_is_async(self) -> None:
        from swebenchify.pipeline import run_repo_pipeline

        assert inspect.iscoroutinefunction(run_repo_pipeline)

    def test_pipeline_imports_all_stages(self) -> None:
        """The pipeline module should import from all stage modules."""
        import swebenchify.pipeline as pipeline_mod

        # Verify the module references functions from each stage
        source = inspect.getsource(pipeline_mod)
        assert "collect_prs" in source
        assert "extract_all" in source
        assert "discover_environment" in source
        assert "validate_instances" in source
        assert "apply_filters" in source
        assert "emit_dataset" in source

    def test_run_pipeline_accepts_resume_param(self) -> None:
        from swebenchify.pipeline import run_pipeline

        sig = inspect.signature(run_pipeline)
        assert "resume" in sig.parameters

    def test_run_repo_pipeline_accepts_resume_param(self) -> None:
        from swebenchify.pipeline import run_repo_pipeline

        sig = inspect.signature(run_repo_pipeline)
        assert "resume" in sig.parameters


class TestCLIRunCommand:
    """Verify the CLI run command has the --resume flag."""

    def test_run_parser_has_resume_flag(self) -> None:
        from swebenchify.cli import build_parser

        parser = build_parser()
        # Parse with the run subcommand and --resume
        args = parser.parse_args(["run", "--resume"])
        assert args.resume is True

    def test_run_parser_resume_default_false(self) -> None:
        from swebenchify.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.resume is False
