"""Unit tests for stages.select_cv_variant — TDD."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bewerbungs_agent.models.state import (
    CVVariantMetadata,
    InternalKnowledge,
    RequirementExtraction,
    SelectedCV,
    WorkflowState,
)
from bewerbungs_agent.stages.select_cv_variant import build_prompt, select_cv_variant


def _make_knowledge(tmp_path: Path, variant_ids: list[str]) -> InternalKnowledge:
    variants = []
    for vid in variant_ids:
        cv_file = tmp_path / f"{vid}.md"
        cv_file.write_text(f"# {vid}\nCV content for {vid}.")
        meta = CVVariantMetadata(
            variant_id=vid,
            file_path=cv_file,
            role_families=["software-engineering"],
            skills=["Python"],
        )
        variants.append(meta)
    return InternalKnowledge(
        master_profile={"name": "Test"},
        cv_variants=variants,
        personal_skills="",
    )


def _state_with_knowledge(
    minimal_state: WorkflowState, knowledge: InternalKnowledge
) -> WorkflowState:
    reqs = RequirementExtraction(
        core_requirement="Python expertise",
        technical_requirements=["Spark"],
    )
    return minimal_state.model_copy(
        update={"knowledge": knowledge, "requirements": reqs}
    )


class TestBuildPrompt:
    def test_includes_variant_list(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        knowledge = _make_knowledge(tmp_path, ["cv_software", "cv_data"])
        state = _state_with_knowledge(minimal_state, knowledge)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "cv_software" in combined
        assert "cv_data" in combined

    def test_includes_requirements(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        knowledge = _make_knowledge(tmp_path, ["cv_software"])
        state = _state_with_knowledge(minimal_state, knowledge)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "Python expertise" in combined


class TestSelectCvVariant:
    def test_override_skips_llm(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """cv_variant_override set → no LLM call, correct variant returned."""
        knowledge = _make_knowledge(tmp_path, ["cv_software", "cv_data"])
        config = minimal_state.config.model_copy(
            update={"cv_variant_override": "cv_data"}
        )
        state = minimal_state.model_copy(
            update={"config": config, "knowledge": knowledge}
        )
        result = select_cv_variant(state)
        assert result["selected_cv"].variant_id == "cv_data"

    def test_unknown_override_raises(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        knowledge = _make_knowledge(tmp_path, ["cv_software"])
        config = minimal_state.config.model_copy(
            update={"cv_variant_override": "cv_nonexistent"}
        )
        state = minimal_state.model_copy(
            update={"config": config, "knowledge": knowledge}
        )
        with pytest.raises(ValueError, match="cv_nonexistent"):
            select_cv_variant(state)

    def test_no_variants_raises(self, minimal_state: WorkflowState) -> None:
        knowledge = InternalKnowledge(
            master_profile={}, cv_variants=[], personal_skills=""
        )
        state = minimal_state.model_copy(update={"knowledge": knowledge})
        with pytest.raises(ValueError, match="No CV variants"):
            select_cv_variant(state)

    def test_llm_selection_returns_selected_cv(
        self, minimal_state: WorkflowState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM returns a valid variant_id → SelectedCV with that variant."""
        knowledge = _make_knowledge(tmp_path, ["cv_software"])
        state = _state_with_knowledge(minimal_state, knowledge)

        mock_client = MagicMock()
        mock_client.call.return_value = {
            "variant_id": "cv_software",
            "selection_reason": "Best match for role",
        }
        monkeypatch.setattr(
            "bewerbungs_agent.stages.select_cv_variant.get_llm_client",
            lambda: mock_client,
        )

        result = select_cv_variant(state)
        assert isinstance(result["selected_cv"], SelectedCV)
        assert result["selected_cv"].variant_id == "cv_software"
        assert mock_client.call.called
