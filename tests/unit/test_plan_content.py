"""Unit tests for stages.plan_content — TDD."""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungs_agent.models.state import (
    ContentPlan,
    EvidenceItem,
    EvidenceMap,
    RequirementExtraction,
    WorkflowState,
)
from bewerbungs_agent.stages.plan_content import build_prompt, parse_response


def _state_with_evidence(minimal_state: WorkflowState) -> WorkflowState:
    reqs = RequirementExtraction(
        core_requirement="Python expertise",
        technical_requirements=["Spark"],
    )
    evidence_map = EvidenceMap(
        items=[
            EvidenceItem(
                claim="5 years Python experience",
                source_type="cv_variant",
                source_file="cvs/cv_software.md",
                passage="Python expert with 5 years experience.",
            ),
            EvidenceItem(
                claim="Led ETL migration reducing failures by 40%",
                source_type="master_profile",
                source_file="profile/master_profile.json",
                passage="Led migration of legacy ETL system, reducing pipeline failures by 40%",
            ),
        ],
        known_gaps=[],
    )
    return minimal_state.model_copy(
        update={"requirements": reqs, "evidence_map": evidence_map}
    )


class TestBuildPrompt:
    def test_prompt_includes_verbatim_passages(self, minimal_state: WorkflowState) -> None:
        """build_prompt must include the verbatim passage from each EvidenceItem."""
        evidence_map = EvidenceMap(
            items=[
                EvidenceItem(
                    claim="Led microservices migration",
                    source_type="cv_variant",
                    source_file="cvs/cv_software.md",
                    passage="SENTINEL_VERBATIM_PASSAGE_TEXT",
                    relevance_note="Evidences architecture experience.",
                ),
            ],
            known_gaps=[],
        )
        reqs = RequirementExtraction(core_requirement="Backend architecture")
        state = minimal_state.model_copy(
            update={"requirements": reqs, "evidence_map": evidence_map}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "SENTINEL_VERBATIM_PASSAGE_TEXT" in combined

    def test_prompt_includes_relevance_note_when_present(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must include the relevance_note when non-empty."""
        evidence_map = EvidenceMap(
            items=[
                EvidenceItem(
                    claim="Python expert",
                    source_type="cv_variant",
                    source_file="cvs/cv_software.md",
                    passage="Python expert with 5 years experience.",
                    relevance_note="SENTINEL_RELEVANCE_NOTE",
                ),
            ],
            known_gaps=[],
        )
        reqs = RequirementExtraction(core_requirement="Python expertise")
        state = minimal_state.model_copy(
            update={"requirements": reqs, "evidence_map": evidence_map}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "SENTINEL_RELEVANCE_NOTE" in combined

    def test_does_not_include_raw_internal_knowledge(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must NOT include raw InternalKnowledge."""
        state = _state_with_evidence(minimal_state)
        # knowledge is None on minimal_state — build_prompt must not need it
        messages = build_prompt(state)
        assert isinstance(messages, list)

    def test_includes_evidence_claims(self, minimal_state: WorkflowState) -> None:
        state = _state_with_evidence(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "5 years Python experience" in combined

    def test_includes_soft_skill_max_constraint(
        self, minimal_state: WorkflowState
    ) -> None:
        state = _state_with_evidence(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert str(minimal_state.config.soft_skill_max) in combined


class TestParseResponse:
    _valid_plan = {
        "template_id": "default_de_neutral",
        "selected_cv_variant": "cv_software",
        "mode": "standard",
        "sections": [
            {
                "title": "role_fit",
                "key_claims": ["5 years Python experience"],
                "evidence_refs": ["5 years Python experience"],
                "soft_skills": [],
            }
        ],
        "selected_soft_skills": [],
        "open_questions": [],
        "assumptions": [],
        "evidence_map": {
            "items": [
                {
                    "claim": "5 years Python experience",
                    "source_type": "cv_variant",
                    "source_file": "cvs/cv_software.md",
                    "passage": "Python expert with 5 years experience.",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        },
    }

    def test_anchor_passages_accepted(self) -> None:
        """A section with anchor_passages must deserialise with those passages."""
        plan = {
            **self._valid_plan,
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["5 years Python experience"],
                    "evidence_refs": ["5 years Python experience"],
                    "anchor_passages": ["Python expert with 5 years experience."],
                    "soft_skills": [],
                }
            ],
        }
        result = parse_response(plan, soft_skill_max=3)
        assert result.sections[0].anchor_passages == ["Python expert with 5 years experience."]

    def test_valid_plan_parses(self) -> None:
        result = parse_response(self._valid_plan, soft_skill_max=3)
        assert isinstance(result, ContentPlan)
        assert result.selected_cv_variant == "cv_software"

    def test_soft_skill_max_respected(self) -> None:
        """More soft skills than soft_skill_max → ValueError."""
        plan = {
            **self._valid_plan,
            "selected_soft_skills": [
                {
                    "name": f"Skill{i}",
                    "behaviour": "Did things",
                    "evidence_item": {
                        "claim": "x",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv.md",
                        "passage": "x",
                    },
                }
                for i in range(4)  # 4 > max 3
            ],
        }
        with pytest.raises(ValueError, match="soft_skill_max"):
            parse_response(plan, soft_skill_max=3)

    def test_claim_not_in_evidence_map_raises(self) -> None:
        """A claim in sections that is not in evidence_map → ValueError."""
        plan = {
            **self._valid_plan,
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["Invented claim not in evidence"],
                    "evidence_refs": ["Invented claim not in evidence"],
                    "soft_skills": [],
                }
            ],
        }
        with pytest.raises(ValueError, match="evidence"):
            parse_response(plan, soft_skill_max=3)


# ---------------------------------------------------------------------------
# Feature 008 — RolePositioning + ContentPlan.role_positioning field
# ---------------------------------------------------------------------------


class TestRolePositioningModel:
    """T002 — Pydantic-level coverage for the new positioning sub-object."""

    def test_valid_construction_populates_all_six_fields(self) -> None:
        from bewerbungs_agent.models.state import RolePositioning

        rp = RolePositioning(
            role_family="AI/ML platform engineering",
            primary_selling_point="Built scalable Python ML inference platforms.",
            secondary_selling_points=["Biomedical-ML modelling adjacent context"],
            emphasise=["platform reliability", "Python software quality"],
            deemphasise=["biomedical domain depth"],
            opening_angle="Lead with infrastructure-builder identity.",
        )
        assert rp.role_family.startswith("AI/ML")
        assert rp.secondary_selling_points == ["Biomedical-ML modelling adjacent context"]
        assert rp.deemphasise == ["biomedical domain depth"]

    def test_missing_required_fields_raises(self) -> None:
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import RolePositioning

        with pytest.raises(ValidationError):
            # role_family missing
            RolePositioning(  # type: ignore[call-arg]
                primary_selling_point="X",
                opening_angle="Y",
            )

    def test_extra_key_forbidden(self) -> None:
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import RolePositioning

        with pytest.raises(ValidationError):
            RolePositioning.model_validate({
                "role_family": "x",
                "primary_selling_point": "y",
                "opening_angle": "z",
                "unknown_typo_field": True,
            })

    def test_content_plan_accepts_role_positioning_none_for_backward_compat(self) -> None:
        """Existing serialised plans without role_positioning still load."""
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import ContentPlan

        plan = ContentPlan(
            template_id="t",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
        )
        assert plan.role_positioning is None


# ---------------------------------------------------------------------------
# Feature 008 US1 — Planner positioning + raw job text in prompt
# ---------------------------------------------------------------------------


_JOB_SENTINEL = "SCALABLE_CLOUD_INFRA_SENTINEL"


def _state_with_job_text(minimal_state: WorkflowState) -> WorkflowState:
    """Return a state with both evidence AND a recognisable raw job text."""
    from bewerbungs_agent.models.state import JobContext

    state = _state_with_evidence(minimal_state)
    return state.model_copy(update={
        "job_context": JobContext(
            raw_job_text=f"Build {_JOB_SENTINEL} for AI/ML workloads.",
            job_title="Senior Software Engineer — AI/ML Infrastructure",
            company_name="Helix Compute",
        ),
    })


class TestPlannerPositioning:
    """T007 / T008 / T009 — planner prompt + parse handle positioning."""

    def test_prompt_includes_raw_job_text_and_positioning_instructions(
        self, minimal_state: WorkflowState
    ) -> None:
        """T007 — FR-001, FR-002, contracts §4."""
        state = _state_with_job_text(minimal_state)
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert _JOB_SENTINEL in content, "raw job text must appear verbatim in planner prompt"
        assert "role_positioning" in content, "prompt must reference role_positioning"
        assert "role_family" in content, "prompt must reference primary_role_family"

    def test_parse_accepts_role_positioning_subobject(self) -> None:
        """T008 — parse_response builds a ContentPlan with role_positioning."""
        plan = {
            "template_id": "default_de_neutral",
            "selected_cv_variant": "cv_software",
            "mode": "standard",
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["5 years Python experience"],
                    "evidence_refs": ["5 years Python experience"],
                    "soft_skills": [],
                }
            ],
            "evidence_map": {
                "items": [
                    {
                        "claim": "5 years Python experience",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv_software.md",
                        "passage": "Python expert.",
                    }
                ],
                "known_gaps": [],
            },
            "role_positioning": {
                "role_family": "AI/ML platform engineering",
                "primary_selling_point": "Built scalable Python ML inference platforms.",
                "secondary_selling_points": ["Biomedical-ML adjacent context"],
                "emphasise": ["platform reliability"],
                "deemphasise": ["biomedical domain depth"],
                "opening_angle": "Lead with infrastructure-builder identity.",
            },
        }
        result = parse_response(plan, soft_skill_max=3)
        assert result.role_positioning is not None
        assert result.role_positioning.role_family == "AI/ML platform engineering"
        assert result.role_positioning.secondary_selling_points == ["Biomedical-ML adjacent context"]

    def test_positions_infrastructure_first_on_ml_infra_fixture(self) -> None:
        """T009 — FR-004, FR-024, SC-002.

        A canned correctly-positioned response → resulting ContentPlan never
        records biomedical-ML as the primary selling point. This is the
        regression guard against the GSK-style failure mode.
        """
        plan = {
            "template_id": "default_de_neutral",
            "selected_cv_variant": "cv_software",
            "mode": "standard",
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["Built scalable Python ML platforms"],
                    "evidence_refs": ["Built scalable Python ML platforms"],
                    "soft_skills": [],
                }
            ],
            "evidence_map": {
                "items": [
                    {
                        "claim": "Built scalable Python ML platforms",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv_software.md",
                        "passage": "Designed Python platform.",
                    }
                ],
                "known_gaps": [],
            },
            "role_positioning": {
                "role_family": "AI/ML platform engineering",
                "primary_selling_point": "Built scalable Python ML inference platforms for engineering teams.",
                "secondary_selling_points": [
                    "Biomedical-ML modelling experience as adjacent domain context.",
                ],
                "emphasise": [
                    "platform reliability",
                    "Python software quality",
                    "AI/ML inference scaling",
                ],
                "deemphasise": ["biomedical domain depth"],
                "opening_angle": "Lead with infrastructure-builder identity; biomedical context briefly.",
            },
        }
        result = parse_response(plan, soft_skill_max=3)
        rp = result.role_positioning
        assert rp is not None

        # The primary role family MUST be infrastructure/platform-flavoured —
        # NOT biomedical. This is the durable GSK-regression guard.
        primary_lower = rp.role_family.lower()
        assert ("platform" in primary_lower or "infrastructure" in primary_lower), (
            f"role_family must reflect infrastructure framing; got {rp.role_family!r}"
        )
        assert "biomedical" not in primary_lower, (
            f"role_family must NOT lead with biomedical; got {rp.role_family!r}"
        )

        # Biomedical-ML must appear in secondary, NOT primary selling point.
        assert "biomedical" not in rp.primary_selling_point.lower(), (
            f"primary_selling_point must not lead with biomedical; "
            f"got {rp.primary_selling_point!r}"
        )
        assert any("biomedical" in s.lower() for s in rp.secondary_selling_points), (
            "biomedical-ML angle should be recorded in secondary_selling_points"
        )


