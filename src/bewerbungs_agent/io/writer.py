"""Output artifact writer: persists all pipeline state fields to disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bewerbungs_agent.models.state import WorkflowState


def _json_default(obj: Any) -> Any:
    """JSON serialiser for Pydantic models and Path objects."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=_json_default, ensure_ascii=False)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_artifacts(state: WorkflowState, output_dir: Path) -> None:
    """Persist all available intermediate artifacts to *output_dir*/artifacts/.

    Skips fields that are None (stage not yet executed).
    """
    artifacts = output_dir / "artifacts"

    if state.requirements is not None:
        _write_json(artifacts / "requirements.json", state.requirements.model_dump())

    if state.evidence_map is not None:
        _write_json(artifacts / "evidence_map.json", state.evidence_map.model_dump())
        # Known gaps as a convenience file
        _write_json(artifacts / "known_gaps.json", state.evidence_map.known_gaps)

    if state.content_plan is not None:
        _write_json(artifacts / "content_plan.json", state.content_plan.model_dump())

    if state.cv_tailoring_plan is not None:
        _write_json(
            artifacts / "cv_tailoring_plan.json",
            state.cv_tailoring_plan.model_dump(),
        )

    if state.letter_validation is not None:
        _write_json(
            artifacts / "validation_letter.json",
            state.letter_validation.model_dump(),
        )

    if state.cv_validation is not None:
        _write_json(
            artifacts / "validation_cv.json",
            state.cv_validation.model_dump(),
        )


def write_final_outputs(state: WorkflowState, output_dir: Path) -> None:
    """Write human-readable final outputs (letter.md, cv_tailored.md)."""
    if state.letter_draft is not None:
        _write_text(output_dir / "letter.md", state.letter_draft.text)

    if state.cv_tailoring_plan is not None and state.cv_tailoring_plan.tailored_text:
        _write_text(output_dir / "cv_tailored.md", state.cv_tailoring_plan.tailored_text)
