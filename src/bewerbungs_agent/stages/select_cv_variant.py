"""Stage: select_cv_variant — choose the best CV variant for the role."""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.io.loader import load_cv_variant_text
from bewerbungs_agent.models.state import SelectedCV, WorkflowState
from bewerbungs_agent.utils.llm_client import get_llm_client

_SELECT_SCHEMA: dict[str, Any] = {
    "title": "select_cv_variant",
    "type": "object",
    "properties": {
        "variant_id": {
            "type": "string",
            "description": "The variant_id of the best matching CV variant.",
        },
        "selection_reason": {
            "type": "string",
            "description": "Brief explanation of why this variant was chosen.",
        },
    },
    "required": ["variant_id", "selection_reason"],
}


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for CV variant selection.

    Only uses state.knowledge.cv_variants and state.requirements.
    """
    variants = state.knowledge.cv_variants if state.knowledge else []
    variants_summary = "\n".join(
        f"- ID: {v.variant_id} | Families: {v.role_families} | "
        f"Skills: {v.skills[:6]} | Summary: {v.summary}"
        for v in variants
    )

    req_lines = ""
    if state.requirements:
        r = state.requirements
        req_lines = (
            f"Core requirement: {r.core_requirement}\n"
            f"Technical requirements: {r.technical_requirements}\n"
            f"Domain requirement: {r.domain_requirement or 'n/a'}\n"
            f"Collaboration requirement: {r.collaboration_requirement or 'n/a'}"
        )

    content = (
        "Select the single best CV variant for this job application.\n\n"
        f"Job requirements:\n{req_lines}\n\n"
        f"Available CV variants:\n{variants_summary}\n\n"
        "Return the variant_id and a brief selection_reason."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any]) -> dict[str, str]:
    """Validate LLM response — returns {variant_id, selection_reason}."""
    if "variant_id" not in data:
        raise ValueError("LLM response missing 'variant_id'")
    return {"variant_id": str(data["variant_id"]), "selection_reason": str(data.get("selection_reason", ""))}


def select_cv_variant(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: select the best CV variant for the role.

    If config.cv_variant_override is set, skip the LLM and use that variant.

    Returns:
        Partial state update: ``{"selected_cv": SelectedCV}``.

    Raises:
        ValueError: If no CV variants are available or override is unknown.
    """
    knowledge = state.knowledge
    if not knowledge or not knowledge.cv_variants:
        raise ValueError("No CV variants available in internal knowledge.")

    override = state.config.cv_variant_override

    if override:
        matching = [v for v in knowledge.cv_variants if v.variant_id == override]
        if not matching:
            available = [v.variant_id for v in knowledge.cv_variants]
            raise ValueError(
                f"CV variant override '{override}' not found. "
                f"Available: {available}"
            )
        metadata = matching[0]
        selection_reason = "manual override"
    else:
        client = get_llm_client()
        messages = build_prompt(state)
        raw = client.call(messages, _SELECT_SCHEMA)
        parsed = parse_response(raw)

        matching = [v for v in knowledge.cv_variants if v.variant_id == parsed["variant_id"]]
        if not matching:
            raise ValueError(
                f"LLM selected unknown variant: '{parsed['variant_id']}'. "
                f"Available: {[v.variant_id for v in knowledge.cv_variants]}"
            )
        metadata = matching[0]
        selection_reason = parsed["selection_reason"]

    full_text = load_cv_variant_text(metadata)
    return {
        "selected_cv": SelectedCV(
            variant_id=metadata.variant_id,
            metadata=metadata,
            full_text=full_text,
            selection_reason=selection_reason,
        )
    }
