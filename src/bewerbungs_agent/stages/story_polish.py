"""Stage: story_polish — polish letter prose without adding facts.

Feature 013 US2. Runs between write_letter and hiring_review. Reads
letter_draft, content_plan, narrative_strategy, role_positioning, config.
Deterministic post-check (utils.extractors.post_check) refuses any polished
output whose tool/employer/numeric set is not a subset of the draft's.
Three failure modes — LLM error, post-check failure, stage disabled —
all fall back to the unpolished draft.
"""

from __future__ import annotations

import warnings
from typing import Any

from bewerbungs_agent.models.state import StoryPolishOutput, WorkflowState
from bewerbungs_agent.utils.extractors import (
    TOOL_REGISTRY_DEFAULT,
    StoryPolishPostCheck,
    post_check,
)
from bewerbungs_agent.utils.prompts import load_prompt

_POLISH_SCHEMA: dict[str, Any] = {
    "title": "story_polish",
    "type": "object",
    "properties": {
        "polished_text": {
            "type": "string",
            "description": "The polished letter text. Must add no new facts.",
        },
    },
    "required": ["polished_text"],
}


def _resolve_tool_registry(state: WorkflowState) -> set[str]:
    """Pick the per-template tool registry override, else the built-in seed."""
    override = state.config.narrative_polish.tool_registry
    if override:
        return set(override)
    return set(TOOL_REGISTRY_DEFAULT)


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the message list for the story_polish LLM call."""
    draft = state.letter_draft
    ns = state.narrative_strategy
    rp = state.role_positioning
    config = state.config

    draft_text = draft.text if draft else ""

    ns_block = ""
    if ns is not None:
        ns_block = (
            "# Narrative Strategy (for tone reference only)\n"
            f"- bridge: {ns.bridge}\n"
            f"- opening_angle: {ns.opening_angle}\n"
            f"- tone_guidance: {ns.tone_guidance}\n"
            f"- anti_patterns: {list(ns.anti_patterns)}\n\n"
        )

    rp_block = ""
    if rp is not None:
        rp_block = (
            "# Role Positioning (for tone reference only)\n"
            f"- role_family: {rp.role_family}\n"
            f"- opening_angle: {rp.opening_angle}\n\n"
        )

    instructions = load_prompt("story_polisher")

    content = (
        f"Polish the cover letter for flow, transitions, sentence rhythm, "
        f"and naturalness — WITHOUT adding any new fact.\n\n"
        f"Configuration: language={config.language}, mode={config.mode.value}, "
        f"tone={config.tone}\n\n"
        f"{rp_block}"
        f"{ns_block}"
        f"# Draft Letter (the source of truth — only its text, reordered/rephrased, may appear in output)\n"
        f"```\n{draft_text}\n```\n\n"
        f"# Instructions\n{instructions}\n"
    )
    return [{"role": "user", "content": content}]


def _fallback(
    state: WorkflowState,
    reason: str,
    check: StoryPolishPostCheck | None = None,
) -> dict[str, Any]:
    """Build a fallback result: keep the draft, record the reason."""
    draft = state.letter_draft
    assert draft is not None
    output = StoryPolishOutput(
        polished_text=draft.text,
        post_check_passed=False,
        post_check_rationale=reason,
        used_fallback=True,
        fallback_reason=reason[:240],
        added_tools=list(check.added_tools) if check else [],
        added_employers=list(check.added_employers) if check else [],
        added_numerics=list(check.added_numerics) if check else [],
        diff_char_count=0,
    )
    return {"letter_draft": draft, "story_polish_output": output}


def story_polish(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: polish the letter draft (configurable, fallback-safe)."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    draft = state.letter_draft
    if draft is None:
        # No draft to polish — pass through unchanged.
        return {"letter_draft": None, "story_polish_output": None}

    # Disabled path
    if not state.config.narrative_polish.story_polish_enabled:
        return {"letter_draft": draft, "story_polish_output": None}

    # LLM call (wrapped in try/except — any failure falls back to draft)
    try:
        client = get_llm_client()
        messages = build_prompt(state)
        stage_th = resolve_stage_thinking(state.config, "story_polish")
        response = client.call(
            messages, _POLISH_SCHEMA, system=load_prompt("system"), thinking=stage_th
        )
        if state.tracker:
            state.tracker.log_stage(
                stage_name="story_polish",
                model=AnthropicLLMClient.MODEL,
                thinking=stage_th,
                prompt_name="story_polisher",
                prompt_hash=_compute_prompt_hash("story_polisher"),
            )
        polished_text = response["polished_text"]
    except Exception as exc:
        warnings.warn(
            f"story_polish LLM call failed ({type(exc).__name__}: {exc}); "
            f"falling back to unpolished draft",
            stacklevel=2,
        )
        return _fallback(state, reason=f"llm_failure: {exc!s}")

    # Post-check (the load-bearing factual-integrity contract)
    registry = _resolve_tool_registry(state)
    check = post_check(draft.text, polished_text, registry)
    if not check.passed:
        reason = (
            f"post_check_failed: tools={check.added_tools} "
            f"employers={check.added_employers} numerics={check.added_numerics}"
        )
        warnings.warn(
            f"story_polish post-check failed; falling back to draft. {reason}",
            stacklevel=2,
        )
        return _fallback(state, reason=reason, check=check)

    # Accept polished text — update letter_draft.text
    updated_draft = draft.model_copy(update={"text": polished_text})
    output = StoryPolishOutput(
        polished_text=polished_text,
        post_check_passed=True,
        post_check_rationale="all extracted sets are subsets of draft",
        used_fallback=False,
        fallback_reason=None,
        added_tools=[],
        added_employers=[],
        added_numerics=[],
        diff_char_count=abs(len(polished_text) - len(draft.text)),
    )
    return {"letter_draft": updated_draft, "story_polish_output": output}
