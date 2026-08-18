"""Stage: build_evidence_map — map factual claims to approved source passages."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

from bewerbungs_agent.models.state import EvidenceItem, EvidenceMap, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt

# Approved source path prefixes — any source_file must start with one of these
# (relative path from profile_dir root).
_APPROVED_PREFIXES = (
    "profile/",
    "cvs/",
    "letters/",
)


def _is_approved_source(source_file: str, profile_dir: str) -> bool:
    """Return True if *source_file* is within approved source directories."""
    p = Path(source_file)
    # Absolute paths outside profile_dir are never approved
    if p.is_absolute():
        try:
            p.relative_to(profile_dir)
            return True
        except ValueError:
            return False
    # Relative paths must start with an approved prefix
    return any(source_file.startswith(prefix) for prefix in _APPROVED_PREFIXES)


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for evidence mapping.

    Passes: requirements, selected CV text, personal skills, project doc
    summaries, and a summary of the master profile.
    Does NOT pass raw InternalKnowledge wholesale — only relevant excerpts.
    """
    knowledge = state.knowledge
    requirements = state.requirements
    selected_cv = state.selected_cv

    req_text = ""
    if requirements:
        req_text = (
            f"Core: {requirements.core_requirement}\n"
            f"Technical: {requirements.technical_requirements}\n"
            f"Domain: {requirements.domain_requirement or 'n/a'}\n"
            f"Collaboration: {requirements.collaboration_requirement or 'n/a'}\n"
            f"Must include: {requirements.must_include}\n"
            f"Must avoid: {requirements.must_avoid}"
        )

    cv_text = selected_cv.full_text if selected_cv else ""
    skills_text = knowledge.personal_skills if knowledge else ""
    profile_summary = json.dumps(
        knowledge.master_profile if knowledge else {}, ensure_ascii=False
    )
    projects_summary = ""
    if knowledge and knowledge.project_docs:
        projects_summary = "\n\n".join(
            f"## {name}\n{text}"
            for name, text in list(knowledge.project_docs.items())[:5]
        )

    content = (
        "Map the job requirements to factual evidence from the approved sources below.\n\n"
        f"# Job Requirements\n{req_text}\n\n"
        f"# Selected CV\n{cv_text}\n\n"
        f"# Master Profile\n{profile_summary}\n\n"
        f"# Personal Skills\n{skills_text}\n\n"
        f"# Project Documents\n{projects_summary}\n\n"
        "Instructions:\n"
        "1. For each requirement, identify the best matching text from the approved "
        "sources above and create an EvidenceItem.\n"
        "2. In the `passage` field, copy the most relevant excerpt from the source "
        "text. For PDF or structured sources where text may be reformatted, use the "
        "best available excerpt — do not require perfect verbatim alignment. Include "
        "enough context to make the claim credible (1–3 sentences or a bullet point).\n"
        "3. Use source paths: 'cvs/<filename>.pdf', 'cvs/<filename>.md', "
        "'profile/master_profile.json', 'profile/personal_skills.md', "
        "'profile/projects/<name>.md', or 'letters/<name>.md'.\n"
        "4. In `relevance_note`, write one sentence explaining why this excerpt "
        "supports the claim.\n"
        "5. Add a requirement to `known_gaps` ONLY if the skill or experience is "
        "completely absent from ALL provided sources (CV, profile, skills, projects). "
        "Do NOT add to known_gaps merely because you cannot find a perfectly phrased "
        "sentence — if the skill is present anywhere, create an evidence item for it.\n"
        "6. It is expected that most or all requirements will have matching evidence. "
        "An empty items list is almost certainly wrong — check all sources thoroughly."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any], profile_dir: str = "data") -> EvidenceMap:
    """Validate and parse the LLM response into an EvidenceMap.

    Raises:
        ValueError: If any EvidenceItem.source_file is outside approved directories.
    """
    items = []
    known_gaps: list[str] = list(data.get("known_gaps", []))
    for raw_item in data.get("items", []):
        source_file = raw_item.get("source_file", "")
        if not _is_approved_source(source_file, profile_dir):
            raise ValueError(
                f"EvidenceItem source_file '{source_file}' is outside approved "
                f"directories. Only paths under {_APPROVED_PREFIXES} are allowed."
            )
        item = EvidenceItem.model_validate(raw_item)
        if not item.passage.strip():
            known_gaps.append(item.claim)
        else:
            items.append(item)

    return EvidenceMap(
        items=items,
        known_gaps=known_gaps,
        assumptions=data.get("assumptions", []),
    )


def build_evidence_map(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: map job requirements to evidence from approved sources."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)

    # Flat schema avoids $ref/$defs which the Anthropic tool-use API may not resolve.
    schema: dict[str, Any] = {
        "title": "build_evidence_map",
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Evidence items — one per matched requirement.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "Short statement of the factual claim."},
                        "source_type": {"type": "string", "description": "e.g. 'cv', 'master_profile', 'personal_skills', 'project_doc'"},
                        "source_file": {"type": "string", "description": "Relative path: 'cvs/<file>', 'profile/master_profile.json', etc."},
                        "passage": {"type": "string", "description": "Best matching excerpt from the source document."},
                        "relevance_note": {"type": "string", "description": "One sentence: why this excerpt supports the claim."},
                    },
                    "required": ["claim", "source_type", "source_file", "passage"],
                },
            },
            "known_gaps": {
                "type": "array",
                "description": "Requirements completely absent from all sources.",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "description": "Any assumptions made during evidence mapping.",
                "items": {"type": "string"},
            },
        },
        "required": ["items", "known_gaps"],
    }
    stage_th = resolve_stage_thinking(state.config, "build_evidence_map")
    response = client.call(messages, schema, system=load_prompt("system"), thinking=stage_th)

    if state.tracker:
        state.tracker.log_stage(
            stage_name="build_evidence_map",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="system",
            prompt_hash=_compute_prompt_hash("system"),
        )
    profile_dir = str(state.config.profile_dir)
    evidence_map = parse_response(response, profile_dir=profile_dir)

    has_sources = bool(
        (state.selected_cv and state.selected_cv.full_text)
        or (state.knowledge and state.knowledge.master_profile)
        or (state.knowledge and state.knowledge.personal_skills)
    )
    if has_sources and not evidence_map.items and not evidence_map.known_gaps:
        warnings.warn(
            "build_evidence_map: LLM returned empty items and known_gaps despite "
            "having source documents. This usually means the model could not match "
            "the verbatim-quoting requirement. Check the prompt or source text quality.",
            stacklevel=2,
        )

    return {"evidence_map": evidence_map}
