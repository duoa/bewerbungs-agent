"""Unified document loader for all approved source formats.

Supports: JSON, YAML, Markdown/plain text, PDF (via pypdf).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from bewerbungs_agent.config.models import StarterTemplate
from bewerbungs_agent.models.state import CVVariantMetadata


def load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def load_yaml(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


def load_markdown(path: Path) -> str:
    """Load a Markdown or plain-text file as a string."""
    return path.read_text(encoding="utf-8")


def load_pdf(path: Path) -> str:
    """Extract text from a PDF file using pypdf."""
    try:
        import pypdf
    except ImportError as exc:
        raise ImportError("pypdf is required to load PDF files: pip install pypdf") from exc

    reader = pypdf.PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def load_cv_variant_text(metadata: CVVariantMetadata) -> str:
    """Load the full text of a CV variant file (PDF or Markdown)."""
    path = metadata.file_path
    if not path.exists():
        raise FileNotFoundError(f"CV variant file not found: {path}")
    if path.suffix.lower() == ".pdf":
        return load_pdf(path)
    return load_markdown(path)


def load_cv_variant_metadata(metadata_path: Path) -> CVVariantMetadata:
    """Load and validate CV variant metadata from a JSON file."""
    data = load_json(metadata_path)
    # file_path is stored relative to the metadata dir's parent (data/cvs/)
    if "file_path" in data and not Path(data["file_path"]).is_absolute():
        data["file_path"] = metadata_path.parent.parent / data["file_path"]
    return CVVariantMetadata.model_validate(data)


def load_starter_template_yaml(path: Path) -> dict[str, Any]:
    """Load a starter template YAML file, injecting template_id from filename if absent."""
    data = load_yaml(path)
    if "template_id" not in data:
        data["template_id"] = path.stem
    return data


def load_starter_template(path: Path) -> StarterTemplate:
    """Load and fully validate a starter template YAML file.

    Raises:
        ValueError: If the YAML content fails StarterTemplate Pydantic validation,
            with the offending field names included in the message.
        FileNotFoundError: If *path* does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Starter template not found: {path}")

    data = load_starter_template_yaml(path)
    try:
        return StarterTemplate.model_validate(data)
    except Exception as exc:
        # Pydantic ValidationError carries field-level detail; wrap in ValueError
        # so callers get a consistent error type with the path context.
        raise ValueError(
            f"Invalid starter template '{path}': {exc}"
        ) from exc