# ---------------------------------------------------------------------------
# Feature 010 US2 — RolePositioning rename + risky_or_gap_areas + planner
# consumption of requirement_items
# ---------------------------------------------------------------------------


class TestFeature010RolePositioning:
    """T013–T016 — schema validation, aliases, defaults, unknown-field guard."""

    def test_role_positioning_accepts_new_field_names(self) -> None:
        """T013 — FR-007, FR-022."""
        from bewerbungs_agent.models.state import RolePositioning

        data = {
            "role_family": "AI/ML platform engineering",
            "primary_selling_point": "Built scalable Python ML platforms.",
            "secondary_selling_points": ["Biomedical-ML adjacent context"],
            "opening_angle": "Lead with infra identity.",
            "emphasise": ["platform reliability"],
            "deemphasise": ["biomedical domain depth"],
            "risky_or_gap_areas": ["claims of deep on-call experience"],
        }
        rp = RolePositioning.model_validate(data)
        assert rp.role_family == "AI/ML platform engineering"
        assert rp.emphasise == ["platform reliability"]
        assert rp.deemphasise == ["biomedical domain depth"]
        assert rp.risky_or_gap_areas == ["claims of deep on-call experience"]

    def test_role_positioning_accepts_legacy_field_names_via_alias(self) -> None:
        """T014 — FR-019, FR-024. Feature-008-shape JSON loads via Pydantic aliases."""
        from bewerbungs_agent.models.state import RolePositioning

        data = {
            "role_family": "AI/ML platform engineering",
            "primary_selling_point": "Built scalable Python ML platforms.",
            "secondary_selling_points": [],
            "opening_angle": "Lead with infra identity.",
            "emphasise": ["platform reliability"],
            "deemphasise": ["biomedical domain depth"],
            # NOTE: no risky_or_gap_areas — should default to []
        }
        rp = RolePositioning.model_validate(data)
        assert rp.role_family == "AI/ML platform engineering"
        assert rp.emphasise == ["platform reliability"]
        assert rp.deemphasise == ["biomedical domain depth"]
        assert rp.risky_or_gap_areas == []

    def test_role_positioning_risky_or_gap_areas_defaults_to_empty(self) -> None:
        """T015 — FR-008, FR-019. Minimal positioning omits risky_or_gap_areas."""
        from bewerbungs_agent.models.state import RolePositioning

        data = {
            "role_family": "X",
            "primary_selling_point": "Y",
            "opening_angle": "Z",
        }
        rp = RolePositioning.model_validate(data)
        assert rp.risky_or_gap_areas == []
        assert rp.secondary_selling_points == []
        assert rp.emphasise == []
        assert rp.deemphasise == []

    def test_role_positioning_unknown_field_forbidden(self) -> None:
        """T016 — FR-020, FR-027. Typo top-level field raises."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import RolePositioning

        data = {
            "role_family": "X",
            "primary_selling_point": "Y",
            "opening_angle": "Z",
            "role_familly": "typo",  # deliberate typo
        }
        with pytest.raises(ValidationError):
            RolePositioning.model_validate(data)


class TestFeature010PlannerConsumption:
    """T017 — planner build_prompt renders requirement_items in priority order."""

    def test_planner_build_prompt_renders_requirement_items_in_priority_order(
        self, minimal_state: WorkflowState
    ) -> None:
        """T017 — contracts §6.1. Priority-ordered weighted block surfaces."""
        from bewerbungs_agent.models.state import (
            EvidenceNeeded,
            Priority,
            RequirementCategory,
            RequirementExtraction,
            RequirementItem,
        )

        # Items intentionally out of order: low, high, medium.
        reqs = RequirementExtraction(
            core_requirement="x",
            requirement_items=[
                RequirementItem(
                    id="R3",
                    text="Familiarity with biomedical data",
                    priority=Priority.low,
                    category=RequirementCategory.optional,
                    evidence_needed=EvidenceNeeded.optional,
                ),
                RequirementItem(
                    id="R1",
                    text="Design scalable cloud infrastructure",
                    priority=Priority.high,
                    category=RequirementCategory.core,
                    evidence_needed=EvidenceNeeded.required,
                ),
                RequirementItem(
                    id="R2",
                    text="Write robust Python software",
                    priority=Priority.medium,
                    category=RequirementCategory.technical,
                    evidence_needed=EvidenceNeeded.preferred,
                ),
            ],
        )
        # Need an evidence_map too — reuse the minimal-state helper for evidence
        state = _state_with_evidence(minimal_state).model_copy(
            update={"requirements": reqs}
        )

        messages = build_prompt(state)
        content = messages[0]["content"]

        # Weighted Requirements block must be present
        assert "# Weighted Requirements" in content

        # High priority appears BEFORE medium appears BEFORE low
        idx_high = content.find("Design scalable cloud infrastructure")
        idx_medium = content.find("Write robust Python software")
        idx_low = content.find("Familiarity with biomedical data")
        assert idx_high != -1 and idx_medium != -1 and idx_low != -1
        assert idx_high < idx_medium < idx_low, (
            f"weighted items not priority-ordered; positions: "
            f"high={idx_high} medium={idx_medium} low={idx_low}"
        )

        # Each rendered line contains the markers
        assert "priority=high" in content
        assert "priority=medium" in content
        assert "evidence=required" in content
        assert "category=core" in content


class TestFeature010InfrastructureRegressionGuard:
    """T018 — FR-011, FR-026, SC-005. Updated GSK-style regression guard for new field names."""

    def test_planner_produces_infrastructure_first_role_family_on_fixture(self) -> None:
        """A correctly-positioned canned response → role_family is infra, not biomedical."""
        plan = {
            "template_id": "default_de_neutral",
            "selected_cv_variant": "cv_software",
            "mode": "standard",
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["Built scalable Python ML platforms"],
                    "evidence_refs": ["Built scalable Python ML platforms"],
                    "soft_skills": [],
                }
            ],
            "evidence_map": {
                "items": [
                    {
                        "claim": "Built scalable Python ML platforms",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv_software.md",
                        "passage": "Designed Python platform.",
                    }
                ],
                "known_gaps": [],
            },
            "role_positioning": {
                "role_family": "AI/ML platform engineering",
                "primary_selling_point": "Built scalable Python ML inference platforms for engineering teams.",
                "secondary_selling_points": [
                    "Biomedical-ML modelling experience as adjacent domain context.",
                ],
                "opening_angle": "Lead with infrastructure-builder identity; biomedical briefly.",
                "emphasise": ["platform reliability", "Python software quality"],
                "deemphasise": ["biomedical domain depth"],
                "risky_or_gap_areas": ["claims of deep oncall experience without anchors"],
            },
        }
        result = parse_response(plan, soft_skill_max=3)
        rp = result.role_positioning
        assert rp is not None

        # role_family contains infra terminology, NOT biomedical / data science
        family_lower = rp.role_family.lower()
        assert "platform" in family_lower or "infrastructure" in family_lower, (
            f"role_family must reflect infra framing; got {rp.role_family!r}"
        )
        assert "biomedical" not in family_lower
        assert "data science" not in family_lower

        # Biomedical only in secondary_selling_points
        assert "biomedical" not in rp.primary_selling_point.lower()
        assert any("biomedical" in s.lower() for s in rp.secondary_selling_points)

        # risky_or_gap_areas is populated
        assert rp.risky_or_gap_areas != []


# ---------------------------------------------------------------------------
# Feature 011 — ParagraphPlan + hiring-story ContentPlan
# ---------------------------------------------------------------------------


class TestFeature011ParagraphPlanSchema:
    """T002–T004 — ParagraphPlan field-level validation."""

    def test_paragraph_plan_main_message_is_single_string(self) -> None:
        """T002 — FR-004, FR-024."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import ParagraphPlan

        # Valid: short non-empty single string.
        p = ParagraphPlan(
            purpose="opening",
            main_message="Lead with infrastructure-builder identity.",
            max_claims=1,
            max_tools=0,
        )
        assert isinstance(p.main_message, str)
        assert p.main_message == "Lead with infrastructure-builder identity."

        # Reject empty string (min_length=1)
        with pytest.raises(ValidationError):
            ParagraphPlan(purpose="opening", main_message="", max_claims=1, max_tools=0)

        # Reject 401-char string (max_length=400; bumped from 300 to accommodate
        # German compound-noun length without crashing DE runs)
        with pytest.raises(ValidationError):
            ParagraphPlan(
                purpose="opening",
                main_message="x" * 401,
                max_claims=1,
                max_tools=0,
            )

    def test_paragraph_plan_unknown_field_forbidden(self) -> None:
        """T003 — FR-023, FR-029. Typo top-level field raises."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import ParagraphPlan

        with pytest.raises(ValidationError):
            ParagraphPlan.model_validate({
                "purpose": "opening",
                "main_message": "x",
                "max_claims": 1,
                "max_tools": 0,
                "purpoze": "typo",  # deliberate typo
            })

    def test_paragraph_plan_max_claims_max_tools_bounds(self) -> None:
        """T004 — FR-008, FR-009. Pydantic field bounds."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import ParagraphPlan

        # max_claims out of [1, 8]
        with pytest.raises(ValidationError):
            ParagraphPlan(purpose="x", main_message="y", max_claims=0, max_tools=0)
        with pytest.raises(ValidationError):
            ParagraphPlan(purpose="x", main_message="y", max_claims=9, max_tools=0)
        # max_tools out of [0, 12]
        with pytest.raises(ValidationError):
            ParagraphPlan(purpose="x", main_message="y", max_claims=1, max_tools=-1)
        with pytest.raises(ValidationError):
            ParagraphPlan(purpose="x", main_message="y", max_claims=1, max_tools=13)
        # Edges are valid
        ParagraphPlan(purpose="x", main_message="y", max_claims=1, max_tools=0)
        ParagraphPlan(purpose="x", main_message="y", max_claims=8, max_tools=12)


