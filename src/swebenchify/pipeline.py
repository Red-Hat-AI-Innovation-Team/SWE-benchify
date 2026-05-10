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
from swebenchify.discovery import discover_environment
from swebenchify.dispatcher import CostTracker
from swebenchify.emitter import emit_dataset
from swebenchify.extractor import extract_all, load_candidates, save_candidates
from swebenchify.filters import apply_filters
from swebenchify.models import EnvironmentSpec, QualityScore, Repository, TaskInstance
from swebenchify.sandbox import SandboxConfig, is_docker_available
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
    instance_versions: dict[str, str] = {}
    version_commits: dict[str, str] = {}  # version -> representative commit
    for c in viable:
        v = detect_version(str(bare_clone), c.base_commit) or "unknown"
        instance_versions[c.instance_id] = v
        if v not in version_commits:
            version_commits[v] = c.base_commit

    logger.info(f"  Detected {len(version_commits)} unique version(s): {list(version_commits.keys())}")

    # Discover environment for each unique version
    env_specs: dict[str, EnvironmentSpec] = {}
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
        except Exception as e:
            logger.warning(f"  v{version}: env discovery error ({e}), skipping")

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
    task_instances: list[TaskInstance] = []
    for candidate in viable:
        vr = validation_results.get(candidate.instance_id)
        if vr and vr.status == "valid":
            version = instance_versions.get(candidate.instance_id, "unknown")
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
