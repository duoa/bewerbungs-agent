"""Unit tests for the tailor_cv stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bewerbungs_agent.models.state import (
    CVVariantMetadata,
    EvidenceItem,
    EvidenceMap,
    InternalKnowledge,
    RequirementExtraction,
    SelectedCV,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_selected_cv(tmp_path: Path, variant_id: str = "cv_software") -> SelectedCV:
    cv_file = tmp_path / f"{variant_id}.md"
    cv_file.write_text(
        "# CV\n\n## Experience\n\nSoftware Engineer at Acme Corp 2020–2023\n"
        "Led migration to Kubernetes.\n\n## Skills\n\nPython, Kubernetes, PostgreSQL\n",
        encoding="utf-8",
    )
    metadata = CVVariantMetadata(
        variant_id=variant_id,
        file_path=cv_file,
        role_families=["software"],
        skills=["Python", "Kubernetes"],
        summary="Software engineer CV",
    )
    return SelectedCV(
        variant_id=variant_id,
        metadata=metadata,
        full_text=cv_file.read_text(encoding="utf-8"),
        selection_reason="best match",
    )


def _make_requirements() -> RequirementExtraction:
    return RequirementExtraction(
        core_requirement="Build backend services for a data platform",
        technical_requirements=["Python", "Kubernetes"],
        must_include=[],
        must_avoid=[],
    )


def _make_evidence_map() -> EvidenceMap:
    return EvidenceMap(
        items=[
            EvidenceItem(
                claim="Led migration to Kubernetes at Acme Corp",
                source_type="cv_variant",
                source_file="cvs/cv_software.md",
                passage="Led migration to Kubernetes.",
            ),
        ],
        known_gaps=[],
        assumptions=[],
    )


def _state_with_cv_and_evidence(
    base_state: WorkflowState, selected_cv: SelectedCV, evidence_map: EvidenceMap
) -> WorkflowState:
    requirements = _make_requirements()
    return base_state.model_copy(
        update={
            "selected_cv": selected_cv,
            "evidence_map": evidence_map,
            "requirements": requirements,
        }
    )


# ---------------------------------------------------------------------------
# Tests: build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_contains_selected_cv_text(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must include selected CV full_text."""
        from bewerbungs_agent.stages.tailor_cv import build_prompt

        selected_cv = _make_selected_cv(tmp_path)
        evidence_map = _make_evidence_map()
        state = _state_with_cv_and_evidence(minimal_state, selected_cv, evidence_map)

        messages = build_prompt(state)
        assert len(messages) == 1
        content = messages[0]["content"]
        assert "Software Engineer at Acme Corp" in content

    def test_contains_requirements(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must include the job requirements."""
        from bewerbungs_agent.stages.tailor_cv import build_prompt

        selected_cv = _make_selected_cv(tmp_path)
        evidence_map = _make_evidence_map()
        state = _state_with_cv_and_evidence(minimal_state, selected_cv, evidence_map)

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "Build backend services" in content

    def test_contains_evidence_map(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must include evidence claims."""
        from bewerbungs_agent.stages.tailor_cv import build_prompt

        selected_cv = _make_selected_cv(tmp_path)
        evidence_map = _make_evidence_map()
        state = _state_with_cv_and_evidence(minimal_state, selected_cv, evidence_map)

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "Led migration to Kubernetes" in content

    def test_does_not_contain_raw_internal_knowledge(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must NOT dump InternalKnowledge wholesale.

        InternalKnowledge is a large object; passing it raw would break the
        Approved Sources Only principle. Only selected_cv + evidence_map may
        reach the LLM at this stage.
        """
        from bewerbungs_agent.stages.tailor_cv import build_prompt

        cv_file = tmp_path / "cv.md"
        cv_file.write_text("CV content", encoding="utf-8")
        metadata = CVVariantMetadata(
            variant_id="cv_software",
            file_path=cv_file,
            role_families=["software"],
            skills=["Python"],
            summary="sw cv",
        )
        selected_cv = SelectedCV(
            variant_id="cv_software",
            metadata=metadata,
            full_text="CV content",
            selection_reason="best match",
        )
        evidence_map = _make_evidence_map()

        # Inject InternalKnowledge with a distinctive string that must NOT
        # appear in the prompt.
        secret_string = "MASTER_PROFILE_SHOULD_NOT_LEAK"
        knowledge = InternalKnowledge(
            master_profile={"_secret": secret_string},
            cv_variants=[metadata],
            personal_skills=secret_string,
            project_docs={},
            previous_letters={},
        )
        state = minimal_state.model_copy(
            update={
                "selected_cv": selected_cv,
                "evidence_map": evidence_map,
                "requirements": _make_requirements(),
                "knowledge": knowledge,
            }
        )

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert secret_string not in content


# ---------------------------------------------------------------------------
# Tests: parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_response_returns_plan(self) -> None:
        """Valid actions + non-empty tailored_text → CVTailoringPlan returned."""
        from bewerbungs_agent.stages.tailor_cv import parse_response

        data: dict[str, Any] = {
            "base_variant_id": "cv_software",
            "tailored_text": "# CV\n\nTailored content here.\n",
            "changes": [
                {
                    "section": "Experience",
                    "action": "emphasise",
                    "rationale": "Matches Kubernetes requirement",
                    "evidence_ref": "Led migration to Kubernetes at Acme Corp",
                }
            ],
        }
        plan = parse_response(data)
        assert plan.base_variant_id == "cv_software"
        assert len(plan.changes) == 1
        assert plan.tailored_text != ""

    def test_invalid_action_raises(self) -> None:
        """An action value outside the allowed set must raise ValueError."""
        from bewerbungs_agent.stages.tailor_cv import parse_response

        data: dict[str, Any] = {
            "base_variant_id": "cv_software",
            "tailored_text": "Tailored.",
            "changes": [
                {
                    "section": "Skills",
                    "action": "invent",  # not in allowed set
                    "rationale": "Adding made-up skill",
                    "evidence_ref": None,
                }
            ],
        }
        with pytest.raises(ValueError, match="invent"):
            parse_response(data)

    def test_all_valid_actions_accepted(self) -> None:
        """All four allowed actions must be accepted without error."""
        from bewerbungs_agent.stages.tailor_cv import parse_response

        for action in ("emphasise", "reorder", "include", "exclude"):
            data: dict[str, Any] = {
                "base_variant_id": "cv_software",
                "tailored_text": "Tailored.",
                "changes": [
                    {
                        "section": "Experience",
                        "action": action,
                        "rationale": "test",
                        "evidence_ref": None,
                    }
                ],
            }
            plan = parse_response(data)
            assert plan.changes[0].action == action

    def test_empty_tailored_text_raises(self) -> None:
        """Empty tailored_text must raise ValueError."""
        from bewerbungs_agent.stages.tailor_cv import parse_response

        data: dict[str, Any] = {
            "base_variant_id": "cv_software",
            "tailored_text": "",
            "changes": [],
        }
        with pytest.raises(ValueError, match="tailored_text"):
            parse_response(data)

    def test_no_changes_accepted(self) -> None:
        """An empty changes list is valid — the CV may require no modification."""
        from bewerbungs_agent.stages.tailor_cv import parse_response

        data: dict[str, Any] = {
            "base_variant_id": "cv_software",
            "tailored_text": "# CV\n\nOriginal content.\n",
            "changes": [],
        }
        plan = parse_response(data)
        assert plan.changes == []