# ---------------------------------------------------------------------------
# Feature 011 — ContentPlan cross-field validators
# ---------------------------------------------------------------------------


def _content_plan_with_paragraphs(**overrides):
    """Build a minimal valid ContentPlan with paragraphs + evidence_map populated."""
    from bewerbungs_agent.config.models import WritingMode
    from bewerbungs_agent.models.state import (
        ContentPlan,
        EvidenceItem,
        EvidenceMap,
        ParagraphPlan,
        SectionPlan,
    )

    defaults: dict = {
        "template_id": "t",
        "selected_cv_variant": "cv_x",
        "mode": WritingMode.standard,
        "sections": [SectionPlan(title="role_fit", key_claims=["a"], evidence_refs=["claim-a"])],
        "evidence_map": EvidenceMap(items=[
            EvidenceItem(
                claim="claim-a",
                source_type="cv_variant",
                source_file="cvs/cv_x.md",
                passage="x",
            ),
            EvidenceItem(
                claim="claim-b",
                source_type="cv_variant",
                source_file="cvs/cv_x.md",
                passage="y",
            ),
        ]),
        "paragraphs": [
            ParagraphPlan(
                purpose="opening",
                main_message="Lead with infra identity.",
                evidence_refs=["claim-a"],
                max_claims=1,
                max_tools=0,
            ),
        ],
    }
    defaults.update(overrides)
    return ContentPlan(**defaults)


