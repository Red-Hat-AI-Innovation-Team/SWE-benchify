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

    _setup_logging()
    config = load_config(args.config)
    asyncio.run(run_pipeline(config, resume=args.resume))


def _setup_logging() -> None:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cmd_collect(args: argparse.Namespace) -> None:
    """Run Stage 1: PR collection only."""
    _setup_logging()
    config = load_config(args.config)
    from pathlib import Path

    from swebenchify.collector import collect_prs, load_prs
    from swebenchify.models import CandidatePR, Repository

    output_dir = Path(config.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import json
    from dataclasses import asdict

    total_repos = len(config.repos)
    for idx, repo_name in enumerate(config.repos, 1):
        token = config.github_tokens.get(repo_name, config.github_token)
        repo = Repository(full_name=repo_name, access_token=token)
        out_file = output_dir / f"{repo.slug}-prs.jsonl"

        existing_numbers: set[int] = set()
        if out_file.exists():
            existing_prs = load_prs(str(out_file))
            existing_numbers = {pr.pr_number for pr in existing_prs}
            print(
                f"[{idx}/{total_repos}] {repo.full_name}: resuming "
                f"({len(existing_numbers)} already collected)",
                flush=True,
            )
        else:
            print(f"[{idx}/{total_repos}] {repo.full_name}: collecting ...", flush=True)

        # Stream-write each new candidate as it's found so crashes don't lose progress
        mode = "a" if existing_numbers else "w"
        new_count = 0
        with open(out_file, mode) as out_f:
            def _write(pr: "CandidatePR", _f=out_f) -> None:
                nonlocal new_count
                _f.write(json.dumps(asdict(pr)) + "\n")
                _f.flush()
                new_count += 1

            collect_prs(
                repo,
                max_prs=config.pipeline.max_prs_per_repo,
                pr_after=config.pipeline.pr_after,
                pr_before=config.pipeline.pr_before,
                existing_pr_numbers=existing_numbers,
                on_candidate=_write,
                rh_jira_projects=config.rh_jira_projects,
            )

        total = len(existing_numbers) + new_count
        print(
            f"[{idx}/{total_repos}] {repo.full_name}: {new_count} new "
            f"({total} total) -> {out_file}",
            flush=True,
        )


def _cmd_extract(args: argparse.Namespace) -> None:
    """Run Stage 2: patch extraction from collected PRs."""
    _setup_logging()
    import json
    from dataclasses import asdict
    from pathlib import Path

    config = load_config(args.config)

    from swebenchify.collector import load_prs
    from swebenchify.extractor import extract_patches, load_candidates
    from swebenchify.models import Repository

    output_dir = Path(config.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for repo_name in config.repos:
        token = config.github_tokens.get(repo_name, config.github_token)
        repo = Repository(full_name=repo_name, access_token=token)

        prs_file = output_dir / f"{repo.slug}-prs.jsonl"
        candidates_file = output_dir / f"{repo.slug}-candidates.jsonl"

        if not prs_file.exists():
            print(
                f"{repo.full_name}: no PRs file ({prs_file}), run 'collect' first",
                file=sys.stderr,
            )
            continue

        prs = load_prs(str(prs_file))

        # Resume: skip already-extracted PR numbers
        already_done: set[int] = set()
        if candidates_file.exists():
            for c in load_candidates(str(candidates_file)):
                already_done.add(c.pr_number)
            if already_done:
                print(
                    f"{repo.full_name}: {len(already_done)} already extracted, "
                    f"{len(prs) - len(already_done)} remaining"
                )

        pending = [pr for pr in prs if pr.pr_number not in already_done]
        if not pending:
            print(f"{repo.full_name}: nothing new to extract", flush=True)
        else:
            mode = "a" if already_done else "w"
            with open(candidates_file, mode) as out_f:
                for i, pr in enumerate(pending):
                    instance = extract_patches(pr, github_token=token)
                    out_f.write(json.dumps(asdict(instance)) + "\n")
                    out_f.flush()
                    if (i + 1) % 50 == 0 or (i + 1) == len(pending):
                        print(
                            f"  {repo.full_name}: {i + 1}/{len(pending)} extracted",
                            flush=True,
                        )

        # Summary stats
        if candidates_file.exists():
            all_candidates = load_candidates(str(candidates_file))
            viable = sum(
                1 for c in all_candidates if c.patch and c.test_patch and c.problem_statement
            )
            print(
                f"{repo.full_name}: {len(all_candidates)} total, "
                f"{viable} viable (have patch + test_patch + problem_statement)",
                flush=True,
            )
        else:
            print(f"{repo.full_name}: 0 PRs, nothing to extract", flush=True)


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


def _cmd_remote_validate(args: argparse.Namespace) -> None:
    """Dispatch validation to GitHub Actions runners."""
    import json

    _setup_logging()
    config = load_config(args.config)

    from swebenchify.emitter import emit_dataset
    from swebenchify.extractor import load_candidates
    from swebenchify.filters import apply_go_filters
    from swebenchify.models import GoEnvironmentSpec
    from swebenchify.remote import build_task_instances, remote_validate

    candidates = load_candidates(args.input)
    viable = [c for c in candidates if c.patch and c.test_patch and c.problem_statement]
    if not viable:
        print("No viable candidates found")
        return

    env_spec = None
    if args.env_spec:
        with open(args.env_spec) as f:
            env_spec = GoEnvironmentSpec(**json.load(f))

    print(f"Dispatching {len(viable)} validations to GitHub Actions ...")

    results = remote_validate(
        candidates=viable,
        env_spec=env_spec,
        n_runs=args.n_runs,
        timeout=args.timeout,
    )

    task_instances = build_task_instances(viable, results, env_spec)
    print(f"{len(task_instances)}/{len(results)} instances valid")

    if not task_instances:
        print("No valid instances to emit")
        return

    is_go = isinstance(env_spec, GoEnvironmentSpec)
    if is_go:
        filtered = apply_go_filters(task_instances, config.filters, results)
    else:
        from swebenchify.filters import apply_filters
        filtered = apply_filters(task_instances, config.filters)

    if not filtered:
        print("All instances filtered out")
        return

    repo_slug = viable[0].repo.replace("/", "__")
    emit_dataset(filtered, config.output.dir, repo_slug=repo_slug)
    print(f"{len(filtered)} instances emitted to {config.output.dir}")


def _cmd_eval(args: argparse.Namespace) -> None:
    """Run evaluation: dispatch a coding agent to solve instances."""
    import asyncio
    import json

    config = load_config(args.config)

    from swebenchify.discovery import discover_environment
    from swebenchify.dispatcher import CostTracker
    from swebenchify.eval_harness import eval_instances, save_eval_results
    from swebenchify.models import Repository, TaskInstance
    from swebenchify.workspace import WorkspaceManager

    # Load instances
    instances: list[TaskInstance] = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(TaskInstance(**json.loads(line)))

    if args.max_instances:
        instances = instances[: args.max_instances]

    if not instances:
        print("No instances to evaluate")
        return

    repo_name = instances[0].repo
    token = config.github_tokens.get(repo_name, config.github_token)
    repo = Repository(full_name=repo_name, access_token=token)
    workspace_mgr = WorkspaceManager(config.output.dir + "/workspaces")
    cost_tracker = CostTracker()

    async def run() -> None:
        # Discover environment
        env_spec, _ = await discover_environment(
            repo=repo,
            commit=instances[0].base_commit,
            version=instances[0].version,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
        )
        if not env_spec:
            print("Environment discovery failed")
            return

        print(f"Evaluating {len(instances)} instances with model={args.model}")
        results = await eval_instances(
            instances,
            env_spec=env_spec,
            repo=repo,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
            model=args.model,
        )

        resolved = sum(1 for r in results if r.resolved)
        print(f"\nResults: {resolved}/{len(results)} resolved")
        for r in results:
            status = "PASS" if r.resolved else "FAIL"
            cost = f"${r.cost_usd:.2f}" if r.cost_usd else "N/A"
            print(f"  [{status}] {r.instance_id} (cost: {cost})")
            if r.error_message:
                print(f"         Error: {r.error_message}")

        print(f"\n{cost_tracker.summary()}")

        # Save results
        output_path = (
            args.output
            or f"{config.output.dir}/eval-{repo.slug}-{args.model}.jsonl"
        )
        save_eval_results(results, output_path)
        print(f"Results saved to {output_path}")

    asyncio.run(run())


def _cmd_ground_truth(args: argparse.Namespace) -> None:
    """Dispatch ground-truth sub-subcommands."""
    sub = args.gt_command
    if sub is None:
        print("Usage: swebenchify ground-truth {collect,extract,emit,run}", file=sys.stderr)
        sys.exit(1)
    print(f"ground-truth {sub}: Not yet implemented", file=sys.stderr)
    sys.exit(1)


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
    collect_parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Merge newly collected PRs with existing output instead of overwriting",
    )

    # extract
    extract_parser = subparsers.add_parser(
        "extract",
        help="Stage 2: Download patches and issue bodies from collected PRs",
    )
    _add_common_args(extract_parser)

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

    # remote-validate
    rv_parser = subparsers.add_parser(
        "remote-validate",
        help="Dispatch validation to GitHub Actions runners",
    )
    _add_common_args(rv_parser)
    rv_parser.add_argument("--input", "-i", required=True, help="Input candidates JSONL")
    rv_parser.add_argument("--env-spec", help="Path to GoEnvironmentSpec JSON file")
    rv_parser.add_argument("--n-runs", type=int, default=1, help="Flake quarantine runs")
    rv_parser.add_argument("--timeout", type=int, default=300, help="Per-validation timeout (seconds)")

    # eval
    eval_parser = subparsers.add_parser(
        "eval", help="Evaluate: run a coding agent on benchmark instances"
    )
    _add_common_args(eval_parser)
    eval_parser.add_argument(
        "--input", "-i", required=True, help="Input task instances JSONL file"
    )
    eval_parser.add_argument(
        "--model", default="haiku", help="Model to use (default: haiku)"
    )
    eval_parser.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Max instances to evaluate",
    )
    eval_parser.add_argument(
        "--output", "-o", default=None, help="Output eval results JSONL file"
    )

    # ground-truth
    gt_parser = subparsers.add_parser(
        "ground-truth",
        help="Ground truth initialization pipeline",
    )
    _add_common_args(gt_parser)
    gt_subparsers = gt_parser.add_subparsers(dest="gt_command", help="Ground truth sub-commands")

    gt_collect = gt_subparsers.add_parser("collect", help="Enumerate and normalize landed changes")
    _add_common_args(gt_collect)

    gt_extract = gt_subparsers.add_parser("extract", help="Extract patches, descriptions, and provenance")
    _add_common_args(gt_extract)

    gt_emit = gt_subparsers.add_parser("emit", help="Write JSONL output artifacts")
    _add_common_args(gt_emit)

    gt_run = gt_subparsers.add_parser("run", help="Run the full ground truth pipeline")
    _add_common_args(gt_run)

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
        "extract": _cmd_extract,
        "validate": _cmd_validate,
        "remote-validate": _cmd_remote_validate,
        "emit": _cmd_emit,
        "eval": _cmd_eval,
        "ground-truth": _cmd_ground_truth,
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
