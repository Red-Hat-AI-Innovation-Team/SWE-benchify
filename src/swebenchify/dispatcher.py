"""Agent dispatcher wrapper.

Manages Claude Code sessions via the Agent SDK for environment discovery
and instance validation. See SPEC.md Section 7.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from claude_code_sdk import ClaudeCodeOptions, ResultMessage, query

logger = logging.getLogger(__name__)

# Default tools the agent is allowed to use (SPEC.md Section 5.4).
DEFAULT_TOOLS = ["Bash", "Read", "Write", "Glob", "Grep"]


@dataclass
class AgentResult:
    """Outcome of a single Claude Code agent session.

    Attributes:
        status: One of ``"success"``, ``"error_max_turns"``,
            ``"error_max_budget_usd"``, ``"error_during_execution"``,
            or ``"error"`` (catch-all).
        output: Final text result returned by the agent, if any.
        session_id: Unique identifier for the agent session.
        cost_usd: Total cost of the session in US dollars.
        duration_ms: Wall-clock duration of the session in milliseconds.
        num_turns: Number of conversational turns the agent used.
        is_error: Whether the session ended in an error state.
    """

    status: str
    output: str | None
    session_id: str | None
    cost_usd: float | None
    duration_ms: int | None
    num_turns: int | None
    is_error: bool


async def run_agent_task(
    prompt: str,
    cwd: str | Path,
    tools: list[str] | None = None,
    max_turns: int = 50,
    budget_usd: float = 5.0,
    model: str | None = None,
) -> AgentResult:
    """Run a single Claude Code agent session and return its result.

    This is the core function that wraps the Claude Code SDK ``query()``
    call.  It builds :class:`ClaudeCodeOptions`, iterates through the
    messages produced by the agent, and extracts the final
    :class:`ResultMessage` into an :class:`AgentResult`.

    Args:
        prompt: The task-specific prompt for the agent.
        cwd: Working directory for the agent session.
        tools: List of allowed tools.  Defaults to :data:`DEFAULT_TOOLS`.
        max_turns: Maximum number of conversational turns.
        budget_usd: Maximum cost in US dollars for the session.
        model: Model identifier to use (``None`` for the SDK default).

    Returns:
        An :class:`AgentResult` summarising the session outcome.
    """
    if tools is None:
        tools = list(DEFAULT_TOOLS)

    extra_args: dict[str, str | None] = {
        "max-budget-usd": str(budget_usd),
    }

    options = ClaudeCodeOptions(
        cwd=str(cwd),
        allowed_tools=tools,
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,
        extra_args=extra_args,
    )

    logger.info(
        "Starting agent session: cwd=%s max_turns=%d budget_usd=%.2f",
        cwd,
        max_turns,
        budget_usd,
    )

    result_message: ResultMessage | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_message = message
    except Exception:
        logger.exception("Exception during agent query")
        return AgentResult(
            status="error",
            output=None,
            session_id=None,
            cost_usd=None,
            duration_ms=None,
            num_turns=None,
            is_error=True,
        )

    if result_message is None:
        logger.error("Agent session produced no ResultMessage")
        return AgentResult(
            status="error",
            output=None,
            session_id=None,
            cost_usd=None,
            duration_ms=None,
            num_turns=None,
            is_error=True,
        )

    # Map the SDK subtype to our status vocabulary.
    subtype = result_message.subtype
    known_subtypes = {
        "success",
        "error_max_turns",
        "error_max_budget_usd",
        "error_during_execution",
    }
    status = subtype if subtype in known_subtypes else "error"

    agent_result = AgentResult(
        status=status,
        output=result_message.result,
        session_id=result_message.session_id,
        cost_usd=result_message.total_cost_usd,
        duration_ms=result_message.duration_ms,
        num_turns=result_message.num_turns,
        is_error=result_message.is_error,
    )

    logger.info(
        "Agent session finished: status=%s cost_usd=%s turns=%s duration_ms=%s",
        agent_result.status,
        agent_result.cost_usd,
        agent_result.num_turns,
        agent_result.duration_ms,
    )

    return agent_result


async def run_agent_with_retry(
    prompt: str,
    cwd: str | Path,
    output_files: list[str],
    tools: list[str] | None = None,
    max_turns: int = 50,
    budget_usd: float = 5.0,
    max_attempts: int = 3,
    model: str | None = None,
) -> AgentResult:
    """Run an agent task with automatic retries and output-file validation.

    After each successful agent run the function checks that every path
    listed in *output_files* exists (relative to *cwd*).  If any file is
    missing, or the agent returned an error status, the function retries
    with an amended prompt describing the previous failure.

    Special retry behaviour:

    * ``error_max_turns`` -- retries with ``max_turns`` scaled by 1.5x.
    * ``error_max_budget_usd`` -- does **not** retry (budget exceeded is
      terminal); logs a warning and returns immediately.

    Args:
        prompt: The original task-specific prompt.
        cwd: Working directory for the agent session.
        output_files: Relative paths (inside *cwd*) that must exist on
            success.
        tools: Allowed tools (defaults to :data:`DEFAULT_TOOLS`).
        max_turns: Initial maximum turns.
        budget_usd: Cost budget per attempt.
        max_attempts: Maximum number of attempts (including the first).
        model: Model identifier (``None`` for the SDK default).

    Returns:
        The :class:`AgentResult` from the last attempt.
    """
    cwd_path = Path(cwd)
    current_max_turns = max_turns
    last_result: AgentResult | None = None
    previous_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        # Build the prompt, potentially amending with failure info.
        effective_prompt = prompt
        if previous_error is not None:
            effective_prompt = (
                f"{prompt}\n\n"
                f"IMPORTANT: A previous attempt (attempt {attempt - 1}) failed. "
                f"Here is what went wrong:\n{previous_error}\n"
                f"Please avoid the same mistake and try again."
            )

        logger.info(
            "Agent attempt %d/%d: max_turns=%d budget_usd=%.2f",
            attempt,
            max_attempts,
            current_max_turns,
            budget_usd,
        )

        result = await run_agent_task(
            prompt=effective_prompt,
            cwd=cwd,
            tools=tools,
            max_turns=current_max_turns,
            budget_usd=budget_usd,
            model=model,
        )
        last_result = result

        # Budget exceeded is terminal -- do not retry.
        if result.status == "error_max_budget_usd":
            logger.warning(
                "Agent exceeded budget (%.2f USD). Not retrying.", budget_usd
            )
            return result

        # On max-turns, increase the limit for the next attempt.
        if result.status == "error_max_turns":
            previous_error = (
                f"Agent exhausted the turn limit ({current_max_turns} turns)."
            )
            current_max_turns = math.ceil(current_max_turns * 1.5)
            logger.info(
                "Increasing max_turns to %d for next attempt.", current_max_turns
            )
            continue

        # On execution error, retry with error info.
        if result.is_error or result.status not in ("success",):
            previous_error = (
                f"Agent returned status '{result.status}'. "
                f"Output: {result.output or '(none)'}"
            )
            continue

        # Agent reported success -- verify output files exist.
        missing = [
            f for f in output_files if not (cwd_path / f).exists()
        ]
        if missing:
            previous_error = (
                f"Agent reported success but the following required output "
                f"files are missing: {missing}"
            )
            logger.warning("Missing output files: %s", missing)
            continue

        # All checks passed.
        logger.info("Agent succeeded on attempt %d.", attempt)
        return result

    logger.error("Agent failed after %d attempts.", max_attempts)
    assert last_result is not None  # At least one iteration ran.
    return last_result


class CostTracker:
    """Aggregate cost tracking across multiple agent sessions.

    Records per-session cost information and provides helpers to query
    totals grouped by pipeline stage or repository.
    """

    def __init__(self) -> None:
        self.sessions: list[dict] = []

    def record(
        self,
        stage: str,
        repo: str,
        result: AgentResult,
        instance_id: str | None = None,
    ) -> None:
        """Record the cost and metadata of an agent session.

        Args:
            stage: Pipeline stage name (e.g. ``"env-discovery"``,
                ``"validate"``).
            repo: Repository full name (``"owner/repo"``).
            result: The :class:`AgentResult` from the session.
            instance_id: Optional instance identifier for validation runs.
        """
        self.sessions.append(
            {
                "stage": stage,
                "repo": repo,
                "instance_id": instance_id,
                "cost_usd": result.cost_usd,
                "session_id": result.session_id,
                "duration_ms": result.duration_ms,
                "num_turns": result.num_turns,
                "status": result.status,
                "is_error": result.is_error,
            }
        )

    def total_cost(self) -> float:
        """Return the total cost across all recorded sessions."""
        return sum(s["cost_usd"] for s in self.sessions if s["cost_usd"] is not None)

    def cost_by_stage(self) -> dict[str, float]:
        """Return a mapping of stage name to aggregate cost."""
        totals: dict[str, float] = {}
        for s in self.sessions:
            if s["cost_usd"] is not None:
                totals[s["stage"]] = totals.get(s["stage"], 0.0) + s["cost_usd"]
        return totals

    def cost_by_repo(self) -> dict[str, float]:
        """Return a mapping of repository name to aggregate cost."""
        totals: dict[str, float] = {}
        for s in self.sessions:
            if s["cost_usd"] is not None:
                totals[s["repo"]] = totals.get(s["repo"], 0.0) + s["cost_usd"]
        return totals

    def summary(self) -> str:
        """Return a human-readable summary of costs.

        Includes total cost, per-stage breakdown, and per-repo breakdown.
        """
        lines: list[str] = []
        lines.append(f"Total cost: ${self.total_cost():.4f}")
        lines.append(f"Sessions:   {len(self.sessions)}")

        by_stage = self.cost_by_stage()
        if by_stage:
            lines.append("Cost by stage:")
            for stage, cost in sorted(by_stage.items()):
                lines.append(f"  {stage}: ${cost:.4f}")

        by_repo = self.cost_by_repo()
        if by_repo:
            lines.append("Cost by repo:")
            for repo, cost in sorted(by_repo.items()):
                lines.append(f"  {repo}: ${cost:.4f}")

        return "\n".join(lines)
