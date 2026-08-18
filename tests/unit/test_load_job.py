"""Unit tests for stages.load_job — TDD (must fail before implementation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungs_agent.models.state import JobContext, WorkflowState
from bewerbungs_agent.stages.load_job import load_job


def test_load_job_valid_file(minimal_state: WorkflowState) -> None:
    """Valid job file → JobContext with non-empty raw_job_text."""
    result = load_job(minimal_state)
    assert "job_context" in result
    ctx = result["job_context"]
    assert isinstance(ctx, JobContext)
    assert len(ctx.raw_job_text) > 0


def test_load_job_no_company_file(minimal_state: WorkflowState) -> None:
    """No company_file in config → raw_company_text is None."""
    assert minimal_state.config.company_file is None
    result = load_job(minimal_state)
    assert result["job_context"].raw_company_text is None


def test_load_job_no_storyboard_file(minimal_state: WorkflowState) -> None:
    """No storyboard_file in config → raw_storyboard_text is None."""
    assert minimal_state.config.storyboard_file is None
    result = load_job(minimal_state)
    assert result["job_context"].raw_storyboard_text is None


def test_load_job_with_company_file(minimal_state: WorkflowState, tmp_path: Path) -> None:
    """company_file present → raw_company_text populated."""
    company_file = tmp_path / "company.md"
    company_file.write_text("# Acme Corp\nLeading data company.")
    config = minimal_state.config.model_copy(update={"company_file": company_file})
    state = minimal_state.model_copy(update={"config": config})
    result = load_job(state)
    assert result["job_context"].raw_company_text == "# Acme Corp\nLeading data company."


def test_load_job_missing_file(minimal_state: WorkflowState, tmp_path: Path) -> None:
    """Missing job_file → FileNotFoundError."""
    config = minimal_state.config.model_copy(
        update={"job_file": tmp_path / "nonexistent.md"}
    )
    state = minimal_state.model_copy(update={"config": config})
    with pytest.raises(FileNotFoundError):
        load_job(state)


def test_load_job_empty_file(minimal_state: WorkflowState, tmp_path: Path) -> None:
    """Empty job_file → ValueError."""
    empty = tmp_path / "empty.md"
    empty.write_text("")
    config = minimal_state.config.model_copy(update={"job_file": empty})
    state = minimal_state.model_copy(update={"config": config})
    with pytest.raises(ValueError):
        load_job(state)


def test_load_job_missing_company_file_raises(
    minimal_state: WorkflowState, tmp_path: Path
) -> None:
    """company_file specified but missing → FileNotFoundError."""
    config = minimal_state.config.model_copy(
        update={"company_file": tmp_path / "missing_company.md"}
    )
    state = minimal_state.model_copy(update={"config": config})
    with pytest.raises(FileNotFoundError):
        load_job(state)
