"""Unit tests for stages.load_profile — TDD."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungs_agent.models.state import InternalKnowledge, WorkflowState
from bewerbungs_agent.stages.load_profile import load_profile


def _state_with_profile_dir(minimal_state: WorkflowState, profile_dir: Path) -> WorkflowState:
    config = minimal_state.config.model_copy(update={"profile_dir": profile_dir})
    return minimal_state.model_copy(update={"config": config})


def _make_minimal_profile(base: Path) -> None:
    """Write the minimum required profile files into *base*."""
    (base / "profile").mkdir(parents=True)
    (base / "profile" / "master_profile.json").write_text(
        json.dumps({"name": "Test User", "roles": [], "skills": []})
    )
    (base / "profile" / "personal_skills.md").write_text("# Skills\n\n- Reliability")
    (base / "cvs" / "metadata").mkdir(parents=True)
    (base / "cvs" / "cv_test.md").write_text("# Test CV\n\nSoftware engineer.")
    (base / "cvs" / "metadata" / "cv_test.json").write_text(
        json.dumps(
            {
                "variant_id": "cv_test",
                "file_path": "cv_test.md",
                "role_families": ["software-engineering"],
                "skills": ["Python"],
                "tools": [],
                "summary": "Test CV",
            }
        )
    )


class TestLoadProfile:
    def test_loads_all_required_files(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """Valid profile dir → InternalKnowledge with all required fields populated."""
        _make_minimal_profile(tmp_path)
        state = _state_with_profile_dir(minimal_state, tmp_path)
        result = load_profile(state)
        assert "knowledge" in result
        k = result["knowledge"]
        assert isinstance(k, InternalKnowledge)
        assert k.master_profile["name"] == "Test User"
        assert len(k.cv_variants) == 1
        assert k.personal_skills != ""

    def test_missing_master_profile_raises(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """Missing master_profile.json → FileNotFoundError."""
        _make_minimal_profile(tmp_path)
        (tmp_path / "profile" / "master_profile.json").unlink()
        state = _state_with_profile_dir(minimal_state, tmp_path)
        with pytest.raises(FileNotFoundError, match="master_profile"):
            load_profile(state)

    def test_missing_personal_skills_raises(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """Missing personal_skills.md → FileNotFoundError."""
        _make_minimal_profile(tmp_path)
        (tmp_path / "profile" / "personal_skills.md").unlink()
        state = _state_with_profile_dir(minimal_state, tmp_path)
        with pytest.raises(FileNotFoundError, match="personal_skills"):
            load_profile(state)

    def test_no_cv_variants_raises(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """No CV variant metadata files → FileNotFoundError."""
        _make_minimal_profile(tmp_path)
        for f in (tmp_path / "cvs" / "metadata").glob("*.json"):
            f.unlink()
        state = _state_with_profile_dir(minimal_state, tmp_path)
        with pytest.raises(FileNotFoundError, match="CV variant"):
            load_profile(state)

    def test_optional_projects_absent_returns_empty_dict(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """No projects/ directory → project_docs is empty dict."""
        _make_minimal_profile(tmp_path)
        state = _state_with_profile_dir(minimal_state, tmp_path)
        result = load_profile(state)
        assert result["knowledge"].project_docs == {}

    def test_optional_letters_absent_returns_empty_dict(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """No letters/ directory → previous_letters is empty dict."""
        _make_minimal_profile(tmp_path)
        state = _state_with_profile_dir(minimal_state, tmp_path)
        result = load_profile(state)
        assert result["knowledge"].previous_letters == {}

    def test_project_docs_loaded_when_present(
        self, minimal_state: WorkflowState, tmp_path: Path
    ) -> None:
        """Projects in profile/projects/ → loaded into project_docs."""
        _make_minimal_profile(tmp_path)
        projects = tmp_path / "profile" / "projects"
        projects.mkdir()
        (projects / "project_alpha.md").write_text("# Project Alpha\nDetails here.")
        state = _state_with_profile_dir(minimal_state, tmp_path)
        result = load_profile(state)
        assert "project_alpha.md" in result["knowledge"].project_docs
