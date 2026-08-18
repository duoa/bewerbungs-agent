"""Unit tests for stages.role_position — TDD (feature 013, T004).

The role_position stage is extracted from plan_content so feature 013 can
insert narrative_strategy between role positioning and content planning.
The prompt and RolePositioning schema are unchanged from feature 010.
"""

from __future__ import annotations

import pytest

from bewerbungs_agent.models.state import (
    JobContext,
    Priority,
    RequirementCategory,
    RequirementExtraction,
    RequirementItem,
    EvidenceNeeded,
    RolePositioning,
    WorkflowState,
)


def _state_with_job(minimal_state: WorkflowState) -> WorkflowState:
    job = JobContext(
        raw_job_text="We are hiring an AI/ML platform engineer ...",
        job_title="Senior AI/ML Platform Engineer",
        company_name="Bayer",
    )
    reqs = RequirementExtraction(
        core_requirement="Build and operate ML inference platforms.",
        technical_requirements=["Python", "Kubernetes", "AWS"],
        domain_requirement=None,
        collaboration_requirement="Cross-functional with data scientists.",
        requirement_items=[
            RequirementItem(
                id="R1",
                text="5+ years Python in production ML platforms",
                priority=Priority.high,
                category=RequirementCategory.technical,
                evidence_needed=EvidenceNeeded.required,
                source_excerpt="five or more years of hands-on Python",
            ),
        ],
    )
    return minimal_state.model_copy(update={"job_context": job, "requirements": reqs})


class TestRolePositionStage:
    """T004 — feature 013 extracted stage."""

    def test_role_position_prompt_includes_job_description(
        self, minimal_state: WorkflowState
    ) -> None:
        from bewerbungs_agent.stages.role_position import build_prompt

        state = _state_with_job(minimal_state)
        messages = build_prompt(state)
        combined = " ".join(m["content"] for m in messages)

        assert "AI/ML platform engineer" in combined
        assert "# Weighted Requirements" in combined
        assert "R1" in combined
        assert "5+ years Python" in combined

    def test_role_position_parse_response_validates_schema(self) -> None:
        from bewerbungs_agent.stages.role_position import parse_response

        canned = {
            "role_family": "AI/ML platform engineering",
            "primary_selling_point": "Built scalable Python ML inference platforms.",
            "secondary_selling_points": ["Adjacent biomedical-ML context"],
            "emphasise": ["platform reliability"],
            "deemphasise": ["biomedical domain depth"],
            "opening_angle": "Lead with infrastructure-builder identity.",
            "risky_or_gap_areas": [],
        }
        rp = parse_response(canned)
        assert isinstance(rp, RolePositioning)
        assert rp.role_family == "AI/ML platform engineering"
        assert rp.secondary_selling_points == ["Adjacent biomedical-ML context"]
        assert rp.opening_angle == "Lead with infrastructure-builder identity."

    def test_role_position_node_writes_role_positioning_to_state(
        self, minimal_state: WorkflowState, monkeypatch, mock_llm_client
    ) -> None:
        """The LangGraph node returns {'role_positioning': RolePositioning(...)}."""
        from bewerbungs_agent.stages.role_position import role_position
        import bewerbungs_agent.utils.llm_client as llm_mod

        canned = {
            "role_family": "AI/ML platform engineering",
            "primary_selling_point": "Built scalable Python ML inference platforms.",
            "secondary_selling_points": [],
            "emphasise": ["platform reliability"],
            "deemphasise": [],
            "opening_angle": "Lead with infrastructure-builder identity.",
            "risky_or_gap_areas": [],
        }
        mock_llm_client.call.return_value = canned
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda *a, **kw: mock_llm_client)

        state = _state_with_job(minimal_state)
        result = role_position(state)

        assert "role_positioning" in result
        assert isinstance(result["role_positioning"], RolePositioning)
        assert result["role_positioning"].role_family == "AI/ML platform engineering"
        assert mock_llm_client.call.called
