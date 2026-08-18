"""Deterministic extractors for story_polish post-check — feature 013 US2.

The post-check is the load-bearing factual-integrity contract for the polish
stage: tool names, employer names, and numeric tokens in the polished version
MUST be a subset of those in the draft. Any addition fails the check and
the pipeline falls back to the unpolished draft.

These extractors are intentionally simple and exhaustively tested (see
tests/unit/test_extractors.py). The constitution makes factual integrity
non-negotiable; an LLM-based judge would defeat the safety net's purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# Built-in tool-name registry. Operators can override per-template via
# NarrativePolishConfig.tool_registry. Kept short and casing-canonical;
# matches are case-insensitive whole-word.
TOOL_REGISTRY_DEFAULT: frozenset[str] = frozenset({
    "Python", "Kafka", "Spark", "Airflow", "Beam", "Snowflake", "dbt",
    "Terraform", "Kubernetes", "K8s", "EKS", "S3", "MSK", "RDS", "AWS",
    "GCP", "Azure", "Argo", "Docker", "PostgreSQL", "Postgres", "Redis",
    "PyTorch", "TensorFlow", "JAX", "Ray", "MLflow", "FastAPI", "Django",
    "React", "TypeScript", "JavaScript", "Node", "Go", "Rust", "Java",
    "Scala", "SQL", "GraphQL", "REST", "gRPC",
})

EMPLOYER_CONTEXT_PREFIXES: tuple[str, ...] = (
    "at ", "bei ", "with ", "für ", "for ", " @ ",
)


def tool_names_in_text(text: str, registry: Iterable[str]) -> set[str]:
    """Case-insensitive whole-word matches against the registry.

    Returns a set of registry-cased names found in the text. Whole-word
    means the match is not adjacent to alphanumeric characters on either
    side. Hyphens count as non-word, so "AWS-managed" matches "AWS" but
    "AWSome" does not.
    """
    found: set[str] = set()
    if not text:
        return found
    lowered = text.lower()
    for tool in registry:
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(tool.lower()) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, lowered):
            found.add(tool)
    return found


# Capitalised multi-word phrase after one of EMPLOYER_CONTEXT_PREFIXES.
# Each subsequent capitalised word may include & for company-name joins
# ("Procter & Gamble"). Limited to 4 words to avoid runaway matches.
_EMPLOYER_RE_TEMPLATE = (
    r"({prefix})([A-Z][A-Za-z0-9&]*(?:\s+[A-Z][A-Za-z0-9&]*){{0,3}})"
)


def employer_names_in_text(text: str) -> set[str]:
    """Capitalised multi-word phrases following at/bei/with/für/for/@.

    Heuristic — accepts noise. The polish post-check only fires on
    *additions*, so any noise present in BOTH draft and polished cancels
    out (the comparison is set-based).
    """
    found: set[str] = set()
    if not text:
        return found
    for prefix in EMPLOYER_CONTEXT_PREFIXES:
        pattern = _EMPLOYER_RE_TEMPLATE.format(prefix=re.escape(prefix))
        for m in re.finditer(pattern, text):
            name = m.group(2).strip()
            if name:
                found.add(name)
    return found


# Digit sequences with optional decimal point. Surrounding ~, +, %, commas
# normalised away (so "1000", "1,000", "~1000", "1000+", "1000%" all map
# to "1000"). Decimals preserved: "1.5" stays "1.5".
_NUMERIC_RE = re.compile(r"[~+]*(\d[\d,]*(?:\.\d+)?)[%+]*")


def numeric_tokens_in_text(text: str) -> set[str]:
    """Extract normalised numeric tokens (commas stripped, ~/+/% removed)."""
    found: set[str] = set()
    if not text:
        return found
    for m in _NUMERIC_RE.finditer(text):
        normalised = m.group(1).replace(",", "")
        if normalised:
            found.add(normalised)
    return found


@dataclass(frozen=True)
class StoryPolishPostCheck:
    """Result of comparing a polished letter against its draft.

    `passed` is True iff polished contains no additions in any of the three
    extracted categories. `added_*` lists are sorted for stable error
    messages.
    """

    passed: bool
    added_tools: list[str] = field(default_factory=list)
    added_employers: list[str] = field(default_factory=list)
    added_numerics: list[str] = field(default_factory=list)


def post_check(
    draft: str, polished: str, registry: Iterable[str] | None = None
) -> StoryPolishPostCheck:
    """Compare polished vs. draft on tools, employers, numeric tokens.

    Returns a StoryPolishPostCheck with `passed=True` iff polished is a
    subset of draft on all three categories.
    """
    reg = registry if registry is not None else TOOL_REGISTRY_DEFAULT
    added_tools = sorted(
        tool_names_in_text(polished, reg) - tool_names_in_text(draft, reg)
    )
    added_emp = sorted(
        employer_names_in_text(polished) - employer_names_in_text(draft)
    )
    added_num = sorted(
        numeric_tokens_in_text(polished) - numeric_tokens_in_text(draft)
    )
    return StoryPolishPostCheck(
        passed=not (added_tools or added_emp or added_num),
        added_tools=added_tools,
        added_employers=added_emp,
        added_numerics=added_num,
    )