class TestFeature011ContentPlanValidators:
    """T005–T007 — three model validators on ContentPlan."""

    def test_content_plan_evidence_refs_exceeding_max_claims_raises(self) -> None:
        """T005 — FR-010, FR-027."""
        from pydantic import ValidationError

        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            ContentPlan,
            EvidenceItem,
            EvidenceMap,
            ParagraphPlan,
        )

        with pytest.raises(ValidationError) as exc_info:
            ContentPlan(
                template_id="t",
                selected_cv_variant="cv_x",
                mode=WritingMode.standard,
                evidence_map=EvidenceMap(items=[
                    EvidenceItem(claim=f"c{i}", source_type="cv_variant",
                                 source_file="cvs/cv_x.md", passage="x")
                    for i in range(4)
                ]),
                paragraphs=[
                    # max_claims=1 but evidence_refs has 2 entries
                    ParagraphPlan(
                        purpose="opening",
                        main_message="x",
                        evidence_refs=["c0", "c1"],
                        max_claims=1,
                        max_tools=0,
                    ),
                ],
            )
        err = str(exc_info.value)
        assert "max_claims" in err or "evidence_refs" in err

    def test_content_plan_opening_paragraph_max_claims_must_be_one_or_two(self) -> None:
        """T006 — FR-012. Opening paragraph max_claims constrained to {1, 2}."""
        from pydantic import ValidationError

        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            ContentPlan,
            EvidenceMap,
            ParagraphPlan,
        )

        def _make(opening_max_claims: int) -> ContentPlan:
            return ContentPlan(
                template_id="t",
                selected_cv_variant="cv_x",
                mode=WritingMode.standard,
                evidence_map=EvidenceMap(),
                paragraphs=[
                    ParagraphPlan(
                        purpose="opening",
                        main_message="x",
                        max_claims=opening_max_claims,
                        max_tools=0,
                    ),
                ],
            )

        # max_claims=1 and 2 must pass
        _make(1)
        _make(2)

        # 3, 4, 8 must fail (opening-specific rule even though field bound is 1..8)
        for bad in (3, 4, 8):
            with pytest.raises(ValidationError) as exc_info:
                _make(bad)
            assert "opening" in str(exc_info.value).lower() or "max_claims" in str(exc_info.value)

    def test_content_plan_paragraph_evidence_refs_not_in_evidence_map_raises(self) -> None:
        """T007 — FR-006. Paragraph evidence_refs must trace to evidence_map.items."""
        from pydantic import ValidationError

        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            ContentPlan,
            EvidenceItem,
            EvidenceMap,
            ParagraphPlan,
        )

        with pytest.raises(ValidationError) as exc_info:
            ContentPlan(
                template_id="t",
                selected_cv_variant="cv_x",
                mode=WritingMode.standard,
                evidence_map=EvidenceMap(items=[
                    EvidenceItem(claim="claim-a", source_type="cv_variant",
                                 source_file="cvs/cv_x.md", passage="x"),
                ]),
                paragraphs=[
                    ParagraphPlan(
                        purpose="opening",
                        main_message="x",
                        evidence_refs=["claim-a", "claim-z-missing"],
                        max_claims=2,
                        max_tools=0,
                    ),
                ],
            )
        err = str(exc_info.value)
        assert "claim-z-missing" in err


