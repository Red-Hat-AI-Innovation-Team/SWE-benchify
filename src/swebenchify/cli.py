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
    """Run Stage 1: PR collection."""
    config = load_config(args.config)
    # TODO: implement PR collection
    raise NotImplementedError(
        f"PR collection not yet implemented. "
        f"Config loaded with {len(config.repos)} repo(s)."
    )


def _cmd_validate(args: argparse.Namespace) -> None:
    """Run Stage 4: instance validation."""
    config = load_config(args.config)
    # TODO: implement instance validation
    raise NotImplementedError(
        f"Instance validation not yet implemented. "
        f"Config loaded with {len(config.repos)} repo(s)."
    )


def _cmd_emit(args: argparse.Namespace) -> None:
    """Run Stage 6: dataset emission."""
    config = load_config(args.config)
    # TODO: implement dataset emission
    raise NotImplementedError(
        f"Dataset emission not yet implemented. "
        f"Config loaded with {len(config.repos)} repo(s)."
    )


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

    # emit
    emit_parser = subparsers.add_parser(
        "emit", help="Stage 6: Emit JSONL dataset"
    )
    _add_common_args(emit_parser)

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
