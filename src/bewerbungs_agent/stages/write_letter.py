"""Stage: write_letter — generate cover letter prose from the content plan only."""

from __future__ import annotations

import hashlib
from typing import Any

from bewerbungs_agent.config.models import WritingMode
from bewerbungs_agent.models.state import LetterDraft, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt, load_style

_WRITE_SCHEMA: dict[str, Any] = {
    "title": "write_letter",
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "The complete cover letter text in Markdown.",
        },
        "mode": {
            "type": "string",
            "enum": ["standard", "aida"],
            "description": "The writing mode used.",
        },
    },
    "required": ["text", "mode"],
}


def _format_positioning_block(content_plan: Any) -> str:
    """Render the role_positioning sub-object as a human-readable block."""
    rp = getattr(content_plan, "role_positioning", None) if content_plan else None
    if rp is None:
        return "# Role Positioning\n(none — positioning was not recorded for this plan)\n"

    def _bullets(items: list[str]) -> str:
        return "\n".join(f"  - {x}" for x in items) if items else "  (none)"

    risky_block = ""
    if rp.risky_or_gap_areas:
        risky_block = f"- risky_or_gap_areas:\n{_bullets(list(rp.risky_or_gap_areas))}\n"
    return (
        "# Role Positioning\n"
        f"- role_family: {rp.role_family}\n"
        f"- primary_selling_point: {rp.primary_selling_point}\n"
        f"- secondary_selling_points:\n{_bullets(list(rp.secondary_selling_points))}\n"
        f"- emphasise:\n{_bullets(list(rp.emphasise))}\n"
        f"- deemphasise:\n{_bullets(list(rp.deemphasise))}\n"
        f"- opening_angle: {rp.opening_angle}\n"
        f"{risky_block}"
    )


def _format_paragraphs_block(content_plan: Any) -> str:
    """Render the per-paragraph plan when populated; empty string otherwise.

    Feature 011: surfaces letter_thesis and per-paragraph density limits
    (max_claims, max_tools) so the writer can respect them paragraph-by-paragraph.
    """
    if content_plan is None:
        return ""
    paragraphs = getattr(content_plan, "paragraphs", None) or []
    if not paragraphs:
        return ""

    lines: list[str] = []
    letter_thesis = getattr(content_plan, "letter_thesis", None)
    if letter_thesis:
        lines.append(f"Letter thesis: {letter_thesis}\n")
    lines.append("# Paragraph Plan")
    for i, p in enumerate(paragraphs, start=1):
        lines.append(f"\n## Paragraph {i}: {p.purpose}")
        lines.append(f"- main_message: {p.main_message}")
        if p.requirement_ids:
            lines.append(f"- requirement_ids: {list(p.requirement_ids)}")
        if p.evidence_refs:
            lines.append(f"- evidence_refs: {list(p.evidence_refs)}")
        if p.emphasise:
            lines.append(f"- emphasise: {list(p.emphasise)}")
        if p.deemphasise:
            lines.append(f"- deemphasise: {list(p.deemphasise)}")
        lines.append(f"- max_claims: {p.max_claims}")
        lines.append(f"- max_tools: {p.max_tools}")
    return "\n".join(lines) + "\n\n"


def _format_narrative_strategy_block(state: WorkflowState) -> str:
    """Render the narrative_strategy as a structured block in the writer prompt.

    Feature 013. Empty string when state.narrative_strategy is None (legacy
    compat — pipeline still works when the narrative_strategy stage didn't run).
    """
    ns = state.narrative_strategy
    if ns is None:
        return ""

    use = "\n".join(f"  - {c}" for c in ns.proof_points_to_use) or "  (none)"
    avoid = "\n".join(f"  - {c}" for c in ns.proof_points_to_avoid) or "  (none)"
    anti = "\n".join(f"  - {p}" for p in ns.anti_patterns) or "  (none)"
    return (
        "# Narrative Strategy\n"
        f"- candidate_story: {ns.candidate_story}\n"
        f"- role_story: {ns.role_story}\n"
        f"- bridge: {ns.bridge}\n"
        f"- opening_angle: {ns.opening_angle}\n"
        f"- transfer_framing_guidance: {ns.transfer_framing_guidance or '(none)'}\n"
        f"- tone_guidance: {ns.tone_guidance}\n"
        f"- proof_points_to_use:\n{use}\n"
        f"- proof_points_to_avoid:\n{avoid}\n"
        f"- anti_patterns:\n{anti}\n\n"
    )


