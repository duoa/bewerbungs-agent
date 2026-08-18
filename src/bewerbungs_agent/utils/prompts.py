"""Prompt file loader: reads prompt Markdown files from the prompts/ directory."""

from __future__ import annotations

# Default location of the prompts/ directory, relative to the project root.
# Can be overridden via BEWERBUNGS_PROMPTS_DIR env var (set before import).
import os
from pathlib import Path

from bewerbungs_agent.config.models import WritingMode

_PROMPTS_DIR = Path(os.getenv("BEWERBUNGS_PROMPTS_DIR", "prompts"))


def _prompts_dir() -> Path:
    return _PROMPTS_DIR


def load_prompt(name: str) -> str:
    """Load a named prompt file from prompts/{name}.md.

    Args:
        name: Prompt name without extension, e.g. "system", "requirements".

    Returns:
        File contents as a string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = _prompts_dir() / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_style(mode: WritingMode) -> str:
    """Load the style prompt for the given writing mode.

    Args:
        mode: WritingMode enum value (standard or aida).

    Returns:
        File contents as a string.

    Raises:
        FileNotFoundError: If the style prompt file does not exist.
    """
    path = _prompts_dir() / "styles" / f"{mode.value}.md"
    if not path.exists():
        raise FileNotFoundError(f"Style prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
