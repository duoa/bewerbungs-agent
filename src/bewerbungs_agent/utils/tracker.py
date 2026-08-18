"""MLflow pipeline tracker — non-blocking, opt-in run metadata logging.

All public methods silently swallow exceptions so tracking failures never
abort the pipeline. mlflow is imported lazily and only when tracking is enabled.
"""

from __future__ import annotations

import hashlib
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bewerbungs_agent.config.models import ThinkingConfig, TrackingConfig


def _compute_prompt_hash(prompt_name: str) -> str:
    """Return a 16-char SHA-256 hex prefix of a prompt file's content.

    Reads the file at call time so changes are detected automatically.
    Returns "unknown" if the file is not found.
    """
    try:
        from bewerbungs_agent.utils.prompts import _PROMPTS_DIR

        content = (_PROMPTS_DIR / f"{prompt_name}.md").read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]
    except (FileNotFoundError, AttributeError, ImportError):
        return "unknown"


class PipelineTracker:
    """Non-blocking MLflow run tracker.

    Every method wraps its MLflow calls in try/except so a disk-full,
    permissions error, or any other MLflow failure silently emits a
    warning instead of aborting the pipeline.

    When tracking is disabled (config.enabled=False), all methods are
    immediate no-ops and mlflow is never imported.
    """

    def __init__(self, config: TrackingConfig, run_id: str) -> None:
        self._config = config
        self._run_id = run_id

        if config.enabled:
            try:
                import mlflow as _mlflow  # lazy import
                self._mlflow: Any = _mlflow
            except ImportError as exc:
                warnings.warn(
                    f"MLflow not installed; tracking disabled: {exc}",
                    stacklevel=2,
                )
                self._mlflow = None
        else:
            self._mlflow = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_run(self, job_title: str | None = None) -> None:
        """Start an MLflow run and log run-level parameters."""
        if self._mlflow is None:
            return
        try:
            from bewerbungs_agent.utils.llm_client import AnthropicLLMClient

            self._mlflow.set_tracking_uri(self._config.tracking_uri)
            self._mlflow.set_experiment(self._config.experiment_name)
            self._mlflow.start_run(run_name=self._run_id)
            self._mlflow.log_param("run_id", self._run_id)
            self._mlflow.log_param("model", AnthropicLLMClient.MODEL)
            if job_title:
                self._mlflow.log_param("job_title", job_title)
            self._mlflow.log_param(
                "thinking_enabled_global",
                str(self._config.enabled),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"MLflow tracking error in start_run (non-fatal): {exc}",
                stacklevel=2,
            )

    def log_stage(
        self,
        stage_name: str,
        model: str,
        thinking: ThinkingConfig,
        prompt_name: str,
        prompt_hash: str,
    ) -> None:
        """Log per-stage metadata as MLflow tags."""
        if self._mlflow is None:
            return
        try:
            self._mlflow.set_tag(
                f"stage.{stage_name}.thinking_enabled",
                str(thinking.enabled).lower(),
            )
            self._mlflow.set_tag(
                f"stage.{stage_name}.thinking_effort",
                thinking.effort.value,
            )
            self._mlflow.set_tag(f"stage.{stage_name}.prompt_name", prompt_name)
            self._mlflow.set_tag(f"stage.{stage_name}.prompt_hash", prompt_hash)
            self._mlflow.set_tag(f"stage.{stage_name}.model", model)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"MLflow tracking error in log_stage ({stage_name}) (non-fatal): {exc}",
                stacklevel=2,
            )

    def log_outputs(
        self,
        evidence_count: int,
        gaps_count: int,
        letter_char_count: int,
        validation_passes: int,
        rewrite_count: int,
    ) -> None:
        """Log final pipeline output metrics."""
        if self._mlflow is None:
            return
        try:
            self._mlflow.log_metric("evidence_count", evidence_count)
            self._mlflow.log_metric("gaps_count", gaps_count)
            self._mlflow.log_metric("letter_char_count", letter_char_count)
            self._mlflow.log_metric("validation_passes", validation_passes)
            self._mlflow.log_metric("rewrite_count", rewrite_count)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"MLflow tracking error in log_outputs (non-fatal): {exc}",
                stacklevel=2,
            )

    def log_langfuse_link(self, trace_id: str | None, trace_url: str | None) -> None:
        """Tag the active MLflow run with the Langfuse trace id and URL.

        One-way cross-link only (FR-021): nothing is written back to Langfuse.
        Failure is swallowed; the pipeline never aborts because of this.
        """
        if self._mlflow is None:
            return
        if not trace_id and not trace_url:
            return
        try:
            if trace_id:
                self._mlflow.set_tag("langfuse_trace_id", trace_id)
            if trace_url:
                self._mlflow.set_tag("langfuse_trace_url", trace_url)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"MLflow tracking error in log_langfuse_link (non-fatal): {exc}",
                stacklevel=2,
            )

    def end_run(self, status: str = "FINISHED") -> None:
        """End the active MLflow run."""
        if self._mlflow is None:
            return
        try:
            self._mlflow.end_run(status=status)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"MLflow tracking error in end_run (non-fatal): {exc}",
                stacklevel=2,
            )
