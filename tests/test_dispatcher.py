"""Tests for swebenchify.dispatcher -- AgentResult and CostTracker.

These tests exercise the dataclasses and cost-tracking logic without
calling the Claude Code SDK (which requires a running Claude Code
instance).
"""

from __future__ import annotations

from swebenchify.dispatcher import AgentResult, CostTracker


def _make_result(
    *,
    status: str = "success",
    output: str | None = "done",
    session_id: str | None = "sess-001",
    cost_usd: float | None = 1.0,
    duration_ms: int | None = 5000,
    num_turns: int | None = 10,
    is_error: bool = False,
) -> AgentResult:
    """Helper to build an AgentResult with sensible defaults."""
    return AgentResult(
        status=status,
        output=output,
        session_id=session_id,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        num_turns=num_turns,
        is_error=is_error,
    )


# ---- AgentResult construction and field access ----


class TestAgentResult:
    def test_construction_success(self) -> None:
        r = _make_result()
        assert r.status == "success"
        assert r.output == "done"
        assert r.session_id == "sess-001"
        assert r.cost_usd == 1.0
        assert r.duration_ms == 5000
        assert r.num_turns == 10
        assert r.is_error is False

    def test_construction_error(self) -> None:
        r = _make_result(
            status="error_during_execution",
            output=None,
            session_id="sess-err",
            cost_usd=0.5,
            duration_ms=1200,
            num_turns=3,
            is_error=True,
        )
        assert r.status == "error_during_execution"
        assert r.is_error is True
        assert r.output is None

    def test_none_fields(self) -> None:
        r = AgentResult(
            status="error",
            output=None,
            session_id=None,
            cost_usd=None,
            duration_ms=None,
            num_turns=None,
            is_error=True,
        )
        assert r.cost_usd is None
        assert r.session_id is None
        assert r.duration_ms is None
        assert r.num_turns is None

    def test_all_status_values(self) -> None:
        """AgentResult accepts any status string."""
        for st in [
            "success",
            "error_max_turns",
            "error_max_budget_usd",
            "error_during_execution",
            "error",
        ]:
            r = _make_result(status=st)
            assert r.status == st


# ---- CostTracker ----


class TestCostTracker:
    def test_empty_tracker(self) -> None:
        tracker = CostTracker()
        assert tracker.total_cost() == 0.0
        assert tracker.cost_by_stage() == {}
        assert tracker.cost_by_repo() == {}
        assert tracker.sessions == []

    def test_record_and_total_cost(self) -> None:
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result(cost_usd=1.50))
        tracker.record("validate", "pallets/flask", _make_result(cost_usd=0.75))
        assert tracker.total_cost() == 2.25
        assert len(tracker.sessions) == 2

    def test_record_with_none_cost(self) -> None:
        """Sessions with cost_usd=None should not contribute to totals."""
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result(cost_usd=None))
        tracker.record("validate", "pallets/flask", _make_result(cost_usd=2.0))
        assert tracker.total_cost() == 2.0

    def test_cost_by_stage(self) -> None:
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result(cost_usd=1.0))
        tracker.record("env-discovery", "django/django", _make_result(cost_usd=2.0))
        tracker.record("validate", "pallets/flask", _make_result(cost_usd=0.5))
        tracker.record("validate", "django/django", _make_result(cost_usd=0.3))

        by_stage = tracker.cost_by_stage()
        assert by_stage == {"env-discovery": 3.0, "validate": 0.8}

    def test_cost_by_repo(self) -> None:
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result(cost_usd=1.0))
        tracker.record("validate", "pallets/flask", _make_result(cost_usd=0.5))
        tracker.record("env-discovery", "django/django", _make_result(cost_usd=2.0))

        by_repo = tracker.cost_by_repo()
        assert by_repo == {"pallets/flask": 1.5, "django/django": 2.0}

    def test_record_stores_metadata(self) -> None:
        tracker = CostTracker()
        result = _make_result(
            session_id="sess-42",
            duration_ms=8000,
            num_turns=15,
            status="success",
            is_error=False,
        )
        tracker.record(
            "validate", "pallets/flask", result, instance_id="pallets__flask-123"
        )

        assert len(tracker.sessions) == 1
        s = tracker.sessions[0]
        assert s["stage"] == "validate"
        assert s["repo"] == "pallets/flask"
        assert s["instance_id"] == "pallets__flask-123"
        assert s["session_id"] == "sess-42"
        assert s["duration_ms"] == 8000
        assert s["num_turns"] == 15
        assert s["status"] == "success"
        assert s["is_error"] is False

    def test_record_without_instance_id(self) -> None:
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result())
        assert tracker.sessions[0]["instance_id"] is None

    def test_summary_nonempty(self) -> None:
        tracker = CostTracker()
        tracker.record("env-discovery", "pallets/flask", _make_result(cost_usd=1.23))
        tracker.record("validate", "django/django", _make_result(cost_usd=0.45))

        summary = tracker.summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "1.6800" in summary  # total
        assert "env-discovery" in summary
        assert "validate" in summary
        assert "pallets/flask" in summary
        assert "django/django" in summary

    def test_summary_empty_tracker(self) -> None:
        tracker = CostTracker()
        summary = tracker.summary()
        assert isinstance(summary, str)
        assert "0.0000" in summary

    def test_summary_contains_session_count(self) -> None:
        tracker = CostTracker()
        tracker.record("validate", "a/b", _make_result(cost_usd=0.1))
        tracker.record("validate", "a/b", _make_result(cost_usd=0.2))
        tracker.record("validate", "a/b", _make_result(cost_usd=0.3))
        summary = tracker.summary()
        assert "3" in summary  # session count
