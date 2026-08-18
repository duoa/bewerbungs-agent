"""Unit tests for stages.story_polish — feature 013 US2."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bewerbungs_agent.config.models import WritingMode
from bewerbungs_agent.models.state import (
    ContentPlan,
    LetterDraft,
    SectionPlan,
    WorkflowState,
)


def _state_with_draft(minimal_state: WorkflowState) -> WorkflowState:
    plan = ContentPlan(
        template_id="t",
        selected_cv_variant="cv_x",
        mode=WritingMode.standard,
        sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
    )
    draft = LetterDraft(
        text=(
            "Sehr geehrte Damen und Herren,\n\n"
            "Ich arbeite mit Python und Kafka bei Acme Corp.\n"
            "Wir handhaben 1000 Jobs am Tag.\n\n"
            "Mit freundlichen Grüßen\nAlex"
        ),
        char_count=200,
        mode=WritingMode.standard,
    )
    return minimal_state.model_copy(update={"content_plan": plan, "letter_draft": draft})


class TestStoryPolishOutputSchema:
    """T027 — schema consistency invariants."""

    def test_story_polish_output_schema_consistency_added_tools(self) -> None:
        from bewerbungs_agent.models.state import StoryPolishOutput

        with pytest.raises(ValidationError):
            StoryPolishOutput(
                polished_text="x",
                post_check_passed=True,
                added_tools=["X"],  # inconsistent
            )

    def test_story_polish_output_requires_fallback_reason_when_used_fallback(self) -> None:
        from bewerbungs_agent.models.state import StoryPolishOutput

        with pytest.raises(ValidationError):
            StoryPolishOutput(
                polished_text="x",
                post_check_passed=False,
                used_fallback=True,
                fallback_reason=None,  # required when used_fallback=True
            )


class TestStoryPolishFallback:
    """T028 + T029 + T030 — fallback paths."""

    def test_story_polish_falls_back_on_llm_failure(
        self, minimal_state: WorkflowState, monkeypatch, mock_llm_client
    ) -> None:
        """T028 — LLM raises → return original draft + used_fallback=True."""
        from bewerbungs_agent.stages.story_polish import story_polish
        import bewerbungs_agent.utils.llm_client as llm_mod

        mock_llm_client.call.side_effect = RuntimeError("boom")
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        state = _state_with_draft(minimal_state)
        original_text = state.letter_draft.text
        result = story_polish(state)
        assert "letter_draft" in result
        assert result["letter_draft"].text == original_text
        spo = result["story_polish_output"]
        assert spo.used_fallback is True
        assert spo.fallback_reason.startswith("llm_failure: boom")

    def test_story_polish_falls_back_on_post_check_failure(
        self, minimal_state: WorkflowState, monkeypatch, mock_llm_client
    ) -> None:
        """T029 — polished introduces a new tool name → fallback to draft."""
        from bewerbungs_agent.stages.story_polish import story_polish
        import bewerbungs_agent.utils.llm_client as llm_mod

        # The draft contains Python + Kafka. The polished version adds "Spark".
        state = _state_with_draft(minimal_state)
        polished_text = state.letter_draft.text + "\nAlso skilled in Spark."
        mock_llm_client.call.return_value = {"polished_text": polished_text}
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        original_text = state.letter_draft.text
        result = story_polish(state)
        assert result["letter_draft"].text == original_text  # fallback to draft
        spo = result["story_polish_output"]
        assert spo.used_fallback is True
        assert spo.post_check_passed is False
        assert spo.fallback_reason.startswith("post_check_failed:")
        assert "Spark" in spo.added_tools

    def test_story_polish_skipped_when_disabled(
        self, minimal_state: WorkflowState, monkeypatch, mock_llm_client
    ) -> None:
        """T030 — story_polish_enabled=False → stage is bypassed; no LLM call."""
        from bewerbungs_agent.stages.story_polish import story_polish
        import bewerbungs_agent.utils.llm_client as llm_mod

        cfg = minimal_state.config.model_copy(
            update={
                "narrative_polish": minimal_state.config.narrative_polish.model_copy(
                    update={"story_polish_enabled": False}
                )
            }
        )
        state = _state_with_draft(minimal_state).model_copy(update={"config": cfg})
        called_flag = {"called": False}

        def _fail_if_called(*a, **kw):
            called_flag["called"] = True
            raise AssertionError("LLM should not be called when story_polish disabled")

        mock_llm_client.call.side_effect = _fail_if_called
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        result = story_polish(state)
        assert called_flag["called"] is False
        assert result["letter_draft"] is state.letter_draft
        assert result["story_polish_output"] is None
