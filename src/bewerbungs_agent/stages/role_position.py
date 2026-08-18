"""Stage: role_position — produce a RolePositioning before content planning.

Feature 013: extracted out of plan_content so the narrative_strategy stage
can run between role positioning and content planning. The prompt and
RolePositioning schema are unchanged from feature 010.
"""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.models.state import RolePositioning, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the message list for the role-position LLM call.

    Uses state.job_context, state.requirements, state.evidence_map, state.config.
    Does NOT include raw InternalKnowledge — preserves the writer-isolation
    invariant established for downstream stages.
    """
    job_context = state.job_context
    requirements = state.requirements
    evidence_map = state.evidence_map
    config = state.config

    raw_job_text = (job_context.raw_job_text if job_context else "") or "(unavailable)"

    req_text = ""
    if requirements:
        req_text = (
            f"Core: {requirements.core_requirement}\n"
            f"Technical: {requirements.technical_requirements}\n"
            f"Domain: {requirements.domain_requirement or 'n/a'}\n"
            f"Collaboration: {requirements.collaboration_requirement or 'n/a'}"
        )

    weighted_block = ""
    if requirements and requirements.requirement_items:
        from bewerbungs_agent.models.state import Priority as _Priority

        order = {_Priority.high: 0, _Priority.medium: 1, _Priority.low: 2}
        sorted_items = sorted(
            requirements.requirement_items,
            key=lambda it: (order[it.priority], it.id),
        )
        item_lines: list[str] = []
        for it in sorted_items:
            line = (
                f"- [{it.id}, priority={it.priority.value}, "
                f"evidence={it.evidence_needed.value}, "
                f"category={it.category.value}] {it.text}"
            )
            if it.source_excerpt:
                line += f'\n  source: "{it.source_excerpt}"'
            item_lines.append(line)
        weighted_block = (
            "# Weighted Requirements (priority-ordered)\n"
            + "\n".join(item_lines)
            + "\n\n"
        )

    claims_list = ""
    if evidence_map:
        claim_entries = []
        for item in evidence_map.items:
            entry = f"- {item.claim} [source: {item.source_file}]"
            entry += f'\n  Passage: "{item.passage}"'
            if item.relevance_note:
                entry += f"\n  Note: {item.relevance_note}"
            claim_entries.append(entry)
        claims_list = "\n".join(claim_entries)

    instructions = load_prompt("role_positioner")

    content = (
        f"Decide the role positioning for the cover letter.\n\n"
        f"Config: language={config.language}, mode={config.mode.value}, "
        f"tone={config.tone}\n\n"
        f"# Job Description (verbatim)\n{raw_job_text}\n\n"
        f"{weighted_block}"
        f"# Extracted Requirements\n{req_text}\n\n"
        f"# Available Evidence Claims\n{claims_list}\n\n"
        f"# Instructions\n{instructions}\n"
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any]) -> RolePositioning:
    """Validate the LLM response into a RolePositioning."""
    return RolePositioning.model_validate(data)


def role_position(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: produce the RolePositioning."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)
    schema = RolePositioning.model_json_schema()
    schema["title"] = "role_position"
    stage_th = resolve_stage_thinking(state.config, "role_position")
    response = client.call(
        messages, schema, system=load_prompt("system"), thinking=stage_th
    )
    if state.tracker:
        state.tracker.log_stage(
            stage_name="role_position",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="role_positioner",
            prompt_hash=_compute_prompt_hash("role_positioner"),
        )

    rp = parse_response(response)
    return {"role_positioning": rp}
