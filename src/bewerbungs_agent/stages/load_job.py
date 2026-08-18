"""Stage: load_job — load job description, company info, and storyboard files."""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.io.loader import load_markdown
from bewerbungs_agent.models.state import JobContext, WorkflowState


def load_job(state: WorkflowState) -> dict[str, Any]:
    """Load job context from files specified in state.config.

    Returns:
        Partial state update: ``{"job_context": JobContext}``.

    Raises:
        FileNotFoundError: If any specified file does not exist.
        ValueError: If job_file is empty.
    """
    config = state.config

    if not config.job_file.exists():
        raise FileNotFoundError(f"Job file not found: {config.job_file}")

    raw_job_text = load_markdown(config.job_file)
    if not raw_job_text.strip():
        raise ValueError(f"Job file is empty: {config.job_file}")

    raw_company_text: str | None = None
    if config.company_file is not None:
        if not config.company_file.exists():
            raise FileNotFoundError(f"Company file not found: {config.company_file}")
        raw_company_text = load_markdown(config.company_file)

    raw_storyboard_text: str | None = None
    if config.storyboard_file is not None:
        if not config.storyboard_file.exists():
            raise FileNotFoundError(
                f"Storyboard file not found: {config.storyboard_file}"
            )
        raw_storyboard_text = load_markdown(config.storyboard_file)

    return {
        "job_context": JobContext(
            raw_job_text=raw_job_text,
            raw_company_text=raw_company_text,
            raw_storyboard_text=raw_storyboard_text,
        )
    }
