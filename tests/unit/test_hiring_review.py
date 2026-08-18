"""Unit tests for the hiring_review stage.

Tests MUST fail before hiring_review.py is implemented.
All LLM calls are mocked — no real API calls made.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LengthMode,
    MergedConfig,
    ReviewConfig,
    ReviewDimension,
    WeaknessSeverity,
    WritingMode,
)
from bewerbungs_agent.models.state import (
    LetterDraft,
    RequirementExtraction,
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


def _make_state(**overrides: object) -> WorkflowState:
    config = _make_config()
    letter = LetterDraft(text="## Opening\nHello.\n\n## Experience\nI worked on X.", char_count=44, mode=WritingMode.standard)
    reqs = RequirementExtraction(core_requirement="Python backend engineer")
    defaults: dict = {
        "config": config,
        "letter_draft": letter,
        "requirements": reqs,
    }
    defaults.update(overrides)
    return WorkflowState(**defaults)


def _make_review_payload(high_section: str = "Opening", low_section: str = "Experience") -> dict:
    """Minimal valid LLM review tool-use response."""
    return {
        "sections": [
            {
                "section_name": high_section,
                "strengths": [],
                "weaknesses": [
                    {"text": "Too generic", "severity": "high", "priority_fix": "Add specific role context"},
                ],
                "assessment": "Weak opening.",
            },
            {
                "section_name": low_section,
                "strengths": ["Specific project mentioned"],
                "weaknesses": [
                    {"text": "Minor wording", "severity": "low", "priority_fix": "Tighten phrasing"},
                ],
                "assessment": "Strong section.",
            },
        ],
        "overall_assessment": "Needs improvement in opening.",
    }


class TestHiringReview:
    def _get_stage(self):
        from bewerbungs_agent.stages.hiring_review import hiring_review
        return hiring_review

    def test_hiring_review_produces_review_report(self) -> None:
        """Happy path: stage produces LetterReviewReport with populated sections."""
        from bewerbungs_agent.stages.hiring_review import hiring_review
        from bewerbungs_agent.models.state import LetterReviewReport

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.return_value = _make_review_payload()

        result = hiring_review(state, client=mock_client)

        assert "letter_review" in result
        report = result["letter_review"]
        assert isinstance(report, LetterReviewReport)
        assert len(report.sections) == 2

    def test_hiring_review_computes_sections_to_rewrite_from_threshold(self) -> None:
        """sections_to_rewrite contains only sections with max weakness severity >= threshold."""
        from bewerbungs_agent.stages.hiring_review import hiring_review

        # Default threshold = medium; high-severity section qualifies, low-severity does not
        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.return_value = _make_review_payload(high_section="Opening", low_section="Experience")

        result = hiring_review(state, client=mock_client)

        report = result["letter_review"]
        assert "Opening" in report.sections_to_rewrite
        assert "Experience" not in report.sections_to_rewrite

    def test_hiring_review_returns_empty_when_disabled(self) -> None:
        """When review_config.enabled=False, no LLM call is made and result is {}."""
        from bewerbungs_agent.stages.hiring_review import hiring_review

        config = _make_config(review_config=ReviewConfig(enabled=False))
        state = _make_state(config=config)
        mock_client = MagicMock()

        result = hiring_review(state, client=mock_client)

        assert result == {}
        mock_client.call.assert_not_called()

    def test_hiring_review_returns_empty_when_no_letter(self) -> None:
        """When letter_draft is None, stage short-circuits and returns {}."""
        from bewerbungs_agent.stages.hiring_review import hiring_review

        state = _make_state(letter_draft=None)
        mock_client = MagicMock()

        result = hiring_review(state, client=mock_client)

        assert result == {}
        mock_client.call.assert_not_called()

    def test_hiring_review_swallows_llm_exception(self) -> None:
        """LLM failure is caught; {} is returned; no exception propagates."""
        from bewerbungs_agent.stages.hiring_review import hiring_review

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.side_effect = RuntimeError("API timeout")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = hiring_review(state, client=mock_client)

        assert result == {}
        assert any("hiring_review" in str(w.message) for w in caught)

    def test_hiring_review_logs_stage_when_tracker_present(self) -> None:
        """tracker.log_stage is called with stage_name='hiring_review' on success."""
        from bewerbungs_agent.stages.hiring_review import hiring_review

        state = _make_state()
        mock_client = MagicMock()
        mock_client.call.return_value = _make_review_payload()
        mock_tracker = MagicMock()
        state = state.model_copy(update={"tracker": mock_tracker})

        hiring_review(state, client=mock_client)

        mock_tracker.log_stage.assert_called_once()
        call_kwargs = mock_tracker.log_stage.call_args
        assert call_kwargs.kwargs.get("stage_name") == "hiring_review" or call_kwargs.args[0] == "hiring_review"

    def test_hiring_review_prompt_contains_only_active_dimensions(self) -> None:
        """build_prompt includes only configured dimensions in the user message."""
        from bewerbungs_agent.stages.hiring_review import build_prompt

        config = _make_config(
            review_config=ReviewConfig(
                dimensions=[ReviewDimension.clarity, ReviewDimension.credibility]
            )
        )
        state = _make_state(config=config)
        messages = build_prompt(state)

        content = messages[0]["content"]
        assert "clarity" in content
        assert "credibility" in content
        # Dimensions NOT configured should not appear
        assert "specificity" not in content
        assert "differentiation" not in content


# ---------------------------------------------------------------------------
# Feature 008 US3 — full job text + 5 new positioning dimensions
# ---------------------------------------------------------------------------


_HR_JOB_SENTINEL = "SCALABLE_CLOUD_INFRA_SENTINEL"


def _state_with_job_text(**overrides: object) -> WorkflowState:
    """Same as _make_state but ensures job_context.raw_job_text carries the sentinel."""
    from bewerbungs_agent.models.state import JobContext

    state = _make_state(**overrides)
    return state.model_copy(update={
        "job_context": JobContext(
            raw_job_text=f"Build {_HR_JOB_SENTINEL} for AI/ML workloads.",
            job_title="Senior Software Engineer — AI/ML Infrastructure",
            company_name="Helix Compute",
        ),
    })


class TestHiringReviewPromptIncludesJobTextAndPositioningDimensions:
    """T020 / T021 — feature 008 prompt augmentations."""

    def test_prompt_includes_raw_job_text(self) -> None:
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_job_text()
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert _HR_JOB_SENTINEL in content, "raw job description must appear verbatim in review prompt"
        assert "Original Job Description" in content, "prompt must label the job-text block"

    def test_prompt_lists_positioning_dimensions(self) -> None:
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_job_text()
        messages = build_prompt(state)
        content = messages[0]["content"]
        for dim in (
            "role_match",
            "opening_alignment",
            "secondary_topic_dominance",
            "tool_density",
            "overclaiming",
        ):
            assert dim in content, f"prompt must list positioning dimension {dim!r}"


class TestHiringReviewFlagsMispositionedLetter:
    """T022 — FR-013, FR-014, FR-025, SC-007.

    A canned review response that flags role_match + opening_alignment on the
    opening section with medium severity → sections_to_rewrite includes 'opening'.
    """

    def test_flags_role_match_and_opening_when_mispositioned(self) -> None:
        from bewerbungs_agent.stages.hiring_review import parse_response

        payload = {
            "sections": [
                {
                    "section_name": "opening",
                    "strengths": [],
                    "weaknesses": [
                        {
                            "text": "role_match: letter leads with biomedical-ML, "
                                    "but job is AI/ML infrastructure engineering",
                            "severity": "medium",
                            "priority_fix": "re-anchor opening to AI/ML platform engineering",
                        },
                        {
                            "text": "opening_alignment: first paragraph does not "
                                    "reference scalable cloud infra or efficient compute",
                            "severity": "medium",
                            "priority_fix": "lead with infra responsibility per opening_angle",
                        },
                    ],
                    "assessment": "Mispositioned for the actual role.",
                },
                {
                    "section_name": "experience",
                    "strengths": ["Specific projects cited"],
                    "weaknesses": [],
                    "assessment": "Strong section.",
                },
            ],
            "overall_assessment": "Opening needs re-anchoring to infrastructure framing.",
        }
        report = parse_response(payload, WeaknessSeverity.medium)
        assert "opening" in report.sections_to_rewrite
        # Experience section had no weaknesses — must NOT be on the list.
        assert "experience" not in report.sections_to_rewrite
        # Both positioning-flavoured weaknesses are recorded on the opening section.
        opening = next(s for s in report.sections if s.section_name == "opening")
        weakness_texts = " ".join(w.text for w in opening.weaknesses)
        assert "role_match" in weakness_texts
        assert "opening_alignment" in weakness_texts


# ---------------------------------------------------------------------------
# Feature 009 — US1: full job context (parsed structured fields)
# ---------------------------------------------------------------------------


def _state_with_full_job_context(**overrides: object) -> WorkflowState:
    """A state populated with raw job text + every structured JobContext field."""
    from bewerbungs_agent.models.state import JobContext

    state = _make_state(**overrides)
    return state.model_copy(update={
        "job_context": JobContext(
            raw_job_text=f"Helix Compute is hiring. {_HR_JOB_SENTINEL}.",
            job_title="Senior Software Engineer — AI/ML Infrastructure",
            company_name="Helix Compute GmbH",
            raw_company_text=(
                "Helix Compute is a Berlin-based platform team serving "
                "research partners in life sciences."
            ),
            raw_storyboard_text="Lead with infra builder identity; biomedical briefly.",
        ),
    })


class TestHiringReviewFullJobContext:
    """Feature 009 US1 — parsed structured job_context fields in the prompt."""

    def test_prompt_includes_parsed_job_context_structured_fields(self) -> None:
        """T002 — FR-001, FR-002, FR-020, SC-001, SC-002."""
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_full_job_context()
        messages = build_prompt(state)
        content = messages[0]["content"]
        # The new ## Parsed Job Context heading must appear.
        assert "## Parsed Job Context" in content, "missing ## Parsed Job Context heading"
        # And each populated structured field must be present verbatim.
        assert "Helix Compute GmbH" in content
        assert "Senior Software Engineer — AI/ML Infrastructure" in content
        assert "Berlin-based platform team serving" in content
        assert "Lead with infra builder identity" in content

    def test_prompt_omits_absent_optional_fields_gracefully(self) -> None:
        """T003 — FR-004.

        When optional structured fields are None they MUST NOT appear as
        '(none)' placeholders — they must be silently omitted entirely.
        """
        from bewerbungs_agent.models.state import JobContext
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _make_state().model_copy(update={
            "job_context": JobContext(
                raw_job_text="x",
                job_title="Engineer",
                company_name=None,
                raw_company_text=None,
                raw_storyboard_text=None,
            ),
        })
        messages = build_prompt(state)
        content = messages[0]["content"]
        # The block still appears because job_title is set.
        assert "## Parsed Job Context" in content
        # But absent-field labels must not appear.
        assert "company_name:" not in content, "company_name line leaked despite None"
        assert "company_info:" not in content
        assert "storyboard:" not in content
        # And no "(none)" placeholders for these fields.
        assert "company_name: (none)" not in content
        assert "company_info: (none)" not in content
        assert "storyboard: (none)" not in content

    def test_prompt_builds_when_job_context_is_none(self) -> None:
        """C1 gap fix — FR-003, FR-021, SC-004.

        Legacy / validate-only / unit-test states where state.job_context is
        None MUST not raise; the prompt MUST still build with the documented
        placeholder for the raw job text, and the new ## Parsed Job Context
        block MUST be omitted entirely.
        """
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _make_state()  # no job_context set, defaults to None
        assert state.job_context is None
        messages = build_prompt(state)
        content = messages[0]["content"]
        # Documented fallback placeholder
        assert "job description unavailable" in content
        # Structured-fields block must be omitted entirely
        assert "## Parsed Job Context" not in content

    def test_review_flags_secondary_domain_opening_with_high_severity(self) -> None:
        """T004 — FR-023, SC-008.

        Regression: a canned LLM payload flagging an opening that emphasises
        a secondary domain (role_match + secondary_topic_dominance at high
        severity) routes the 'opening' section into sections_to_rewrite on
        the new combined-context shape — not just on feature 008's minimum
        context.
        """
        from bewerbungs_agent.stages.hiring_review import parse_response

        payload = {
            "sections": [
                {
                    "section_name": "opening",
                    "strengths": [],
                    "weaknesses": [
                        {
                            "text": (
                                "role_match: letter leads with biomedical-ML, but "
                                "the job ad emphasises scalable cloud infrastructure"
                            ),
                            "severity": "high",
                            "priority_fix": "re-anchor opening to AI/ML platform engineering",
                        },
                        {
                            "text": (
                                "secondary_topic_dominance: opening paragraph spent "
                                "on adjacent-domain experience"
                            ),
                            "severity": "high",
                            "priority_fix": "lead with infra responsibility per opening_angle",
                        },
                    ],
                    "assessment": "Mispositioned for the role.",
                },
                {
                    "section_name": "experience",
                    "strengths": ["Specific projects cited"],
                    "weaknesses": [],
                    "assessment": "Strong section.",
                },
            ],
            "overall_assessment": "Opening must be re-anchored.",
        }
        report = parse_response(payload, WeaknessSeverity.medium)
        assert "opening" in report.sections_to_rewrite
        assert "experience" not in report.sections_to_rewrite
        opening = next(s for s in report.sections if s.section_name == "opening")
        weakness_texts = " ".join(w.text for w in opening.weaknesses)
        assert "role_match" in weakness_texts
        assert "secondary_topic_dominance" in weakness_texts


# ---------------------------------------------------------------------------
# Feature 009 — US2: content-plan summary block
# ---------------------------------------------------------------------------


def _state_with_content_plan(**overrides: object) -> WorkflowState:
    """A state with both a full job_context and a populated content_plan."""
    from bewerbungs_agent.config.models import WritingMode
    from bewerbungs_agent.models.state import (
        ContentPlan,
        EvidenceItem,
        EvidenceMap,
        RolePositioning,
        SectionPlan,
    )

    state = _state_with_full_job_context(**overrides)
    plan = ContentPlan(
        template_id="t",
        selected_cv_variant="cv_software",
        mode=WritingMode.standard,
        sections=[
            SectionPlan(
                title="role_fit",
                key_claims=["Built scalable Python ML platforms", "Owned inference SLOs"],
                evidence_refs=["Built scalable Python ML platforms"],
            ),
            SectionPlan(
                title="platform_experience",
                key_claims=["Operated EKS fleets"],
                evidence_refs=["Operated EKS fleets"],
            ),
        ],
        role_positioning=RolePositioning(
            role_family="AI/ML platform engineering",
            primary_selling_point="Built scalable Python ML inference platforms.",
            secondary_selling_points=["Biomedical-ML adjacent context"],
            emphasise=["platform reliability"],
            deemphasise=["biomedical domain depth"],
            opening_angle="Lead with infrastructure-builder identity.",
        ),
        evidence_map=EvidenceMap(
            items=[
                EvidenceItem(
                    claim="Built scalable Python ML platforms",
                    source_type="cv_variant",
                    source_file="cvs/cv_software.md",
                    passage="x",
                ),
            ],
            known_gaps=["Spark experience not documented"],
        ),
    )
    return state.model_copy(update={"content_plan": plan})


class TestHiringReviewContentPlanContext:
    """Feature 009 US2 — content-plan summary block in the review prompt."""

    def test_prompt_includes_content_plan_summary(self) -> None:
        """T008 — FR-005, FR-006, FR-020, SC-003."""
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_content_plan()
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "## Content Plan" in content
        assert "role_fit" in content
        assert "Built scalable Python ML platforms" in content
        assert "platform_experience" in content
        assert "Operated EKS fleets" in content

    def test_prompt_includes_role_positioning_when_present(self) -> None:
        """T009 — FR-006, SC-003. role_positioning sub-block surfaces."""
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_content_plan()
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "Role Positioning" in content
        assert "AI/ML platform engineering" in content
        assert "Lead with infrastructure-builder identity." in content
        assert "biomedical domain depth" in content
        # known_gaps sub-block also surfaces
        assert "Known gaps" in content
        assert "Spark experience not documented" in content

    def test_prompt_builds_when_content_plan_is_none(self) -> None:
        """T010 — FR-005, FR-022, SC-005."""
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_full_job_context()  # job_context populated, content_plan None
        assert state.content_plan is None
        messages = build_prompt(state)
        content = messages[0]["content"]
        # No exception — already validated by reaching here. Plan block omitted.
        assert "## Content Plan" not in content


# ---------------------------------------------------------------------------
# Feature 009 — US3: critical_requirements_underweighted dimension
# ---------------------------------------------------------------------------


class TestHiringReviewCriticalRequirementsDimension:
    """Feature 009 US3 — new always-on coverage dimension."""

    def test_active_dimensions_includes_critical_requirements_underweighted(self) -> None:
        """T014 — FR-008, FR-024, SC-006.

        The new dimension is ADDITIVE, not a replacement: the prompt MUST still
        contain the five feature-008 dimensions AND the new one.
        """
        from bewerbungs_agent.stages.hiring_review import build_prompt

        state = _state_with_full_job_context()
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "critical_requirements_underweighted" in content
        # Feature 008 dims remain
        for dim in (
            "role_match",
            "opening_alignment",
            "secondary_topic_dominance",
            "tool_density",
            "overclaiming",
        ):
            assert dim in content, f"feature-008 dimension {dim!r} disappeared"

    def test_critical_requirements_underweighted_routes_to_rewrite(self) -> None:
        """T015 — FR-009, FR-010, FR-025, SC-007.

        Severity-driven routing: a medium-severity criticality weakness lands
        the affected section in sections_to_rewrite via the existing parser.
        """
        from bewerbungs_agent.stages.hiring_review import parse_response

        payload = {
            "sections": [
                {
                    "section_name": "experience",
                    "strengths": ["Specific projects cited"],
                    "weaknesses": [
                        {
                            "text": (
                                "critical_requirements_underweighted: scalable cloud "
                                "infrastructure barely mentioned; the job ad lists it "
                                "as a top responsibility"
                            ),
                            "severity": "medium",
                            "priority_fix": (
                                "add a paragraph on scalable-infrastructure responsibilities"
                            ),
                        }
                    ],
                    "assessment": "Coverage gap on a top requirement.",
                },
                {
                    "section_name": "opening",
                    "strengths": ["Clear, infra-led opening"],
                    "weaknesses": [],
                    "assessment": "Strong opening.",
                },
            ],
            "overall_assessment": "Opening is solid; experience needs to expand on infra.",
        }
        report = parse_response(payload, WeaknessSeverity.medium)
        assert "experience" in report.sections_to_rewrite
        assert "opening" not in report.sections_to_rewrite
        # Weakness text preserved verbatim on the parsed section
        exp = next(s for s in report.sections if s.section_name == "experience")
        assert any(
            "critical_requirements_underweighted" in w.text for w in exp.weaknesses
        )


# ---------------------------------------------------------------------------
# Feature 010 US2 — risky_or_gap_areas surfaces in hiring-review content-plan block
# ---------------------------------------------------------------------------


class TestFeature010RiskyOrGapAreasSurfacing:
    """T024 — FR-010, FR-025."""

    def test_hiring_review_prompt_surfaces_risky_or_gap_areas_when_present(self) -> None:
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            ContentPlan,
            RolePositioning,
            SectionPlan,
        )
        from bewerbungs_agent.stages.hiring_review import build_prompt

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
            role_positioning=RolePositioning(
                role_family="AI/ML platform engineering",
                primary_selling_point="Built scalable platforms.",
                opening_angle="Lead with infra identity.",
                risky_or_gap_areas=[
                    "claims of deep on-call experience without anchor",
                    "biomedical regulatory expertise",
                ],
            ),
        )
        state = _make_state().model_copy(update={"content_plan": plan})

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "risky_or_gap_areas" in content
        assert "claims of deep on-call experience without anchor" in content
        assert "biomedical regulatory expertise" in content

    def test_hiring_review_prompt_omits_risky_or_gap_areas_when_empty(self) -> None:
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            ContentPlan,
            RolePositioning,
            SectionPlan,
        )
        from bewerbungs_agent.stages.hiring_review import build_prompt

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["a"])],
            role_positioning=RolePositioning(
                role_family="X",
                primary_selling_point="Y",
                opening_angle="Z",
                # risky_or_gap_areas defaults to []
            ),
        )
        state = _make_state().model_copy(update={"content_plan": plan})

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "risky_or_gap_areas" not in content


# ---------------------------------------------------------------------------
# Feature 013 US3 — craft dimensions + German over-analogy scan
# ---------------------------------------------------------------------------


class TestFeature013CraftDimensions:
    """T037 + T038 + T040 — craft dimensions in prompt + parse + verdict escalation."""

    def test_hiring_review_prompt_includes_six_craft_dimensions(
        self, minimal_state: WorkflowState
    ) -> None:
        """T037 — six dimension names appear in the prompt."""
        from bewerbungs_agent.models.state import LetterDraft, RequirementExtraction
        from bewerbungs_agent.stages.hiring_review import build_prompt

        draft = LetterDraft(text="Sehr geehrte Damen", char_count=20, mode=WritingMode.standard)
        reqs = RequirementExtraction(core_requirement="x")
        state = minimal_state.model_copy(
            update={"letter_draft": draft, "requirements": reqs}
        )
        messages = build_prompt(state)
        content = messages[0]["content"]
        for dim in (
            "story_coherence",
            "transition_smoothness",
            "over_constructed_language",
            "claim_relevance",
            "aida_restraint",
            "human_readability",
        ):
            assert dim in content, f"missing craft dimension {dim!r} in hiring_review prompt"

    def test_hiring_review_parses_craft_dimensions(self) -> None:
        """T038 — parse_response builds a CraftDimensions object from craft_dimensions."""
        from bewerbungs_agent.config.models import WeaknessSeverity
        from bewerbungs_agent.models.state import CraftDimension, CraftDimensions
        from bewerbungs_agent.stages.hiring_review import parse_response

        canned = {
            "sections": [],
            "overall_assessment": "good",
            "craft_dimensions": {
                "story_coherence": {"severity": "pass", "rationale": "ok"},
                "transition_smoothness": {"severity": "pass", "rationale": "ok"},
                "over_constructed_language": {"severity": "pass", "rationale": "ok"},
                "claim_relevance": {"severity": "pass", "rationale": "ok"},
                "aida_restraint": {"severity": "pass", "rationale": "ok"},
                "human_readability": {"severity": "pass", "rationale": "ok"},
            },
        }
        report = parse_response(canned, WeaknessSeverity.medium)
        assert report.craft_dimensions is not None
        assert isinstance(report.craft_dimensions, CraftDimensions)
        assert isinstance(report.craft_dimensions.story_coherence, CraftDimension)
        for dim_name in (
            "story_coherence", "transition_smoothness", "over_constructed_language",
            "claim_relevance", "aida_restraint", "human_readability",
        ):
            assert getattr(report.craft_dimensions, dim_name).severity == "pass"

    def test_craft_dimension_requires_evidence_quote_when_warn(self) -> None:
        """T038 — severity=warn requires evidence_quote."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import CraftDimension

        with pytest.raises(ValidationError):
            CraftDimension(severity="warn", rationale="r", evidence_quote=None)
        # Pass severity with None evidence_quote is allowed
        CraftDimension(severity="pass", rationale="r", evidence_quote=None)

    def test_hiring_review_verdict_escalates_when_aida_restraint_warn(self) -> None:
        """T040 — aida_restraint warn ⇒ aggregate verdict at minimum needs_minor_revision."""
        from bewerbungs_agent.config.models import WeaknessSeverity
        from bewerbungs_agent.stages.hiring_review import parse_response

        canned_pass = {
            "sections": [],
            "overall_assessment": "looks fine on the surface",
            "verdict": "pass",
            "craft_dimensions": {
                "story_coherence": {"severity": "pass", "rationale": "ok"},
                "transition_smoothness": {"severity": "pass", "rationale": "ok"},
                "over_constructed_language": {"severity": "pass", "rationale": "ok"},
                "claim_relevance": {"severity": "pass", "rationale": "ok"},
                "aida_restraint": {
                    "severity": "warn",
                    "rationale": "Opening uses ALL-CAPS attention grab",
                    "evidence_quote": "PICTURE THIS:",
                },
                "human_readability": {"severity": "pass", "rationale": "ok"},
            },
        }
        report = parse_response(canned_pass, WeaknessSeverity.medium)
        assert report.verdict == "needs_minor_revision"

        # transition_smoothness=warn also escalates
        canned_pass["craft_dimensions"]["aida_restraint"]["severity"] = "pass"
        canned_pass["craft_dimensions"]["aida_restraint"]["evidence_quote"] = None
        canned_pass["craft_dimensions"]["transition_smoothness"] = {
            "severity": "warn",
            "rationale": "Para 2→3 pivots abruptly",
            "evidence_quote": "Während meiner Promotion ...",
        }
        report = parse_response(canned_pass, WeaknessSeverity.medium)
        assert report.verdict == "needs_minor_revision"

        # When neither escalator is warn, verdict stays as given
        canned_clean = {**canned_pass, "craft_dimensions": {
            "story_coherence": {"severity": "pass", "rationale": "ok"},
            "transition_smoothness": {"severity": "pass", "rationale": "ok"},
            "over_constructed_language": {"severity": "pass", "rationale": "ok"},
            "claim_relevance": {"severity": "pass", "rationale": "ok"},
            "aida_restraint": {"severity": "pass", "rationale": "ok"},
            "human_readability": {"severity": "pass", "rationale": "ok"},
        }}
        report = parse_response(canned_clean, WeaknessSeverity.medium)
        assert report.verdict == "pass"


