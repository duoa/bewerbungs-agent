"""Stage: narrative_strategy — produce a NarrativeStrategy before content planning.

Feature 013. Runs between role_position and plan_content. Reads job_context,
requirements, evidence_map, role_positioning, config. Falls back to a
deterministic minimal strategy when disabled or on LLM failure.
"""

from __future__ import annotations

import warnings
from typing import Any

from bewerbungs_agent.config.models import WritingMode
from bewerbungs_agent.models.state import (
    EvidenceMap,
    NarrativeStrategy,
    WorkflowState,
)
from bewerbungs_agent.utils.prompts import load_prompt


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the message list for the narrative_strategy LLM call."""
    job_context = state.job_context
    requirements = state.requirements
    evidence_map = state.evidence_map
    rp = state.role_positioning
    config = state.config

    raw_job_text = (job_context.raw_job_text if job_context else "") or "(unavailable)"

    weighted_block = ""
    if requirements and requirements.requirement_items:
        from bewerbungs_agent.models.state import Priority as _Priority

        order = {_Priority.high: 0, _Priority.medium: 1, _Priority.low: 2}
        sorted_items = sorted(
            requirements.requirement_items,
            key=lambda it: (order[it.priority], it.id),
        )
        item_lines = []
        for it in sorted_items:
            line = (
                f"- [{it.id}, priority={it.priority.value}, "
                f"evidence={it.evidence_needed.value}] {it.text}"
            )
            item_lines.append(line)
        weighted_block = (
            "# Weighted Requirements (priority-ordered)\n"
            + "\n".join(item_lines)
            + "\n\n"
        )

    rp_block = "# Role Positioning (already decided upstream)\n(none — role_position stage did not run)\n"
    if rp is not None:
        rp_block = (
            "# Role Positioning (already decided upstream)\n"
            f"- role_family: {rp.role_family}\n"
            f"- primary_selling_point: {rp.primary_selling_point}\n"
            f"- secondary_selling_points: {list(rp.secondary_selling_points)}\n"
            f"- emphasise: {list(rp.emphasise)}\n"
            f"- deemphasise: {list(rp.deemphasise)}\n"
            f"- opening_angle: {rp.opening_angle}\n"
            f"- risky_or_gap_areas: {list(rp.risky_or_gap_areas)}\n"
        )

    claims_list = ""
    if evidence_map:
        claim_entries = []
        for item in evidence_map.items:
            entry = f"- {item.claim} [source: {item.source_file}]"
            entry += f'\n  Passage: "{item.passage}"'
            claim_entries.append(entry)
        claims_list = "\n".join(claim_entries)

    instructions = load_prompt("narrative_strategist")

    aida_reminder = ""
    if config.mode == WritingMode.aida and config.narrative_polish.restrained_aida:
        aida_reminder = (
            "\n\nIMPORTANT: Writing mode is AIDA and restrained_aida=True. "
            "tone_guidance MUST contain the literal phrase 'restrained AIDA' "
            "and explicitly constrain the writer to calm, senior, institutional "
            "voice with no marketing copy, no ALL-CAPS, no exclamation marks "
            "in the opening, no second-person imperatives, no hyperbolic "
            "adjectives."
        )

    content = (
        f"Produce a NarrativeStrategy for this cover letter.\n\n"
        f"Config: language={config.language}, mode={config.mode.value}, "
        f"tone={config.tone}\n\n"
        f"# Job Description (verbatim)\n{raw_job_text}\n\n"
        f"{weighted_block}"
        f"{rp_block}\n"
        f"# Available Evidence Claims\n{claims_list}\n\n"
        f"# Instructions\n{instructions}\n"
        f"\nIMPORTANT: Each entry in `proof_points_to_use` and `proof_points_to_avoid` "
        f"MUST appear verbatim in the evidence-claim list above (the bare claim text, "
        f"not the trailing `[source: ...]` part). A mismatch will crash the run."
        f"{aida_reminder}"
    )
    return [{"role": "user", "content": content}]


def parse_response(
    data: dict[str, Any], evidence_map: EvidenceMap | None
) -> NarrativeStrategy:
    """Validate the LLM response and cross-check proof_points against evidence_map."""
    ns = NarrativeStrategy.model_validate(data)
    if evidence_map is None:
        return ns
    valid_claims = {item.claim for item in evidence_map.items}
    if not valid_claims:
        return ns
    for i, c in enumerate(ns.proof_points_to_use):
        if c not in valid_claims:
            raise ValueError(
                f"proof_points_to_use[{i}] = {c!r} is not in evidence_map.items[*].claim"
            )
    for i, c in enumerate(ns.proof_points_to_avoid):
        if c not in valid_claims:
            raise ValueError(
                f"proof_points_to_avoid[{i}] = {c!r} is not in evidence_map.items[*].claim"
            )
    return ns


def _fallback_strategy(state: WorkflowState) -> NarrativeStrategy:
    """Deterministic minimal strategy when LLM disabled or failed.

    Derives from already-decided positioning + top-6 evidence claims so the
    downstream stages always have a NarrativeStrategy to consume.
    """
    rp = state.role_positioning
    evidence = state.evidence_map
    top_claims: list[str] = []
    if evidence is not None:
        top_claims = [item.claim for item in evidence.items[:6]]

    if rp is None:
        candidate_story = "Candidate brings the experience documented in the evidence map."
        role_story = "Role details inferred from the job description."
        bridge = "Direct alignment between background and role."
        opening_angle = "Lead with the strongest evidence claim."
        tone_guidance = "Calm, senior, credible, institutional voice."
    else:
        candidate_story = (
            f"Candidate's strongest positioning is in {rp.role_family}."
        )
        role_story = f"This role is in {rp.role_family}."
        bridge = (
            rp.primary_selling_point
            or "Direct alignment between background and role."
        )
        opening_angle = rp.opening_angle
        tone_guidance = "Calm, senior, credible, institutional voice."

    if (
        state.config.mode == WritingMode.aida
        and state.config.narrative_polish.restrained_aida
    ):
        tone_guidance += (
            " Restrained AIDA — narrative arc only, no marketing copy."
        )

    return NarrativeStrategy(
        candidate_story=candidate_story,
        role_story=role_story,
        bridge=bridge,
        opening_angle=opening_angle,
        proof_points_to_use=top_claims,
        proof_points_to_avoid=[],
        transfer_framing_guidance="",
        tone_guidance=tone_guidance,
        anti_patterns=[
            "Do not open with 'Although my background is...' — defensive framing",
            "Do not use marketing imperatives such as 'Imagine...' or 'PICTURE THIS:'",
        ],
    )


def narrative_strategy(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: produce the NarrativeStrategy."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    if not state.config.narrative_polish.narrative_strategy_enabled:
        ns = _fallback_strategy(state)
        return {"narrative_strategy": ns}

    try:
        client = get_llm_client()
        messages = build_prompt(state)
        schema = NarrativeStrategy.model_json_schema()
        schema["title"] = "narrative_strategy"
        stage_th = resolve_stage_thinking(state.config, "narrative_strategy")
        response = client.call(
            messages, schema, system=load_prompt("system"), thinking=stage_th
        )
        if state.tracker:
            state.tracker.log_stage(
                stage_name="narrative_strategy",
                model=AnthropicLLMClient.MODEL,
                thinking=stage_th,
                prompt_name="narrative_strategist",
                prompt_hash=_compute_prompt_hash("narrative_strategist"),
            )
        ns = parse_response(response, state.evidence_map)
    except Exception as exc:
        warnings.warn(
            f"narrative_strategy stage failed ({type(exc).__name__}: {exc}); "
            f"falling back to deterministic minimal strategy",
            stacklevel=2,
        )
        ns = _fallback_strategy(state)

    return {"narrative_strategy": ns}