# ---------------------------------------------------------------------------
# Feature 011 — opening paragraph reflects role_positioning (regression guard)
# ---------------------------------------------------------------------------


class TestFeature011OpeningReflectsRolePositioning:
    """T008 — FR-011, FR-025, SC-003. Deterministic regression guard."""

    def test_opening_paragraph_main_message_references_role_family(self) -> None:
        """A canned planner response → opening main_message references infra terms.

        Asserts on substring presence/absence in the planner's CANNED OUTPUT
        (not on LLM behaviour). The role of this test is to pin the contract
        downstream consumers depend on: when role_positioning.role_family is
        infrastructure-flavoured, the opening main_message must reflect that.
        """
        plan = {
            "template_id": "default_de_neutral",
            "selected_cv_variant": "cv_software",
            "mode": "standard",
            "sections": [
                {
                    "title": "role_fit",
                    "key_claims": ["Built scalable Python ML platforms"],
                    "evidence_refs": ["Built scalable Python ML platforms"],
                    "soft_skills": [],
                }
            ],
            "evidence_map": {
                "items": [
                    {
                        "claim": "Built scalable Python ML platforms",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv_software.md",
                        "passage": "Designed Python platform.",
                    }
                ],
                "known_gaps": [],
            },
            "role_positioning": {
                "role_family": "AI/ML platform engineering",
                "primary_selling_point": "Built scalable Python ML inference platforms.",
                "opening_angle": "Lead with infrastructure-builder identity.",
                "emphasise": ["platform reliability"],
                "deemphasise": ["biomedical domain depth"],
                "risky_or_gap_areas": [],
                "secondary_selling_points": ["Biomedical-ML adjacent context"],
            },
            "letter_thesis": (
                "Built and scaled Python ML infrastructure for engineering teams."
            ),
            "paragraphs": [
                {
                    "purpose": "opening",
                    "main_message": (
                        "I build the AI/ML infrastructure your software engineers "
                        "rely on, anchored in scalable Python platforms."
                    ),
                    "requirement_ids": [],
                    "evidence_refs": ["Built scalable Python ML platforms"],
                    "emphasise": ["platform reliability"],
                    "deemphasise": [],
                    "max_claims": 1,
                    "max_tools": 0,
                },
                {
                    "purpose": "platform_credibility",
                    "main_message": "Ran inference fleets at scale with tight SLOs.",
                    "requirement_ids": [],
                    "evidence_refs": ["Built scalable Python ML platforms"],
                    "emphasise": [],
                    "deemphasise": [],
                    "max_claims": 2,
                    "max_tools": 4,
                },
            ],
        }
        result = parse_response(plan, soft_skill_max=3)
        assert result.paragraphs, "paragraphs must be populated"

        opening = result.paragraphs[0]
        assert opening.purpose == "opening"

        # Opening main_message must reference infra-flavoured terms.
        msg_lower = opening.main_message.lower()
        infra_terms = ("infrastructure", "platform", "ai/ml", "software")
        assert any(term in msg_lower for term in infra_terms), (
            f"opening main_message must reference infra terms; got {opening.main_message!r}"
        )
        assert "biomedical" not in msg_lower
        assert "data science" not in msg_lower

        # Opening max_claims must be 1 or 2 (validator)
        assert opening.max_claims in (1, 2)


