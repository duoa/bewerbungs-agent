"""Stage: tailor_cv — adapt the selected CV variant for the target role."""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.models.state import CVTailoringPlan, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt

_ALLOWED_ACTIONS = frozenset({"emphasise", "reorder", "include", "exclude"})

_TAILOR_SCHEMA: dict[str, Any] = {
    "title": "tailor_cv",
    "type": "object",
    "properties": {
        "base_variant_id": {
            "type": "string",
            "description": "The variant_id of the CV being tailored.",
        },
        "tailored_text": {
            "type": "string",
            "description": "The full tailored CV text in Markdown.",
        },
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["emphasise", "reorder", "include", "exclude"],
                    },
                    "rationale": {"type": "string"},
                    "evidence_ref": {"type": ["string", "null"]},
                },
                "required": ["section", "action", "rationale"],
            },
            "description": "List of targeted changes applied to produce tailored_text.",
        },
    },
    "required": ["base_variant_id", "tailored_text", "changes"],
}


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for CV tailoring.

    CRITICAL: Only selected_cv.full_text, requirements, and evidence_map items
    are passed to the LLM. Raw InternalKnowledge is never included.
    """
    selected_cv = state.selected_cv
    requirements = state.requirements
    evidence_map = state.evidence_map

    cv_text = selected_cv.full_text[:4000] if selected_cv else ""
    variant_id = selected_cv.variant_id if selected_cv else "unknown"

    req_text = ""
    if requirements:
        req_text = (
            f"Core: {requirements.core_requirement}\n"
            f"Technical: {requirements.technical_requirements}\n"
            f"Domain: {requirements.domain_requirement or 'n/a'}\n"
            f"Collaboration: {requirements.collaboration_requirement or 'n/a'}"
        )

    claims_list = ""
    if evidence_map:
        claims_list = "\n".join(
            f"- {item.claim} [source: {item.source_file}]"
            for item in evidence_map.items
        )

    instructions = load_prompt("tailor_cv")

    content = (
        f"Tailor the CV variant '{variant_id}' for the job requirements below.\n\n"
        f"# Job Requirements\n{req_text}\n\n"
        f"# Evidence Claims (use these to justify emphasis/ordering changes)\n"
        f"{claims_list}\n\n"
        f"# Base CV (variant: {variant_id})\n{cv_text}\n\n"
        f"# Instructions\n{instructions}\n\n"
        f"Return the full tailored CV text and list every change made with its action "
        f"(emphasise | reorder | include | exclude) and rationale."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any]) -> CVTailoringPlan:
    """Validate LLM response into a CVTailoringPlan.

    Raises:
        ValueError: If any change has an invalid action, or tailored_text is empty.
    """
    tailored_text = data.get("tailored_text", "")
    if not tailored_text or not tailored_text.strip():
        raise ValueError("tailored_text is empty — LLM returned no CV content.")

    changes = data.get("changes", [])
    for change in changes:
        action = change.get("action", "")
        if action not in _ALLOWED_ACTIONS:
            raise ValueError(
                f"Invalid CVTailoringChange action '{action}'. "
                f"Allowed: {sorted(_ALLOWED_ACTIONS)}"
            )

    return CVTailoringPlan.model_validate(data)


def tailor_cv(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: produce a tailored CV from the selected variant."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)
    stage_th = resolve_stage_thinking(state.config, "tailor_cv")
    response = client.call(messages, _TAILOR_SCHEMA, system=load_prompt("system"), thinking=stage_th)
    if state.tracker:
        state.tracker.log_stage(
            stage_name="tailor_cv",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="system",
            prompt_hash=_compute_prompt_hash("system"),
        )
    plan = parse_response(response)
    return {"cv_tailoring_plan": plan}
