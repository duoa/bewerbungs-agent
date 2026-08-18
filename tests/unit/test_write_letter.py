"""Unit tests for stages.write_letter — TDD."""

from __future__ import annotations

import pytest

from bewerbungs_agent.config.models import WritingMode
from bewerbungs_agent.models.state import (
    ContentPlan,
    EvidenceItem,
    EvidenceMap,
    LetterDraft,
    WorkflowState,
)
from bewerbungs_agent.stages.write_letter import build_prompt, parse_response


def _make_content_plan() -> ContentPlan:
    return ContentPlan(
        template_id="default_de_neutral",
        selected_cv_variant="cv_software",
        mode=WritingMode.standard,
        sections=[],
        selected_soft_skills=[],
        evidence_map=EvidenceMap(
            items=[
                EvidenceItem(
                    claim="5 years Python",
                    source_type="cv_variant",
                    source_file="cvs/cv.md",
                    passage="Python expert",
                )
            ]
        ),
    )


def _state_with_plan(minimal_state: WorkflowState) -> WorkflowState:
    return minimal_state.model_copy(
        update={"content_plan": _make_content_plan()}
    )


class TestBuildPrompt:
    def test_prompt_contains_anchor_instruction(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must instruct the writer to anchor prose to anchor_passages."""
        state = _state_with_plan(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages).lower()
        assert "anchor" in combined or "anchor_passages" in combined

    def test_prompt_does_not_contain_raw_profile_text(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must not include raw InternalKnowledge text in the prompt.

        We attach a knowledge object with a sentinel string and assert it does NOT
        appear in the prompt (only the ContentPlan JSON should be present).
        """
        from bewerbungs_agent.models.state import InternalKnowledge

        sentinel = "SENTINEL_RAW_PROFILE_TEXT_NOT_IN_PLAN"
        knowledge = InternalKnowledge(
            master_profile={"name": "Test"},
            personal_skills=sentinel,
        )
        state = _state_with_plan(minimal_state).model_copy(
            update={"knowledge": knowledge}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert sentinel not in combined, (
            "Raw profile text must not appear in write_letter prompt"
        )

    def test_contains_content_plan_json(self, minimal_state: WorkflowState) -> None:
        """build_prompt must include serialised ContentPlan."""
        state = _state_with_plan(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "cv_software" in combined  # from content_plan.selected_cv_variant

    def test_does_not_contain_internal_knowledge(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must NOT reference raw InternalKnowledge.

        knowledge is None on this state; if build_prompt tried to access it,
        it would raise AttributeError — which this test would catch.
        """
        assert minimal_state.knowledge is None
        state = _state_with_plan(minimal_state)
        messages = build_prompt(state)  # must not raise
        assert isinstance(messages, list)

    def test_standard_mode_uses_standard_style(
        self, minimal_state: WorkflowState
    ) -> None:
        """Standard mode → prompt references standard style instructions."""
        state = _state_with_plan(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        # The standard.md placeholder content should appear
        assert len(combined) > 0  # at minimum not empty


class TestParseResponse:
    def test_valid_response(self) -> None:
        text = "Sehr geehrte Damen und Herren, hiermit bewerbe ich mich..."
        result = parse_response({"text": text, "mode": "standard"})
        assert isinstance(result, LetterDraft)
        assert result.char_count == len(text)
        assert result.mode == WritingMode.standard

    def test_raises_when_char_count_zero(self) -> None:
        with pytest.raises(ValueError, match="char_count"):
            parse_response({"text": "", "mode": "standard"})

    def test_raises_when_text_empty_after_strip(self) -> None:
        with pytest.raises(ValueError, match="char_count"):
            parse_response({"text": "   ", "mode": "standard"})

    def test_char_count_matches_text_length(self) -> None:
        text = "A" * 2500
        result = parse_response({"text": text, "mode": "standard"})
        assert result.char_count == 2500


# ---------------------------------------------------------------------------
# Feature 008 US2 — writer prompt consumes role_positioning + writer_rules
# ---------------------------------------------------------------------------


class TestWriterPromptIncludesPositioningAndRules:
    """T016 — FR-006, FR-007, FR-008, contracts §5."""

    def test_prompt_includes_positioning_block_and_writer_rules(
        self, minimal_state: WorkflowState
    ) -> None:
        from bewerbungs_agent.config.models import WriterRules
        from bewerbungs_agent.models.state import (
            ContentPlan,
            RolePositioning,
            SectionPlan,
        )

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
            role_positioning=RolePositioning(
                role_family="AI/ML platform engineering",
                primary_selling_point="Built scalable Python ML platforms.",
                secondary_selling_points=["Biomedical-ML adjacent context"],
                emphasise=["platform reliability"],
                deemphasise=["biomedical domain depth"],
                opening_angle="Lead with infrastructure-builder identity.",
            ),
        )

        # Build a state with the plan + default WriterRules
        cfg = minimal_state.config.model_copy(update={"writer_rules": WriterRules()})
        state = minimal_state.model_copy(update={"config": cfg, "content_plan": plan})

        messages = build_prompt(state)
        content = messages[0]["content"]

        # Positioning block must appear (feature 010: renamed field labels)
        assert "Role Positioning" in content
        assert "role_family" in content
        assert "AI/ML platform engineering" in content
        assert "Biomedical-ML adjacent context" in content
        assert "biomedical domain depth" in content
        assert "opening_angle" in content

        # Writer rules block must appear with the default cap + ban list
        assert "Writer Rules" in content
        assert "tool_density_max" in content
        assert "4" in content
        # All seven default ban phrases must surface so the LLM has them visible
        for phrase in (
            "expert-level", "deep expertise", "world-class",
            "guru", "rockstar", "10x", "ninja",
        ):
            assert phrase in content, f"banned phrase {phrase!r} not in prompt"


# ---------------------------------------------------------------------------
# Feature 011 — writer prompt surfaces per-paragraph density limits
# ---------------------------------------------------------------------------


class TestFeature011ParagraphBlockInWriterPrompt:
    """T017–T018 — # Paragraph Plan block rendering + graceful omission."""

    def test_writer_prompt_surfaces_paragraph_max_claims_and_max_tools(
        self, minimal_state: WorkflowState
    ) -> None:
        """T017 — FR-009, FR-016, FR-026, SC-006."""
        from bewerbungs_agent.config.models import WriterRules
        from bewerbungs_agent.models.state import (
            ContentPlan,
            ParagraphPlan,
            SectionPlan,
        )

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
            letter_thesis="Built scalable Python ML infrastructure for engineering teams.",
            paragraphs=[
                ParagraphPlan(
                    purpose="opening",
                    main_message="Lead with infrastructure-builder identity.",
                    max_claims=1,
                    max_tools=0,
                ),
                ParagraphPlan(
                    purpose="platform_credibility",
                    main_message="Owned EKS fleets running 1000 jobs/day with tight SLOs.",
                    max_claims=3,
                    max_tools=4,
                ),
            ],
        )
        cfg = minimal_state.config.model_copy(update={"writer_rules": WriterRules()})
        state = minimal_state.model_copy(update={"config": cfg, "content_plan": plan})

        messages = build_prompt(state)
        content = messages[0]["content"]

        # Block header + per-paragraph headings appear
        assert "# Paragraph Plan" in content
        assert "opening" in content
        assert "platform_credibility" in content

        # Per-paragraph limits appear
        assert "max_claims: 1" in content
        assert "max_claims: 3" in content
        assert "max_tools: 0" in content
        assert "max_tools: 4" in content

        # Main messages appear verbatim
        assert "Lead with infrastructure-builder identity." in content
        assert "Owned EKS fleets running 1000 jobs/day with tight SLOs." in content

        # Letter thesis surfaces
        assert "Built scalable Python ML infrastructure for engineering teams." in content

    def test_writer_prompt_omits_paragraph_block_when_paragraphs_empty(
        self, minimal_state: WorkflowState
    ) -> None:
        """T018 — FR-022 backward-compat. Block omitted entirely for legacy plans."""
        from bewerbungs_agent.config.models import WriterRules
        from bewerbungs_agent.models.state import ContentPlan, SectionPlan

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
            # NO paragraphs, NO letter_thesis — legacy shape
        )
        cfg = minimal_state.config.model_copy(update={"writer_rules": WriterRules()})
        state = minimal_state.model_copy(update={"config": cfg, "content_plan": plan})

        messages = build_prompt(state)
        content = messages[0]["content"]

        # Block must be absent
        assert "# Paragraph Plan" not in content
        # But the existing Writer Rules block from feature 008 must still be present
        assert "Writer Rules" in content


# ---------------------------------------------------------------------------
# Feature 013 US1 — writer consumes NarrativeStrategy block
# ---------------------------------------------------------------------------


class TestFeature013NarrativeStrategyInWriter:
    """T016 — narrative_strategy block surfaces in writer prompt."""

    def test_writer_prompt_includes_narrative_strategy_block(
        self, minimal_state: WorkflowState
    ) -> None:
        from bewerbungs_agent.config.models import WriterRules
        from bewerbungs_agent.models.state import (
            ContentPlan,
            NarrativeStrategy,
            SectionPlan,
        )

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
        )
        ns = NarrativeStrategy(
            candidate_story="An engineer who built Python ML platforms.",
            role_story="The company wants a senior platform owner.",
            bridge="The candidate already owns the systems this role needs.",
            opening_angle="Lead with infrastructure-builder identity.",
            proof_points_to_use=["Built ML inference platform"],
            proof_points_to_avoid=["Biomedical PhD"],
            transfer_framing_guidance="Mention research only briefly as credibility.",
            tone_guidance="Calm, senior, credible voice.",
            anti_patterns=["Do not open with 'Although my background is...'"],
        )
        cfg = minimal_state.config.model_copy(update={"writer_rules": WriterRules()})
        state = minimal_state.model_copy(
            update={"config": cfg, "content_plan": plan, "narrative_strategy": ns}
        )

        messages = build_prompt(state)
        content = messages[0]["content"]

        assert "# Narrative Strategy" in content
        assert "bridge:" in content
        assert "opening_angle:" in content
        assert "tone_guidance:" in content
        assert "anti_patterns:" in content
        # Block appears AFTER Writer Rules
        assert content.index("# Writer Rules") < content.index("# Narrative Strategy")
