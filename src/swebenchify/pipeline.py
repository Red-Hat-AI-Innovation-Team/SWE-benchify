"""Pipeline controller / orchestrator.

Owns the stage sequencing for each repository, manages concurrency,
and handles resumption. See SPEC.md Sections 3.1 and 12.1.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from swebenchify.collector import collect_prs, load_prs, save_prs
from swebenchify.config import Config
from swebenchify.discovery import discover_environment, discover_go_environment
from swebenchify.dispatcher import CostTracker
from swebenchify.emitter import emit_dataset
from swebenchify.extractor import extract_all, load_candidates, save_candidates
from swebenchify.filters import apply_filters
from swebenchify.go_registry import GoSpecRegistry
from swebenchify.models import AnyEnvironmentSpec, EnvironmentSpec, GoEnvironmentSpec, QualityScore, Repository, TaskInstance
from swebenchify.sandbox import GoImageCache, SandboxConfig, is_docker_available
from swebenchify.validator import validate_instances
from swebenchify.versioning import detect_version
from swebenchify.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


async def run_pipeline(config: Config, resume: bool = False) -> None:
    """Run the full SWE-benchify pipeline for all configured repos."""
    # Initialise sandbox configuration from agent settings.
    sandbox = SandboxConfig(
        enabled=(config.agent.sandbox == "docker"),
        docker_image=config.agent.docker_image,
    )
    if sandbox.enabled:
        if is_docker_available():
            logger.info(
                "Docker sandboxing enabled (image: %s)", sandbox.docker_image
            )
        else:
            logger.warning(
                "Docker sandboxing requested but Docker is not available. "
                "Falling back to local execution."
            )
            sandbox = SandboxConfig(enabled=False)

    workspace_mgr = WorkspaceManager(config.output.dir + "/workspaces")
    cost_tracker = CostTracker()

    if not resume:
        all_file = Path(config.output.dir) / "all-task-instances.jsonl"
        if all_file.exists():
            all_file.unlink()

    semaphore = asyncio.Semaphore(config.pipeline.max_concurrent_repos)

    async def process_repo(repo_name: str) -> None:
        async with semaphore:
            token = config.github_tokens.get(repo_name, config.github_token)
            repo = Repository(full_name=repo_name, access_token=token)
            try:
                await run_repo_pipeline(
                    repo, config, workspace_mgr, cost_tracker, resume
                )
            except Exception as e:
                logger.error("Pipeline failed for %s: %s", repo_name, e)

    await asyncio.gather(*[process_repo(r) for r in config.repos])

    logger.info("Pipeline complete. %s", cost_tracker.summary())


async def run_repo_pipeline(
    repo: Repository,
    config: Config,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker,
    resume: bool = False,
) -> None:
    """Run the pipeline for a single repository."""
    output_dir = Path(config.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: PR Collection
    prs_file = output_dir / f"{repo.slug}-prs.jsonl"
    if resume and prs_file.exists():
        logger.info("Resuming: loading existing PRs from %s", prs_file)
        prs = load_prs(str(prs_file))
    else:
        logger.info("Stage 1: Collecting PRs for %s", repo.full_name)
        prs = collect_prs(
            repo,
            max_prs=config.pipeline.max_prs_per_repo,
            pr_after=config.pipeline.pr_after,
            pr_before=config.pipeline.pr_before,
        )
        save_prs(prs, str(prs_file))
    logger.info("  %d candidate PRs collected", len(prs))

    # Stage 2: Patch Extraction
    candidates_file = output_dir / f"{repo.slug}-candidates.jsonl"
    if resume and candidates_file.exists():
        logger.info(
            "Resuming: loading existing candidates from %s", candidates_file
        )
        candidates = load_candidates(str(candidates_file))
    else:
        logger.info("Stage 2: Extracting patches for %s", repo.full_name)
        candidates = extract_all(prs, github_token=repo.access_token)
        save_candidates(candidates, str(candidates_file))

    # Filter to viable candidates (has patch + test_patch + problem_statement)
    viable = [
        c
        for c in candidates
        if c.patch and c.test_patch and c.problem_statement
    ]
    logger.info(
        "  %d/%d viable candidates (have patch + test_patch + problem_statement)",
        len(viable),
        len(candidates),
    )

    if not viable:
        logger.warning("No viable candidates for %s", repo.full_name)
        return

    # Stage 3: Environment Discovery (per-version)
    logger.info("Stage 3: Discovering environment for %s", repo.full_name)

    # Ensure bare clone exists before version detection
    workspace_mgr.ensure_bare_clone(repo)
    bare_clone = workspace_mgr.bare_clone_path(repo)

    is_go_repo = repo.full_name in config.go_repos

    instance_versions: dict[str, str] = {}
    version_commits: dict[str, str] = {}  # version -> representative commit

    if is_go_repo:
        # For Go repos, all instances share a single spec keyed by env_spec_hash;
        # we use a sentinel version key "go" and discover once.
        for c in viable:
            instance_versions[c.instance_id] = "go"
        version_commits["go"] = viable[0].base_commit
    else:
        for c in viable:
            v = detect_version(str(bare_clone), c.base_commit) or "unknown"
            instance_versions[c.instance_id] = v
            if v not in version_commits:
                version_commits[v] = c.base_commit

    logger.info(f"  Detected {len(version_commits)} unique version(s): {list(version_commits.keys())}")

    # Discover environment for each unique version
    env_specs: dict[str, AnyEnvironmentSpec] = {}
    go_registry: GoSpecRegistry | None = None
    go_image_name: str | None = None

    if is_go_repo:
        go_registry = GoSpecRegistry(workspace_mgr.workspace_root)
        commit = version_commits["go"]
        try:
            go_spec, repo_version = await discover_go_environment(
                repo=repo,
                commit=commit,
                workspace_mgr=workspace_mgr,
                registry=go_registry,
                cost_tracker=cost_tracker,
                max_attempts=config.agent.max_attempts,
                max_turns=config.agent.env_discovery.max_turns,
                budget_usd=config.agent.env_discovery.budget_usd,
            )
            if go_spec:
                env_specs["go"] = go_spec
                logger.info(
                    "  Go env: go%s, test=%s, mode=%s",
                    go_spec.go_version, go_spec.test_cmd, go_spec.module_mode,
                )
                # Build / retrieve the per-(repo, era) Docker image
                image_cache = GoImageCache(workspace_mgr.workspace_root)
                go_image_name = image_cache.get_or_build(
                    repo=repo.full_name,
                    era_commit=commit,
                    spec=go_spec,
                    repo_path=str(bare_clone),
                )
                if go_image_name:
                    logger.info("  Go image: %s", go_image_name)
                else:
                    logger.warning("  Go image build failed; continuing without cached image")
            else:
                logger.error("Go environment discovery failed for %s", repo.full_name)
        except Exception as exc:
            logger.warning("Go env discovery error for %s: %s", repo.full_name, exc)
    else:
        for version, commit in version_commits.items():
            try:
                env_spec, repo_version = await discover_environment(
                    repo=repo,
                    commit=commit,
                    version=version,
                    workspace_mgr=workspace_mgr,
                    cost_tracker=cost_tracker,
                    max_attempts=config.agent.max_attempts,
                    max_turns=config.agent.env_discovery.max_turns,
                    budget_usd=config.agent.env_discovery.budget_usd,
                )
                if env_spec:
                    env_specs[version] = env_spec
                    logger.info(f"  v{version}: {env_spec.language} {env_spec.language_version}, test: {env_spec.test_cmd}")
                else:
                    logger.warning(f"  v{version}: env discovery failed, skipping instances at this version")
            except Exception as exc:
                logger.warning(f"  v{version}: env discovery error ({exc}), skipping")

    if not env_specs:
        logger.error(f"No environments discovered for {repo.full_name}")
        return

    # Filter viable to only versions with env specs
    viable = [c for c in viable if instance_versions.get(c.instance_id) in env_specs]

    # Stage 4: Instance Validation
    logger.info(
        "Stage 4: Validating %d instances for %s",
        len(viable),
        repo.full_name,
    )

    validation_results = await validate_instances(
        candidates=viable,
        env_specs=env_specs,
        repo=repo,
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_concurrent=config.pipeline.max_concurrent_validations,
        max_attempts=config.agent.max_attempts,
        max_turns=config.agent.validation.max_turns,
        budget_usd=config.agent.validation.budget_usd,
        instance_versions=instance_versions,
    )

    # Build TaskInstances from validated candidates
    from swebenchify.compat import snap_version, get_environment_setup_commit, get_go_version_string
    from swebenchify.go_registry import get_go_environment_setup_commit

    # Get environment_setup_commit from the bare clone
    bare_clone = workspace_mgr.bare_clone_path(repo)

    task_instances: list[TaskInstance] = []
    skipped_version = 0
    for candidate in viable:
        vr = validation_results.get(candidate.instance_id)
        if vr and vr.status == "valid":
            raw_version = instance_versions.get(candidate.instance_id, "unknown")

            if is_go_repo and go_registry is not None:
                go_spec = env_specs.get("go")
                version = get_go_version_string(go_spec, go_registry) if isinstance(go_spec, GoEnvironmentSpec) else raw_version
                env_commit = get_go_environment_setup_commit(str(bare_clone), go_spec, go_registry) if isinstance(go_spec, GoEnvironmentSpec) else None
            else:
                version = snap_version(repo.full_name, raw_version) or raw_version
                if version != raw_version:
                    logger.debug("  Snapped version %s -> %s for %s", raw_version, version, candidate.instance_id)
                env_commit = get_environment_setup_commit(repo.full_name, version, repo_path=str(bare_clone))

            task_instances.append(
                TaskInstance(
                    repo=candidate.repo,
                    instance_id=candidate.instance_id,
                    base_commit=candidate.base_commit,
                    patch=candidate.patch,
                    test_patch=candidate.test_patch,
                    problem_statement=candidate.problem_statement or "",
                    hints_text=candidate.hints_text or "",
                    created_at=candidate.created_at,
                    version=version,
                    FAIL_TO_PASS=json.dumps(vr.FAIL_TO_PASS),
                    PASS_TO_PASS=json.dumps(vr.PASS_TO_PASS),
                    environment_setup_commit=env_commit,
                    image_name=go_image_name if is_go_repo else None,
                    fix_merge_date=candidate.merged_at or None,
                    provenance="public_upstream",
                    link_confidence=candidate.link_confidence,
                )
            )

    logger.info(
        "  %d/%d instances validated successfully",
        len(task_instances),
        len(viable),
    )

    # Stage 4.5: Quality Evaluation
    if task_instances:
        from swebenchify.evaluator import evaluate_quality_batch

        logger.info(
            "Stage 4.5: Evaluating quality for %d instances",
            len(task_instances),
        )
        quality_scores = await evaluate_quality_batch(
            task_instances,
            cost_tracker=cost_tracker,
            max_turns=config.agent.quality_eval.max_turns,
            budget_usd=config.agent.quality_eval.budget_usd,
        )

        # Filter out excluded instances
        before_count = len(task_instances)
        task_instances = [
            inst for inst in task_instances
            if quality_scores.get(
                inst.instance_id,
                QualityScore(0, 0, "unknown", "unknown", "review", ""),
            ).recommendation != "exclude"
        ]
        excluded = before_count - len(task_instances)
        if excluded:
            logger.info(
                "  Quality eval excluded %d/%d instances",
                excluded,
                before_count,
            )

        # Log quality summary
        for inst_id, score in quality_scores.items():
            logger.info(
                "  %s: coherence=%d specificity=%d leakage=%s"
                " difficulty=%s -> %s",
                inst_id,
                score.coherence,
                score.specificity,
                score.leakage_risk,
                score.difficulty,
                score.recommendation,
            )

    # Stage 5: Quality Filtering
    logger.info("Stage 5: Applying quality filters")
    filtered = apply_filters(task_instances, config.filters)

    # Stage 6: Dataset Emission
    logger.info("Stage 6: Emitting dataset")
    emit_dataset(filtered, config.output.dir, repo_slug=repo.slug)
    logger.info("  %d instances emitted for %s", len(filtered), repo.full_name)
