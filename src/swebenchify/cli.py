"""CLI entry point for SWE-benchify.

Provides the ``swebenchify`` command with subcommands for running the
pipeline or individual stages.
"""

from __future__ import annotations

import argparse
import sys

from swebenchify.config import load_config


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by all subcommands."""
    parser.add_argument(
        "-c",
        "--config",
        default="swebenchify.yaml",
        help="Path to the YAML config file (default: swebenchify.yaml)",
    )


def _cmd_run(args: argparse.Namespace) -> None:
    """Run the full pipeline."""
    import asyncio

    from swebenchify.pipeline import run_pipeline

    config = load_config(args.config)
    asyncio.run(run_pipeline(config, resume=args.resume))


def _cmd_collect(args: argparse.Namespace) -> None:
    """Run Stage 1: PR collection only."""
    config = load_config(args.config)
    from pathlib import Path

    from swebenchify.collector import collect_prs, save_prs
    from swebenchify.models import Repository

    output_dir = Path(config.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for repo_name in config.repos:
        token = config.github_tokens.get(repo_name, config.github_token)
        repo = Repository(full_name=repo_name, access_token=token)
        prs = collect_prs(
            repo,
            max_prs=config.pipeline.max_prs_per_repo,
            pr_after=config.pipeline.pr_after,
            pr_before=config.pipeline.pr_before,
        )
        out_file = output_dir / f"{repo.slug}-prs.jsonl"
        save_prs(prs, str(out_file))
        print(f"{repo.full_name}: {len(prs)} candidate PRs -> {out_file}")


def _cmd_validate(args: argparse.Namespace) -> None:
    """Run Stages 3-4: environment discovery + instance validation."""
    import asyncio

    config = load_config(args.config)

    from swebenchify.dispatcher import CostTracker
    from swebenchify.discovery import discover_environment
    from swebenchify.extractor import load_candidates
    from swebenchify.models import Repository
    from swebenchify.validator import validate_instance
    from swebenchify.workspace import WorkspaceManager

    if not args.input:
        print("Error: --input is required for validate", file=sys.stderr)
        sys.exit(1)

    # Load candidates and run validation
    candidates = load_candidates(args.input)
    viable = [c for c in candidates if c.patch and c.test_patch and c.problem_statement]
    if not viable:
        print("No viable candidates found")
        return

    # Determine repo from candidates
    repo_name = viable[0].repo
    token = config.github_tokens.get(repo_name, config.github_token)
    repo = Repository(full_name=repo_name, access_token=token)
    workspace_mgr = WorkspaceManager(config.output.dir + "/workspaces")
    cost_tracker = CostTracker()

    async def run():
        # Simple: single env discovery + validate all
        env_spec, repo_version = await discover_environment(
            repo=repo, commit=viable[0].base_commit, version="default",
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
        )
        if not env_spec:
            print("Environment discovery failed")
            return

        import json

        results = {}
        for c in viable:
            vr = await validate_instance(
                candidate=c, env_spec=env_spec, repo=repo,
                workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            )
            results[c.instance_id] = vr
            status_str = f"{vr.status}: F2P={len(vr.FAIL_TO_PASS)} P2P={len(vr.PASS_TO_PASS)}"
            print(f"  {c.instance_id}: {status_str}")

        valid_count = sum(1 for v in results.values() if v.status == "valid")
        print(f"\n{valid_count}/{len(results)} instances valid")
        print(cost_tracker.summary())

    asyncio.run(run())


def _cmd_emit(args: argparse.Namespace) -> None:
    """Run Stages 5-6: filter + emit."""
    import json

    config = load_config(args.config)

    from swebenchify.emitter import emit_dataset
    from swebenchify.filters import apply_filters
    from swebenchify.models import TaskInstance

    if not args.input:
        print("Error: --input is required for emit", file=sys.stderr)
        sys.exit(1)

    # Load TaskInstances from JSONL
    instances = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                instances.append(TaskInstance(**data))

    filtered = apply_filters(instances, config.filters)

    # Determine repo slug from instances
    repo_slug = None
    if filtered:
        repo_slug = filtered[0].instance_id.rsplit("-", 1)[0]

    emit_dataset(filtered, config.output.dir, repo_slug=repo_slug)
    print(f"{len(filtered)}/{len(instances)} instances emitted to {config.output.dir}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="swebenchify",
        description="Transform GitHub repositories into SWE-bench-compatible benchmarks",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run the full pipeline")
    _add_common_args(run_parser)
    run_parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume from existing stage outputs instead of re-running",
    )

    # collect
    collect_parser = subparsers.add_parser(
        "collect", help="Stage 1: Collect merged PRs with linked issues"
    )
    _add_common_args(collect_parser)

    # validate
    validate_parser = subparsers.add_parser(
        "validate", help="Stage 4: Validate candidate instances"
    )
    _add_common_args(validate_parser)
    validate_parser.add_argument("--input", "-i", help="Input candidates JSONL file")

    # emit
    emit_parser = subparsers.add_parser(
        "emit", help="Stage 6: Emit JSONL dataset"
    )
    _add_common_args(emit_parser)
    emit_parser.add_argument("--input", "-i", help="Input validated instances JSONL file")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the swebenchify CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "run": _cmd_run,
        "collect": _cmd_collect,
        "validate": _cmd_validate,
        "emit": _cmd_emit,
    }

    try:
        commands[args.command](args)
    except NotImplementedError as e:
        print(f"Not implemented: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
