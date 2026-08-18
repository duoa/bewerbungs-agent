"""Unit tests for the targeted_rewrite stage.

Tests MUST fail before targeted_rewrite.py is implemented.
All LLM calls are mocked — no real API calls made.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LengthMode,
    MergedConfig,
    ReviewConfig,
    WeaknessSeverity,
    WritingMode,
)
from bewerbungs_agent.models.state import (
    LetterDraft,
    LetterReviewReport,
    RequirementExtraction,
    SectionReview,
    WeaknessEntry,
    WorkflowState,
)


def _make_config(**overrides: object) -> MergedConfig:
    defaults: dict = {
        "template_id": "test",
        "language": "DE",
        "length": LengthMode.normal,
        "tone": "neutral",
        "mode": WritingMode.standard,
        "cv_selection": CVSelectionMode.automatic,
        "cv_tailoring": True,
        "soft_skill_max": 3,
        "output_sections": ["letter"],
        "validation_rules": {},
        "job_file": Path("job.md"),
        "output_dir": Path("outputs"),
    }
    defaults.update(overrides)
    return MergedConfig(**defaults)


_ORIGINAL_LETTER = "## Opening\nHello.\n\n## Experience\nI built a scalable API at Acme."
_REWRITTEN_LETTER = "## Opening\nDear Hiring Manager, I am excited to apply.\n\n## Experience\nI built a scalable API at Acme."


def _make_review(sections_to_rewrite: list[str]) -> LetterReviewReport:
    sections = [
        SectionReview(
            section_name="Opening",
            strengths=[],
            weaknesses=[WeaknessEntry(text="Too generic", severity=WeaknessSeverity.high, priority_fix="Add role context")],
            assessment="Weak.",
        ),
        SectionReview(
            section_name="Experience",
            strengths=["Specific project"],
            weaknesses=[],
            assessment="Strong.",
        ),
    ]
    return LetterReviewReport(sections=sections, overall_assessment="Needs work.", sections_to_rewrite=sections_to_rewrite)


def _make_state(**overrides: object) -> WorkflowState:
    config = _make_config()
    letter = LetterDraft(text=_ORIGINAL_LETTER, char_count=len(_ORIGINAL_LETTER), mode=WritingMode.standard)
    reqs = RequirementExtraction(core_requirement="Python backend engineer")
    review = _make_review(["Opening"])
    defaults: dict = {
        "config": config,
        "letter_draft": letter,
        "requirements": reqs,
        "letter_review": review,
    }
    defaults.update(overrides)
    return WorkflowState(**defaults)


class TestTargetedRewrite:
    def test_targeted_rewrite_returns_empty_when_no_review(self) -> None:
        """When letter_review is None, stage short-circuits and returns {}."""
        from bewerbungs_agent.stages.targeted_rewrite import targeted_rewrite

        state = _make_state(letter_review=None)
        mock_client = MagicMock()

        result = targeted_rewrite(state, client=mock_client)

        assert result == {}
        mock_client.call.assert_not_called()

    def test_targeted_rewrite_returns_empty_when_no_sections_to_rewrite(self) -> None:
        """When sections_to_rewrite is empty, no LLM call is made and {} returned."""
        from bewerbungs_agent.stages.targeted_rewrite import targeted_rewrite

        state = _make_state(letter_review=_make_review(sections_to_rewrite=[]))
        mock_client = MagicMock()

        result = targeted_rewrite(state, client=mock_client)

        assert result == {}
        mock_client.call.assert_not_called()

    def test_targeted_rewrite_returns_new_letter_draft(self) -> None:
        """Happy path: stage returns updated letter_draft with rewritten text."""
        from bewerbungs_agent.stages.targeted_rewrite import targeted_rewrite

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.return_value = {"text": _REWRITTEN_LETTER}

        result = targeted_rewrite(state, client=mock_client)

        assert "letter_draft" in result
        new_draft = result["letter_draft"]
        assert new_draft.text == _REWRITTEN_LETTER
        assert new_draft.mode == WritingMode.standard  # preserved from original

    def test_targeted_rewrite_swallows_llm_exception(self) -> None:
        """LLM failure is caught; {} is returned; no exception propagates."""
        from bewerbungs_agent.stages.targeted_rewrite import targeted_rewrite

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.side_effect = RuntimeError("Network error")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = targeted_rewrite(state, client=mock_client)

        assert result == {}
        assert any("targeted_rewrite" in str(w.message) for w in caught)

    def test_targeted_rewrite_prompt_contains_only_letter_and_requirements(self) -> None:
        """build_prompt includes letter text and requirements only, not profile/plan."""
        from bewerbungs_agent.stages.targeted_rewrite import build_prompt

        state = _make_state()
        messages = build_prompt(state)

        content = messages[0]["content"]
        assert "Opening" in content  # the section to rewrite
        assert "Python backend engineer" in content  # the requirement
        assert _ORIGINAL_LETTER[:20] in content  # original letter text present
        # Must NOT include knowledge/plan references (these should never appear in prompt)
        assert "InternalKnowledge" not in content
        assert "ContentPlan" not in content

    def test_targeted_rewrite_logs_stage_when_tracker_present(self) -> None:
        """tracker.log_stage is called with stage_name='targeted_rewrite' on success."""
        from bewerbungs_agent.stages.targeted_rewrite import targeted_rewrite

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.return_value = {"text": _REWRITTEN_LETTER}
        mock_tracker = MagicMock()
        state = state.model_copy(update={"tracker": mock_tracker})

        targeted_rewrite(state, client=mock_client)

        mock_tracker.log_stage.assert_called_once()
        call_kwargs = mock_tracker.log_stage.call_args
        assert call_kwargs.kwargs.get("stage_name") == "targeted_rewrite" or call_kwargs.args[0] == "targeted_rewrite"