# ---------------------------------------------------------------------------
# Feature 011 — stage-level requirement_ids cross-reference (T014)
# ---------------------------------------------------------------------------


class TestFeature011RequirementIdsCrossReference:
    """T014 — FR-005, FR-030. plan_content() validates requirement_ids."""

    def test_paragraph_requirement_ids_unknown_id_raises_in_plan_content(
        self, mock_llm_client, monkeypatch
    ) -> None:
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import (
            EvidenceItem,
            EvidenceMap,
            EvidenceNeeded,
            JobContext,
            Priority,
            RequirementCategory,
            RequirementExtraction,
            RequirementItem,
            WorkflowState,
        )

        # Mock LLM to return a canned plan whose paragraphs[0] references R1 + R99.
        # R1 exists in requirement_items; R99 does not.
        canned_plan = {
            "template_id": "t",
            "selected_cv_variant": "cv_x",
            "mode": "standard",
            "sections": [],
            "evidence_map": {
                "items": [
                    {"claim": "claim-a", "source_type": "cv_variant",
                     "source_file": "cvs/cv_x.md", "passage": "x"},
                ],
                "known_gaps": [],
            },
            "paragraphs": [
                {
                    "purpose": "opening",
                    "main_message": "x",
                    "requirement_ids": ["R1", "R99"],
                    "evidence_refs": ["claim-a"],
                    "emphasise": [],
                    "deemphasise": [],
                    "max_claims": 1,
                    "max_tools": 0,
                },
            ],
        }
        mock_llm_client.call.return_value = canned_plan

        # Build a state with requirements that have R1 but not R99
        from bewerbungs_agent.config.models import (
            CVSelectionMode,
            LengthMode,
            MergedConfig,
        )
        config = MergedConfig(
            template_id="t",
            language="DE",
            length=LengthMode.normal,
            tone="neutral",
            mode=WritingMode.standard,
            cv_selection=CVSelectionMode.automatic,
            cv_tailoring=True,
            soft_skill_max=3,
            output_sections=["letter"],
            validation_rules={},
            job_file=Path("data/examples/jobs/sample.md"),
            output_dir=Path("outputs"),
        )
        state = WorkflowState(
            config=config,
            job_context=JobContext(raw_job_text="x"),
            requirements=RequirementExtraction(
                core_requirement="x",
                requirement_items=[
                    RequirementItem(
                        id="R1",
                        text="some requirement",
                        priority=Priority.high,
                        category=RequirementCategory.core,
                        evidence_needed=EvidenceNeeded.required,
                    ),
                ],
            ),
            evidence_map=EvidenceMap(items=[
                EvidenceItem(claim="claim-a", source_type="cv_variant",
                             source_file="cvs/cv_x.md", passage="x"),
            ]),
        )

        # Patch get_llm_client at the source module (plan_content imports it lazily)
        import bewerbungs_agent.utils.llm_client as llm_mod
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        from bewerbungs_agent.stages.plan_content import plan_content
        with pytest.raises(ValueError) as exc_info:
            plan_content(state)
        err = str(exc_info.value)
        assert "R99" in err
        assert "0" in err or "opening" in err.lower()  # paragraph index or purpose


