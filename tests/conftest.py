"""Shared pytest fixtures for all test layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LengthMode,
    MergedConfig,
    WritingMode,
)
from bewerbungs_agent.models.state import WorkflowState

# ---------------------------------------------------------------------------
# Paths to example fixture data
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent / "data" / "examples"


@pytest.fixture()
def fixture_profile_dir() -> Path:
    """Return the path to the examples/ profile directory."""
    return EXAMPLES_DIR


@pytest.fixture()
def fixture_job_path() -> Path:
    """Return the path to the sample job description fixture."""
    return EXAMPLES_DIR / "jobs" / "sample_software_engineer.md"


# ---------------------------------------------------------------------------
# Minimal MergedConfig factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_config(fixture_job_path: Path, fixture_profile_dir: Path, tmp_path: Path) -> MergedConfig:
    """Return a minimal MergedConfig pointing at example fixture files."""
    return MergedConfig(
        template_id="default_de_neutral",
        language="DE",
        length=LengthMode.normal,
        tone="neutral-professionell",
        mode=WritingMode.standard,
        cv_selection=CVSelectionMode.automatic,
        cv_tailoring=True,
        soft_skill_max=3,
        output_sections=["letter", "evidence_map"],
        validation_rules={},
        job_file=fixture_job_path,
        output_dir=tmp_path / "outputs",
        profile_dir=fixture_profile_dir,
    )


# ---------------------------------------------------------------------------
# Minimal WorkflowState factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_state(minimal_config: MergedConfig) -> WorkflowState:
    """Return a WorkflowState with only config populated."""
    return WorkflowState(config=minimal_config, run_id="test-run")


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm_client() -> MagicMock:
    """Return a MagicMock implementing the LLMClient protocol.

    Tests configure ``mock_llm_client.call.return_value`` with the dict they
    want the LLM to return.
    """
    client = MagicMock()
    client.call.return_value = {}
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_llm_response(**fields: Any) -> dict[str, Any]:
    """Convenience helper: build a fake LLM tool-use response dict."""
    return dict(fields)
