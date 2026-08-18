"""Unit tests for stages.build_evidence_map — TDD."""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungs_agent.models.state import (
    CVVariantMetadata,
    EvidenceMap,
    InternalKnowledge,
    RequirementExtraction,
    SelectedCV,
    WorkflowState,
)
from bewerbungs_agent.stages.build_evidence_map import build_prompt, parse_response


def _make_full_state(minimal_state: WorkflowState, tmp_path: Path) -> WorkflowState:
    cv_file = tmp_path / "cv_software.md"
    cv_file.write_text("# CV\nPython expert with Spark experience.")
    meta = CVVariantMetadata(
        variant_id="cv_software",
        file_path=cv_file,
        role_families=["software"],
        skills=["Python"],
    )
    knowledge = InternalKnowledge(
        master_profile={"name": "Test"},
        cv_variants=[meta],
        personal_skills="End-to-End Ownership: led full migrations",
    )
    selected_cv = SelectedCV(
        variant_id="cv_software",
        metadata=meta,
        full_text=cv_file.read_text(),
    )
    reqs = RequirementExtraction(
        core_requirement="Python expertise",
        technical_requirements=["Spark"],
    )
    return minimal_state.model_copy(
        update={
            "knowledge": knowledge,
            "selected_cv": selected_cv,
            "requirements": reqs,
        }
    )