def _format_writer_rules_block(writer_rules: Any) -> str:
    """Render the writer_rules config as a human-readable block."""
    banned = ", ".join(writer_rules.banned_phrases) if writer_rules.banned_phrases else "(none)"
    return (
        "# Writer Rules\n"
        f"- tool_density_max: {writer_rules.tool_density_max}\n"
        f"- banned_phrases: {banned}\n"
    )


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for cover letter generation.

    CRITICAL: Only the serialised ContentPlan is passed to the LLM.
    Raw InternalKnowledge is never included — this prevents the model from
    accessing the full knowledge base and inventing out-of-plan facts.

    Feature 008: the prompt additionally surfaces the role-positioning
    decision and the per-template writer rules (tool-density cap, banned
    self-rating phrases). The writer prompt file uses {tool_density_max}
    and {banned_phrases} placeholders that we resolve here.
    """
    content_plan = state.content_plan
    config = state.config
    writer_rules = config.writer_rules

    # Load the style instructions for the configured writing mode
    style_instructions = load_style(config.mode)

    # Resolve the {tool_density_max} and {banned_phrases} placeholders in writer.md
    writer_instructions_raw = load_prompt("writer")
    banned_phrases_text = "\n".join(f"- {p}" for p in writer_rules.banned_phrases)
    writer_instructions = writer_instructions_raw.format(
        tool_density_max=writer_rules.tool_density_max,
        banned_phrases=banned_phrases_text,
    )

    plan_json = content_plan.model_dump_json(indent=2) if content_plan else "{}"
    positioning_block = _format_positioning_block(content_plan)
    rules_block = _format_writer_rules_block(writer_rules)
    narrative_block = _format_narrative_strategy_block(state)
    paragraphs_block = _format_paragraphs_block(content_plan)

    content = (
        f"Write a cover letter from the structured content plan below.\n\n"
        f"Configuration: language={config.language}, tone={config.tone}, "
        f"mode={config.mode.value}\n\n"
        f"{positioning_block}\n"
        f"{rules_block}\n"
        f"{narrative_block}"
        f"{paragraphs_block}"
        f"# Writing Mode Instructions\n{style_instructions}\n\n"
        f"# Writer Instructions\n{writer_instructions}\n\n"
        f"# Content Plan (USE ONLY THESE FACTS)\n```json\n{plan_json}\n```\n\n"
        f"For each section, anchor your prose to the `anchor_passages` listed in "
        f"that section. Use their phrasing as a starting point; do not invent "
        f"wording not present in the plan.\n"
        f"Do not use any fact not present in the content plan above. "
        f"Write in {config.language}."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any]) -> LetterDraft:
    """Parse LLM tool-use response into a LetterDraft.

    Raises:
        ValueError: If the generated text is empty.
    """
    text = data.get("text", "")
    if not text or not text.strip():
        raise ValueError(
            "char_count is 0 — LLM returned empty letter text."
        )

    mode_str = data.get("mode", "standard")
    try:
        mode = WritingMode(mode_str)
    except ValueError:
        mode = WritingMode.standard

    char_count = len(text)
    return LetterDraft(
        text=text,
        char_count=char_count,
        mode=mode,
    )


def write_letter(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: generate cover letter from the content plan only."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)
    stage_th = resolve_stage_thinking(state.config, "write_letter")
    response = client.call(messages, _WRITE_SCHEMA, system=load_prompt("system"), thinking=stage_th)
    if state.tracker:
        state.tracker.log_stage(
            stage_name="write_letter",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="writer",
            prompt_hash=_compute_prompt_hash("writer"),
        )
    draft = parse_response(response)

    # Record content plan hash for auditability
    if state.content_plan:
        plan_hash = hashlib.sha256(
            state.content_plan.model_dump_json().encode()
        ).hexdigest()
        draft = draft.model_copy(update={"content_plan_hash": plan_hash})

    return {"letter_draft": draft}
