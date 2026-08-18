"""Unit tests for PipelineTracker — MLflow tracking utility.

Tests MUST be written and confirmed to FAIL before tracker.py is created.
All MLflow calls are mocked; no real tracking store is created.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bewerbungs_agent.config.models import (
    ThinkingConfig,
    ThinkingEffort,
    TrackingConfig,
)


class TestPipelineTracker:
    def _make_tracker(self, enabled: bool = True) -> object:
        from bewerbungs_agent.utils.tracker import PipelineTracker

        return PipelineTracker(TrackingConfig(enabled=enabled), run_id="test-run-001")

    def test_start_run_logs_required_params(self) -> None:
        """start_run() logs run_id and model as MLflow params."""
        tracker = self._make_tracker()

        mock_mlflow = MagicMock()
        tracker._mlflow = mock_mlflow
        tracker.start_run(job_title="Senior Engineer")

        logged = {args[0]: args[1] for args in (c.args for c in mock_mlflow.log_param.call_args_list)}
        assert logged.get("run_id") == "test-run-001"
        assert "model" in logged

    def test_start_run_silently_ignores_mlflow_error(self) -> None:
        """start_run() swallows exceptions — pipeline must not abort."""
        tracker = self._make_tracker()

        mock_mlflow = MagicMock()
        mock_mlflow.start_run.side_effect = PermissionError("disk full")
        tracker._mlflow = mock_mlflow

        # Must not raise
        tracker.start_run(job_title="Engineer")

    def test_log_stage_logs_tags_and_params(self) -> None:
        """log_stage() sets MLflow tags for thinking_enabled and prompt_hash."""
        tracker = self._make_tracker()

        mock_mlflow = MagicMock()
        tracker._mlflow = mock_mlflow

        tracker.log_stage(
            stage_name="plan_content",
            model="claude-sonnet-4-6",
            thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.high),
            prompt_name="system",
            prompt_hash="abc12345def67890",
        )

        set_tags = {args[0]: args[1] for args in (c.args for c in mock_mlflow.set_tag.call_args_list)}

        assert "stage.plan_content.thinking_enabled" in set_tags
        assert set_tags["stage.plan_content.thinking_enabled"] == "true"
        assert "stage.plan_content.prompt_hash" in set_tags
        assert set_tags["stage.plan_content.prompt_hash"] == "abc12345def67890"

    def test_log_outputs_logs_five_metrics(self) -> None:
        """log_outputs() calls mlflow.log_metric exactly 5 times with correct keys."""
        tracker = self._make_tracker()

        mock_mlflow = MagicMock()
        tracker._mlflow = mock_mlflow

        tracker.log_outputs(
            evidence_count=5,
            gaps_count=2,
            letter_char_count=2500,
            validation_passes=1,
            rewrite_count=0,
        )

        assert mock_mlflow.log_metric.call_count == 5
        metric_calls = {args[0]: args[1] for args in (c.args for c in mock_mlflow.log_metric.call_args_list)}
        assert metric_calls.get("evidence_count") == 5
        assert metric_calls.get("gaps_count") == 2
        assert metric_calls.get("letter_char_count") == 2500
        assert metric_calls.get("validation_passes") == 1
        assert metric_calls.get("rewrite_count") == 0

    def test_noop_when_tracking_disabled(self) -> None:
        """When tracking.enabled=False, no mlflow calls are made."""
        from bewerbungs_agent.utils.tracker import PipelineTracker

        tracker = PipelineTracker(TrackingConfig(enabled=False), run_id="x")

        # _mlflow should be None when disabled
        assert tracker._mlflow is None

        # All methods should be silent no-ops
        tracker.start_run(job_title="Test")
        tracker.log_stage(
            stage_name="extract_requirements",
            model="claude-sonnet-4-6",
            thinking=ThinkingConfig(),
            prompt_name="system",
            prompt_hash="abc123",
        )
        tracker.log_outputs(
            evidence_count=0,
            gaps_count=0,
            letter_char_count=0,
            validation_passes=0,
            rewrite_count=0,
        )
        tracker.end_run()
        # No assertion needed — if any of these raise, the test fails
