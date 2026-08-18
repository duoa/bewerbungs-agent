"""Stage: plan_content — produce a structured content plan (no prose)."""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.models.state import ContentPlan, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for content planning.

    Only uses state.requirements, state.evidence_map, and state.config.
    Does NOT include raw InternalKnowledge — that is the key invariant.
    """
    requirements = state.requirements
    evidence_map = state.evidence_map
    config = state.config
    job_context = state.job_context

    # Feature 008: include the full original job description so the planner
    # can derive role positioning from the source text (not only from the
    # already-summarised extracted requirements).
    raw_job_text = (job_context.raw_job_text if job_context else "") or "(unavailable)"

    req_text = ""
    if requirements:
        req_text = (
            f"Core: {requirements.core_requirement}\n"
            f"Technical: {requirements.technical_requirements}\n"
            f"Domain: {requirements.domain_requirement or 'n/a'}\n"
            f"Collaboration: {requirements.collaboration_requirement or 'n/a'}"
        )

    # Feature 010: priority-ordered weighted requirement items, rendered as a
    # separate block ABOVE the legacy summary block so the planner sees the
    # weighting first. Omitted entirely when requirement_items is empty.
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
        if evidence_map.known_gaps:
            claims_list += "\n\nKnown gaps (no evidence):\n" + "\n".join(
                f"- {g}" for g in evidence_map.known_gaps
            )

    # Feature 013: narrative_strategy block (when populated). Empty string
    # otherwise — preserves legacy prompt structure for backward compat.
    narrative_block = ""
    ns = state.narrative_strategy
    if ns is not None:
        use_lines = "\n".join(f"  - {c}" for c in ns.proof_points_to_use) or "  (none)"
        avoid_lines = "\n".join(f"  - {c}" for c in ns.proof_points_to_avoid) or "  (none)"
        anti_lines = "\n".join(f"  - {p}" for p in ns.anti_patterns) or "  (none)"
        narrative_block = (
            "# Narrative Strategy\n"
            f"- candidate_story: {ns.candidate_story}\n"
            f"- role_story: {ns.role_story}\n"
            f"- bridge: {ns.bridge}\n"
            f"- opening_angle: {ns.opening_angle}\n"
            f"- proof_points_to_use:\n{use_lines}\n"
            f"- proof_points_to_avoid:\n{avoid_lines}\n"
            f"- transfer_framing_guidance: {ns.transfer_framing_guidance or '(none)'}\n"
            f"- tone_guidance: {ns.tone_guidance}\n"
            f"- anti_patterns:\n{anti_lines}\n\n"
        )

    instructions = load_prompt("planner")

    content = (
        f"Create a structured content plan for the cover letter.\n\n"
        f"Config: language={config.language}, mode={config.mode.value}, "
        f"tone={config.tone}, soft_skill_max={config.soft_skill_max}\n\n"
        f"# Job Description (verbatim)\n{raw_job_text}\n\n"
        f"{weighted_block}"
        f"{narrative_block}"
        f"# Extracted Requirements\n{req_text}\n\n"
        f"# Available Evidence Claims\n{claims_list}\n\n"
        f"# Why this company\n{chr(10).join(config.why_company) or 'n/a'}\n\n"
        f"# Instructions\n{instructions}\n\n"
        f"IMPORTANT: Only use claims listed above. Do not invent new facts. "
        f"Select at most {config.soft_skill_max} soft skills. "
        f"Do not write full sentences — key_claims should be short factual bullets. "
        f"For each section, copy the verbatim passage text from the evidence items "
        f"you reference into the `anchor_passages` list of that section. "
        f"role_positioning has been decided upstream (the role_position stage) "
        f"and will be attached to your output automatically. You MAY optionally "
        f"return a `role_positioning` object echoing the upstream values, but it "
        f"will be overwritten with the upstream values. Focus on letter_thesis, "
        f"paragraphs, sections, selected_soft_skills, and evidence_map. "
        f"Additionally produce `letter_thesis` (one sentence) and `paragraphs` "
        f"(ordered list, each with purpose / main_message / max_claims / "
        f"max_tools and the supporting fields). The opening paragraph MUST "
        f"reflect role_positioning.role_family and opening_angle. "
        f"For EACH paragraph, len(evidence_refs) MUST be ≤ max_claims — "
        f"if you have more candidate evidence than max_claims permits, pick "
        f"the strongest max_claims claims and drop the rest. "
        f"For EACH paragraph, main_message MUST be ≤ 400 characters (HARD "
        f"cap, schema-enforced). German compound nouns inflate length — "
        f"reword to be terse rather than exceed the cap."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any], soft_skill_max: int = 3) -> ContentPlan:
    """Validate LLM response into a ContentPlan.

    Raises:
        ValueError: If soft skills exceed soft_skill_max or a section claim is
            not present in the evidence map.
    """
    soft_skills = data.get("selected_soft_skills", [])
    if len(soft_skills) > soft_skill_max:
        raise ValueError(
            f"soft_skill_max is {soft_skill_max} but plan has {len(soft_skills)} "
            f"soft skills: {[s.get('name') for s in soft_skills]}"
        )

    # Collect all valid claim texts from the evidence_map embedded in the plan
    evidence_data = data.get("evidence_map", {})
    valid_claims = {item.get("claim", "") for item in evidence_data.get("items", [])}

    for section in data.get("sections", []):
        for claim in section.get("evidence_refs", []):
            # Strip trailing " [source: ...]" the LLM may copy from the prompt
            bare_claim = claim.split(" [source:")[0].strip()
            if valid_claims and bare_claim not in valid_claims:
                raise ValueError(
                    f"Section '{section.get('title')}' references claim "
                    f"'{bare_claim}' which is not in the evidence map."
                )

    return ContentPlan.model_validate(data)


def plan_content(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: produce a structured content plan before any prose."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)
    schema = ContentPlan.model_json_schema()
    schema["title"] = "plan_content"
    stage_th = resolve_stage_thinking(state.config, "plan_content")
    response = client.call(messages, schema, system=load_prompt("system"), thinking=stage_th)
    if state.tracker:
        state.tracker.log_stage(
            stage_name="plan_content",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="system",
            prompt_hash=_compute_prompt_hash("system"),
        )
    soft_skill_max = state.config.soft_skill_max
    plan = parse_response(response, soft_skill_max=soft_skill_max)

    # Feature 013: role_positioning is now decided by the upstream
    # role_position stage. If state.role_positioning is populated, override
    # whatever the planner returned (planner is instructed not to produce it).
    if state.role_positioning is not None:
        plan = plan.model_copy(update={"role_positioning": state.role_positioning})

    # Feature 013: filter paragraphs whose evidence_refs overlap with
    # narrative_strategy.proof_points_to_avoid. LLM is instructed not to
    # produce such paragraphs in the prompt; this deterministic backstop
    # mechanises the contract.
    if (
        state.narrative_strategy is not None
        and plan.paragraphs
        and state.narrative_strategy.proof_points_to_avoid
    ):
        avoid = set(state.narrative_strategy.proof_points_to_avoid)
        kept = []
        for i, p in enumerate(plan.paragraphs):
            overlap = avoid.intersection(p.evidence_refs)
            if overlap:
                if state.tracker:
                    try:
                        state.tracker.log_event(
                            "narrative_strategy.paragraph_dropped",
                            {
                                "index": i,
                                "purpose": p.purpose,
                                "overlap": sorted(overlap),
                            },
                        )
                    except Exception:
                        pass
                continue
            kept.append(p)
        if not kept and plan.paragraphs:
            raise ValueError(
                "narrative_strategy.proof_points_to_avoid vetoed every "
                "paragraph — the strategy is incompatible with the plan."
            )
        plan = plan.model_copy(update={"paragraphs": kept})

    # Feature 011: cross-validate paragraph requirement_ids against the
    # workflow's requirement_items (from feature 010). The model-level
    # validators can't reach RequirementExtraction; this stage-level check
    # closes the loop. Skipped when either side is empty (legacy paths).
    if plan.paragraphs and state.requirements is not None:
        valid_ids = {item.id for item in state.requirements.requirement_items}
        if valid_ids:
            for i, p in enumerate(plan.paragraphs):
                for rid in p.requirement_ids:
                    if rid not in valid_ids:
                        raise ValueError(
                            f"Paragraph {i} ({p.purpose!r}) references "
                            f"requirement_id {rid!r} which is not in the "
                            f"run's requirement_items."
                        )

    return {"content_plan": plan}