class TestFeature013DeterministicOverAnalogyScan:
    """T039 — deterministic German over-analogy phrase scan."""

    def test_scan_detects_direkt_uebertragbar(self) -> None:
        from bewerbungs_agent.stages.hiring_review import _scan_over_analogy_phrases

        text = "Mein Hintergrund ist direkt übertragbar auf diese Rolle."
        findings = _scan_over_analogy_phrases(text)
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "over_analogy_phrase_de"
        assert f.severity == "warn"
        assert f.phrase == "direkt übertragbar"
        # The substring "direkt übertragbar" begins at offset 22
        assert text[f.char_start:f.char_end] == "direkt übertragbar"
        assert "direkt übertragbar" in f.context_snippet

    def test_scan_returns_empty_for_clean_letter(self) -> None:
        from bewerbungs_agent.stages.hiring_review import _scan_over_analogy_phrases

        clean = "Sehr geehrte Damen und Herren, ich bewerbe mich um die Position."
        assert _scan_over_analogy_phrases(clean) == []

    def test_scan_returns_two_findings_for_two_occurrences(self) -> None:
        from bewerbungs_agent.stages.hiring_review import _scan_over_analogy_phrases

        text = (
            "Erstens ist mein Stack direkt übertragbar. "
            "Zweitens ist meine Erfahrung strukturell eng verwandt."
        )
        findings = _scan_over_analogy_phrases(text)
        assert len(findings) == 2
        phrases = sorted(f.phrase for f in findings)
        assert phrases == ["direkt übertragbar", "strukturell eng verwandt"]