# ---------------------------------------------------------------------------
# Feature 011 US3 — backward compatibility (legacy plans, extra="forbid")
# ---------------------------------------------------------------------------


class TestFeature011BackwardCompat:
    """T023, T024 — FR-022, FR-023, FR-024, SC-005, SC-007."""

    def test_legacy_content_plan_without_paragraphs_loads_with_defaults(self) -> None:
        """T023 — Legacy plans (no paragraphs / no letter_thesis) load with empty
        defaults; existing validators do not fire when paragraphs is empty.
        """
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import ContentPlan, SectionPlan

        # Build a strictly legacy-shape plan (no paragraphs, no letter_thesis)
        plan = ContentPlan(
            template_id="default_de_neutral",
            selected_cv_variant="cv_software",
            mode=WritingMode.standard,
            sections=[
                SectionPlan(
                    title="role_fit",
                    key_claims=["x"],
                    evidence_refs=["x"],
                )
            ],
            selected_soft_skills=[],
            evidence_map=EvidenceMap(
                items=[
                    EvidenceItem(
                        claim="x",
                        source_type="cv_variant",
                        source_file="cvs/cv.md",
                        passage="x",
                    )
                ]
            ),
        )

        # New fields default to safe values
        assert plan.letter_thesis is None
        assert plan.paragraphs == []

        # Existing legacy fields still work as before
        assert plan.template_id == "default_de_neutral"
        assert len(plan.sections) == 1

        # Serialisation round-trips cleanly
        dumped = plan.model_dump_json()
        round_tripped = ContentPlan.model_validate_json(dumped)
        assert round_tripped.paragraphs == []
        assert round_tripped.letter_thesis is None

    def test_content_plan_unknown_field_forbidden(self) -> None:
        """T024 — extra='forbid' on ContentPlan rejects unknown top-level fields.

        Guards against silent schema drift when planners or fixtures invent
        fields the writer would never see.
        """
        from pydantic import ValidationError

        from bewerbungs_agent.config.models import WritingMode

        bad_payload = {
            "template_id": "t",
            "selected_cv_variant": "cv_x",
            "mode": WritingMode.standard.value,
            "sections": [
                {"title": "role_fit", "key_claims": ["a"], "evidence_refs": ["a"]}
            ],
            "selected_soft_skills": [],
            "evidence_map": {
                "items": [
                    {
                        "claim": "a",
                        "source_type": "cv_variant",
                        "source_file": "cvs/cv.md",
                        "passage": "a",
                    }
                ]
            },
            # The illegal extra:
            "totally_made_up_field": "should not be allowed",
        }
        with pytest.raises(ValidationError) as exc_info:
            ContentPlan.model_validate(bad_payload)
        assert "totally_made_up_field" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Feature 013 US1 — planner consumes NarrativeStrategy