class TestBuildPrompt:
    def test_includes_requirements(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        state = _make_full_state(minimal_state, tmp_path)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert "Python expertise" in combined

    def test_includes_approved_sources(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        state = _make_full_state(minimal_state, tmp_path)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        # Should reference the selected CV text or personal skills
        assert "Python" in combined

    def test_passes_full_cv_text(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must pass the full CV text, not a truncated head."""
        # Create a CV where a sentinel word appears only after 3000 chars
        prefix = "A" * 3100
        sentinel = "SENTINEL_DEEP_CV_WORD"
        long_cv_text = prefix + " " + sentinel
        cv_file = tmp_path / "cv_long.md"
        cv_file.write_text(long_cv_text)
        meta = CVVariantMetadata(
            variant_id="cv_long",
            file_path=cv_file,
            role_families=["software"],
            skills=["Python"],
        )
        knowledge = InternalKnowledge(
            master_profile={"name": "Test"},
            cv_variants=[meta],
            personal_skills="some skills",
        )
        selected_cv = SelectedCV(
            variant_id="cv_long",
            metadata=meta,
            full_text=long_cv_text,
        )
        reqs = RequirementExtraction(core_requirement="Python expertise")
        state = minimal_state.model_copy(
            update={"knowledge": knowledge, "selected_cv": selected_cv, "requirements": reqs}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert sentinel in combined, "Full CV text must be present (not truncated at 3000 chars)"

    def test_passes_full_skills_text(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must pass full personal_skills text, not a truncated head."""
        prefix = "B" * 1600
        sentinel = "SENTINEL_DEEP_SKILLS_WORD"
        long_skills = prefix + " " + sentinel
        cv_file = tmp_path / "cv_software.md"
        cv_file.write_text("# CV")
        meta = CVVariantMetadata(
            variant_id="cv_software", file_path=cv_file, role_families=["software"]
        )
        knowledge = InternalKnowledge(
            master_profile={"name": "Test"},
            cv_variants=[meta],
            personal_skills=long_skills,
        )
        selected_cv = SelectedCV(variant_id="cv_software", metadata=meta, full_text="# CV")
        reqs = RequirementExtraction(core_requirement="Python expertise")
        state = minimal_state.model_copy(
            update={"knowledge": knowledge, "selected_cv": selected_cv, "requirements": reqs}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert sentinel in combined, "Full skills text must be present (not truncated at 1500 chars)"

    def test_passes_full_project_docs(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must pass full project doc text, not a 500-char head."""
        prefix = "C" * 600
        sentinel = "SENTINEL_DEEP_PROJECT_WORD"
        long_project = prefix + " " + sentinel
        cv_file = tmp_path / "cv_software.md"
        cv_file.write_text("# CV")
        meta = CVVariantMetadata(
            variant_id="cv_software", file_path=cv_file, role_families=["software"]
        )
        knowledge = InternalKnowledge(
            master_profile={"name": "Test"},
            cv_variants=[meta],
            personal_skills="skills",
            project_docs={"project_alpha.md": long_project},
        )
        selected_cv = SelectedCV(variant_id="cv_software", metadata=meta, full_text="# CV")
        reqs = RequirementExtraction(core_requirement="Python expertise")
        state = minimal_state.model_copy(
            update={"knowledge": knowledge, "selected_cv": selected_cv, "requirements": reqs}
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert sentinel in combined, "Full project doc text must be present (not truncated at 500 chars)"

    def test_prompt_requests_verbatim_passage(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """build_prompt must instruct the LLM to extract verbatim passages."""
        state = _make_full_state(minimal_state, tmp_path)
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages).lower()
        assert "verbatim" in combined or "quote" in combined, (
            "Prompt must contain 'verbatim' or 'quote' to instruct passage extraction"
        )


class TestParseResponse:
    def test_empty_passage_goes_to_known_gaps(self, tmp_path: Path) -> None:
        """An EvidenceItem with an empty passage must be dropped and its claim added to known_gaps."""
        data = {
            "items": [
                {
                    "claim": "Has cloud experience",
                    "source_type": "cv_variant",
                    "source_file": "cvs/cv_software.md",
                    "passage": "",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        }
        result = parse_response(data, profile_dir=str(tmp_path))
        assert result.items == [], "Item with empty passage must be dropped"
        assert "Has cloud experience" in result.known_gaps

    def test_whitespace_passage_goes_to_known_gaps(self, tmp_path: Path) -> None:
        """An EvidenceItem with whitespace-only passage must be treated as empty."""
        data = {
            "items": [
                {
                    "claim": "Kubernetes experience",
                    "source_type": "cv_variant",
                    "source_file": "cvs/cv_software.md",
                    "passage": "   ",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        }
        result = parse_response(data, profile_dir=str(tmp_path))
        assert result.items == []
        assert "Kubernetes experience" in result.known_gaps

    def test_valid_passage_with_relevance_note_accepted(self, tmp_path: Path) -> None:
        """An item with a non-empty passage and relevance_note must be accepted fully."""
        data = {
            "items": [
                {
                    "claim": "Led microservices migration",
                    "source_type": "cv_variant",
                    "source_file": "cvs/cv_software.md",
                    "passage": "Led migration of monolith to microservices on Kubernetes.",
                    "relevance_note": "Directly evidences large-scale architecture experience.",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        }
        result = parse_response(data, profile_dir=str(tmp_path))
        assert len(result.items) == 1
        assert result.items[0].passage == "Led migration of monolith to microservices on Kubernetes."
        assert result.items[0].relevance_note == "Directly evidences large-scale architecture experience."

    def test_valid_response_parses(self, tmp_path: Path) -> None:
        data = {
            "items": [
                {
                    "claim": "Python expert",
                    "source_type": "cv_variant",
                    "source_file": "cvs/cv_software.md",
                    "passage": "Python expert with Spark experience.",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        }
        profile_dir = str(tmp_path)
        result = parse_response(data, profile_dir=profile_dir)
        assert isinstance(result, EvidenceMap)
        assert len(result.items) == 1

    def test_raises_on_unapproved_source(self, tmp_path: Path) -> None:
        """source_file outside approved dirs → ValueError."""
        data = {
            "items": [
                {
                    "claim": "Python expert",
                    "source_type": "external",
                    "source_file": "/etc/passwd",
                    "passage": "root:x:0:0",
                }
            ],
            "known_gaps": [],
            "assumptions": [],
        }
        with pytest.raises(ValueError, match="approved"):
            parse_response(data, profile_dir=str(tmp_path))

    def test_known_gaps_captured(self, tmp_path: Path) -> None:
        data = {
            "items": [],
            "known_gaps": ["Kubernetes experience not found in profile"],
            "assumptions": [],
        }
        result = parse_response(data, profile_dir=str(tmp_path))
        assert len(result.known_gaps) == 1
        assert "Kubernetes" in result.known_gaps[0]
