"""Stage: load_profile — load all approved internal knowledge sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bewerbungs_agent.io.loader import (
    load_cv_variant_metadata,
    load_json,
    load_markdown,
)
from bewerbungs_agent.models.state import InternalKnowledge, WorkflowState


def load_profile(state: WorkflowState) -> dict[str, Any]:
    """Load the full internal knowledge base from the profile directory.

    Required (raises FileNotFoundError if absent):
        - <profile_dir>/profile/master_profile.json
        - <profile_dir>/profile/personal_skills.md
        - <profile_dir>/cvs/metadata/*.json  (at least one)

    Optional (empty if absent):
        - <profile_dir>/profile/projects/*.md
        - <profile_dir>/letters/*.md

    Returns:
        Partial state update: ``{"knowledge": InternalKnowledge}``.
    """
    profile_dir = Path(str(state.config.profile_dir))

    # Required: master profile
    master_path = profile_dir / "profile" / "master_profile.json"
    if not master_path.exists():
        raise FileNotFoundError(
            f"master_profile.json not found: {master_path}"
        )
    master_profile = load_json(master_path)

    # Required: personal skills
    skills_path = profile_dir / "profile" / "personal_skills.md"
    if not skills_path.exists():
        raise FileNotFoundError(
            f"personal_skills.md not found: {skills_path}"
        )
    personal_skills = load_markdown(skills_path)

    # Required: at least one CV variant
    cv_metadata_dir = profile_dir / "cvs" / "metadata"
    cv_variants = []
    if cv_metadata_dir.exists():
        for meta_path in sorted(cv_metadata_dir.glob("*.json")):
            try:
                meta = load_cv_variant_metadata(meta_path)
                cv_variants.append(meta)
            except Exception as exc:
                raise ValueError(
                    f"Failed to load CV metadata {meta_path}: {exc}"
                ) from exc

    if not cv_variants:
        raise FileNotFoundError(
            f"No CV variant metadata files found in: {cv_metadata_dir}"
        )

    # Optional: project docs
    project_docs: dict[str, str] = {}
    projects_dir = profile_dir / "profile" / "projects"
    if projects_dir.exists():
        for p in sorted(projects_dir.glob("*.md")):
            project_docs[p.name] = load_markdown(p)

    # Optional: previous letters
    previous_letters: dict[str, str] = {}
    letters_dir = profile_dir / "letters"
    if letters_dir.exists():
        for p in sorted(letters_dir.glob("*.md")):
            previous_letters[p.name] = load_markdown(p)

    return {
        "knowledge": InternalKnowledge(
            master_profile=master_profile,
            cv_variants=cv_variants,
            personal_skills=personal_skills,
            project_docs=project_docs,
            previous_letters=previous_letters,
        )
    }