# ---------------------------------------------------------------------------


class TestFeature013NarrativeStrategyInPlanner:
    """T014, T015 — planner prompt block + proof_points_to_avoid filter."""

    def test_planner_prompt_includes_narrative_strategy_block(
        self, minimal_state: WorkflowState
    ) -> None:
        """T014 — narrative_strategy block surfaces in the planner prompt."""
        from bewerbungs_agent.models.state import NarrativeStrategy

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
        state = minimal_state.model_copy(update={"narrative_strategy": ns})
        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "# Narrative Strategy" in content
        assert "candidate_story:" in content
        assert "bridge:" in content
        assert "opening_angle:" in content
        assert "proof_points_to_avoid:" in content
        assert "anti_patterns:" in content
        assert "Biomedical PhD" in content

    def test_planner_drops_paragraphs_in_proof_points_to_avoid(
        self, minimal_state: WorkflowState, monkeypatch, mock_llm_client
    ) -> None:
        """T015 — paragraphs whose evidence_refs overlap proof_points_to_avoid are dropped."""
        from bewerbungs_agent.config.models import WritingMode
        from bewerbungs_agent.models.state import NarrativeStrategy

        canned_plan = {
            "template_id": "default_de_neutral",
            "selected_cv_variant": "cv_software",
            "mode": WritingMode.standard.value,
            "sections": [],
            "selected_soft_skills": [],
            "evidence_map": {
                "items": [
                    {"claim": "A", "source_type": "cv_variant", "source_file": "cv.md", "passage": "A"},
                    {"claim": "B", "source_type": "cv_variant", "source_file": "cv.md", "passage": "B"},
                    {"claim": "C", "source_type": "cv_variant", "source_file": "cv.md", "passage": "C"},
                ],
                "known_gaps": [],
                "assumptions": [],
            },
            "paragraphs": [
                {"purpose": "opening", "main_message": "msg A", "max_claims": 1, "max_tools": 0,
                 "evidence_refs": ["A"], "requirement_ids": [], "emphasise": [], "deemphasise": []},
                {"purpose": "credibility", "main_message": "msg B", "max_claims": 2, "max_tools": 4,
                 "evidence_refs": ["B"], "requirement_ids": [], "emphasise": [], "deemphasise": []},
                {"purpose": "closing", "main_message": "msg C", "max_claims": 1, "max_tools": 0,
                 "evidence_refs": ["C"], "requirement_ids": [], "emphasise": [], "deemphasise": []},
            ],
        }
        mock_llm_client.call.return_value = canned_plan

        import bewerbungs_agent.utils.llm_client as llm_mod
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        ns = NarrativeStrategy(
            candidate_story="x", role_story="x", bridge="x",
            opening_angle="x", tone_guidance="x",
            proof_points_to_use=["A"],
            proof_points_to_avoid=["B"],
            anti_patterns=[],
            transfer_framing_guidance="",
        )
        state = minimal_state.model_copy(update={"narrative_strategy": ns})

        from bewerbungs_agent.stages.plan_content import plan_content
        result = plan_content(state)
        plan = result["content_plan"]
        # Paragraph 1 (evidence_refs=['B']) MUST be filtered out
        purposes = [p.purpose for p in plan.paragraphs]
        assert "opening" in purposes
        assert "credibility" not in purposes  # filtered
        assert "closing" in purposes
        assert len(plan.paragraphs) == 2
