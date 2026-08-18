"""Unit tests for stages.extract_requirements — TDD."""

from __future__ import annotations

import pytest

from bewerbungs_agent.models.state import (
    JobContext,
    RequirementExtraction,
    WorkflowState,
)
from bewerbungs_agent.stages.extract_requirements import build_prompt, parse_response


def _state_with_job(minimal_state: WorkflowState, job_text: str = "We need a Python engineer.") -> WorkflowState:
    return minimal_state.model_copy(
        update={"job_context": JobContext(raw_job_text=job_text)}
    )


class TestBuildPrompt:
    def test_contains_job_text(self, minimal_state: WorkflowState) -> None:
        """build_prompt includes the raw job text."""
        state = _state_with_job(minimal_state, "Looking for a senior Python dev.")
        messages = build_prompt(state)
        assert isinstance(messages, list)
        assert len(messages) >= 1
        combined = " ".join(str(m) for m in messages)
        assert "senior Python dev" in combined

    def test_includes_company_text_when_present(self, minimal_state: WorkflowState) -> None:
        """build_prompt includes company text when present."""
        state = minimal_state.model_copy(
            update={
                "job_context": JobContext(
                    raw_job_text="Python role",
                    raw_company_text="Acme Corp builds rockets.",
                )
            }
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "Acme Corp" in combined

    def test_returns_list_of_dicts(self, minimal_state: WorkflowState) -> None:
        state = _state_with_job(minimal_state)
        messages = build_prompt(state)
        assert all(isinstance(m, dict) for m in messages)


class TestParseResponse:
    def test_valid_response(self) -> None:
        data = {
            "core_requirement": "Python expertise",
            "technical_requirements": ["Spark", "SQL"],
            "tone_signals": ["collaborative"],
            "must_include": [],
            "must_avoid": [],
        }
        result = parse_response(data)
        assert isinstance(result, RequirementExtraction)
        assert result.core_requirement == "Python expertise"

    def test_raises_when_core_requirement_empty(self) -> None:
        data = {
            "core_requirement": "",
            "technical_requirements": [],
        }
        with pytest.raises(ValueError, match="core_requirement"):
            parse_response(data)

    def test_raises_when_core_requirement_whitespace(self) -> None:
        data = {"core_requirement": "   ", "technical_requirements": []}
        with pytest.raises(ValueError, match="core_requirement"):
            parse_response(data)

    def test_many_technical_requirements_accepted(self) -> None:
        data = {
            "core_requirement": "Python",
            "technical_requirements": [f"tech_{i}" for i in range(10)],
        }
        result = parse_response(data)
        assert len(result.technical_requirements) == 10

    def test_zero_technical_requirements_is_ok(self) -> None:
        data = {"core_requirement": "Python", "technical_requirements": []}
        result = parse_response(data)
        assert result.technical_requirements == []


# ---------------------------------------------------------------------------
# Feature 010 US1 — RequirementItem + weighted requirement_items list
# ---------------------------------------------------------------------------


class TestFeature010RequirementItems:
    """T002–T007 — weighted requirement extraction + back-fill."""

    def test_requirement_extraction_parses_mocked_llm_output_with_items(self) -> None:
        """T002 — FR-001, FR-004, FR-021. Canned LLM payload with full enum coverage."""
        from bewerbungs_agent.models.state import (
            EvidenceNeeded,
            Priority,
            RequirementCategory,
        )

        data = {
            "core_requirement": "Design and operate scalable cloud infrastructure",
            "technical_requirements": ["Python", "AWS"],
            "requirement_items": [
                {
                    "id": "R1",
                    "text": "Design and operate scalable cloud infrastructure",
                    "priority": "high",
                    "category": "core",
                    "evidence_needed": "required",
                    "source_excerpt": "Design and operate scalable cloud infrastructure...",
                },
                {
                    "id": "R2",
                    "text": "Write robust Python software",
                    "priority": "medium",
                    "category": "technical",
                    "evidence_needed": "preferred",
                },
                {
                    "id": "R3",
                    "text": "Familiarity with biomedical data",
                    "priority": "low",
                    "category": "optional",
                    "evidence_needed": "optional",
                },
            ],
        }
        result = parse_response(data)
        assert len(result.requirement_items) == 3
        # Each enum-typed field is the actual enum value, not a bare string.
        assert result.requirement_items[0].priority == Priority.high
        assert result.requirement_items[1].category == RequirementCategory.technical
        assert result.requirement_items[2].evidence_needed == EvidenceNeeded.optional
        # source_excerpt populated for item 0, defaults to None for items 1+2.
        assert result.requirement_items[0].source_excerpt is not None
        assert result.requirement_items[1].source_excerpt is None
        assert result.requirement_items[2].source_excerpt is None

    def test_requirement_item_defaults_for_missing_optional_fields(self) -> None:
        """T003 — FR-004. Minimal item omits source_excerpt → defaults to None."""
        from bewerbungs_agent.models.state import RequirementItem

        item = RequirementItem.model_validate({
            "id": "R1",
            "text": "x",
            "priority": "high",
            "category": "core",
            "evidence_needed": "required",
        })
        assert item.source_excerpt is None

    def test_requirement_item_invalid_priority_value_raises(self) -> None:
        """T004 — FR-002, FR-021. priority=urgent is not in the enum."""
        from pydantic import ValidationError

        from bewerbungs_agent.models.state import RequirementItem

        with pytest.raises(ValidationError) as exc_info:
            RequirementItem.model_validate({
                "id": "R1",
                "text": "x",
                "priority": "urgent",
                "category": "core",
                "evidence_needed": "required",
            })
        assert "priority" in str(exc_info.value).lower() or "enum" in str(exc_info.value).lower()

    def test_requirement_extraction_legacy_payload_loads(self) -> None:
        """T005 — FR-018, FR-023. Pre-feature-010 payload (no requirement_items) loads."""
        data = {
            "core_requirement": "Python engineering",
            "technical_requirements": ["Python", "Postgres"],
            "collaboration_requirement": "small team",
        }
        result = parse_response(data)
        assert result.requirement_items == []
        assert result.core_requirement == "Python engineering"
        assert result.technical_requirements == ["Python", "Postgres"]

    def test_requirement_item_duplicate_ids_raise(self) -> None:
        """T006 — FR-005. Duplicate id within requirement_items raises."""
        from pydantic import ValidationError

        data = {
            "core_requirement": "x",
            "requirement_items": [
                {
                    "id": "R1",
                    "text": "first",
                    "priority": "high",
                    "category": "core",
                    "evidence_needed": "required",
                },
                {
                    "id": "R1",  # duplicate
                    "text": "second",
                    "priority": "medium",
                    "category": "technical",
                    "evidence_needed": "preferred",
                },
            ],
        }
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            parse_response(data)
        msg = str(exc_info.value).lower()
        assert "duplicate" in msg or "id" in msg

    def test_requirement_extraction_backfills_all_requirements_from_items(self) -> None:
        """T007 — FR-018, research §R9. Back-fill validator populates all_requirements."""
        data = {
            "core_requirement": "x",
            "requirement_items": [
                {
                    "id": "R1",
                    "text": "Design scalable infra",
                    "priority": "high",
                    "category": "core",
                    "evidence_needed": "required",
                },
                {
                    "id": "R2",
                    "text": "Write robust Python",
                    "priority": "medium",
                    "category": "technical",
                    "evidence_needed": "preferred",
                },
            ],
        }
        result = parse_response(data)
        # Legacy field back-filled from items
        assert len(result.all_requirements) == 2
        assert result.all_requirements[0].label == "core"
        assert result.all_requirements[0].text == "Design scalable infra"
        assert result.all_requirements[0].priority == 1  # high → 1
        assert result.all_requirements[1].label == "technical"
        assert result.all_requirements[1].priority == 2  # medium → 2


# ---------------------------------------------------------------------------
# Feature 010 US3 — backward-compat: unknown field forbidden
# ---------------------------------------------------------------------------


class TestFeature010BackwardCompat:
    """T026 — FR-020, FR-027 (RequirementExtraction half)."""

    def test_requirement_extraction_unknown_field_forbidden(self) -> None:
        """RequirementExtraction MUST reject typo top-level fields."""
        from pydantic import ValidationError

        data = {
            "core_requirement": "x",
            "corre_requirement": "typo",  # deliberate typo
        }
        with pytest.raises(ValidationError) as exc_info:
            parse_response(data)
        assert "corre_requirement" in str(exc_info.value) or "extra" in str(exc_info.value).lower()
