"""Stage: hiring_review — evaluate the generated letter from a hiring manager's perspective.

Inputs:  letter_draft (text), requirements (structured extraction)
Outputs: letter_review (LetterReviewReport with sections_to_rewrite pre-computed)

Non-blocking: any LLM failure returns {} and leaves letter_draft unchanged.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from bewerbungs_agent.config.models import WeaknessSeverity, resolve_stage_thinking
from bewerbungs_agent.models.state import (
    CraftDimensions,
    DeterministicFinding,
    LetterReviewReport,
    SectionReview,
    WeaknessEntry,
    WorkflowState,
)
from bewerbungs_agent.utils.prompts import load_prompt

# Feature 013 US3 — six craft dimensions evaluated on every review.
_CRAFT_DIMENSIONS: tuple[str, ...] = (
    "story_coherence",
    "transition_smoothness",
    "over_constructed_language",
    "claim_relevance",
    "aida_restraint",
    "human_readability",
)

# Feature 013 US3 — German over-analogy phrase blocklist, scanned
# deterministically AFTER the LLM review returns.
OVER_ANALOGY_PHRASES_DE: tuple[str, ...] = (
    "direkt übertragbar",
    "direkt vergleichbar",
    "strukturell eng verwandt",
    "belastbares Analogon",
)

if TYPE_CHECKING:
    from bewerbungs_agent.utils.llm_client import LLMClient

_MODEL = "claude-sonnet-4-6"

# Severity ordering for threshold comparison
_SEVERITY_RANK: dict[str, int] = {
    WeaknessSeverity.low: 0,
    WeaknessSeverity.medium: 1,
    WeaknessSeverity.high: 2,
}

_REVIEW_SCHEMA: dict[str, Any] = {
    "title": "hiring_review",
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "description": "Per-section review entries covering each identified section of the letter.",
            "items": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "Descriptive name of this letter section (e.g. 'opening', 'motivation').",
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of strength observations for this section.",
                    },
                    "weaknesses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                },
                                "priority_fix": {"type": "string"},
                            },
                            "required": ["text", "severity", "priority_fix"],
                        },
                    },
                    "assessment": {
                        "type": "string",
                        "description": "One-sentence overall assessment of this section.",
                    },
                },
                "required": ["section_name", "strengths", "weaknesses", "assessment"],
            },
        },
        "overall_assessment": {
            "type": "string",
            "description": "One-sentence overall assessment of the full letter.",
        },
        # Feature 013 US3 — craft dimensions + verdict.
        "craft_dimensions": {
            "type": "object",
            "description": "Six craft-level dimensions evaluated on every review (feature 013).",
            "properties": {
                dim: {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["pass", "warn", "error"]},
                        "rationale": {"type": "string"},
                        "evidence_quote": {"type": ["string", "null"]},
                    },
                    "required": ["severity", "rationale"],
                }
                for dim in _CRAFT_DIMENSIONS
            },
            "required": list(_CRAFT_DIMENSIONS),
        },
        "verdict": {
            "type": "string",
            "enum": ["pass", "needs_minor_revision", "needs_major_revision"],
            "description": "Overall verdict before any automatic escalation by the pipeline.",
        },
    },
    "required": ["sections", "overall_assessment"],
}


# Always-on review dimensions the stage evaluates in addition to whatever
# standard dimensions the operator's review_config requests. The first five
# were introduced by feature 008 (positioning checks); feature 009 added
# `critical_requirements_underweighted` (a coverage check). Each is tagged
# in weakness text so downstream targeted_rewrite can route the fix.
_POSITIONING_DIMENSIONS: tuple[str, ...] = (
    "role_match",
    "opening_alignment",
    "secondary_topic_dominance",
    "tool_density",
    "overclaiming",
    "critical_requirements_underweighted",
)


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the user message for the hiring_review LLM call.

    Includes letter text, role requirements, the original verbatim job
    description (feature 008), and the active evaluation dimensions.
    Does NOT include InternalKnowledge, ContentPlan, or any profile documents.
    """
    letter_text = state.letter_draft.text if state.letter_draft else ""
    reqs = state.requirements
    review_cfg = state.config.review_config

    # Feature 008: include the verbatim job description so the LLM can judge
    # role match / opening alignment against the source text, not only the
    # extracted requirement summary.
    job_context = state.job_context
    raw_job_text = (job_context.raw_job_text if job_context else "") or (
        "(job description unavailable — base evaluation on requirements only)"
    )

    # Feature 009: parsed structured job-context fields. Build a block ONLY
    # when at least one structured field is populated. Each absent optional
    # field is silently omitted (FR-004 — no "(none)" placeholders).
    parsed_context_block = ""
    if job_context is not None:
        structured_lines: list[str] = []
        if job_context.job_title:
            structured_lines.append(f"- job_title: {job_context.job_title}")
        if job_context.company_name:
            structured_lines.append(f"- company_name: {job_context.company_name}")
        if job_context.raw_company_text:
            structured_lines.append(f"- company_info: {job_context.raw_company_text}")
        if job_context.raw_storyboard_text:
            structured_lines.append(f"- storyboard: {job_context.raw_storyboard_text}")
        if structured_lines:
            parsed_context_block = (
                "## Parsed Job Context\n" + "\n".join(structured_lines) + "\n\n"
            )

    # Format requirements
    req_lines = []
    if reqs:
        req_lines.append(f"Core requirement: {reqs.core_requirement}")
        for tr in reqs.technical_requirements:
            req_lines.append(f"Technical: {tr}")
        if reqs.collaboration_requirement:
            req_lines.append(f"Collaboration: {reqs.collaboration_requirement}")
        if reqs.domain_requirement:
            req_lines.append(f"Domain: {reqs.domain_requirement}")
        if reqs.optional_requirement:
            req_lines.append(f"Optional: {reqs.optional_requirement}")

    # Feature 009: content-plan summary block. Built only when state.content_plan
    # is populated. Shows section titles + first 3 key_claims per section, plus
    # role_positioning summary (when set) and known_gaps (when non-empty).
    # The reviewer reads this as READ-ONLY reference context — never evaluates
    # the plan itself.
    content_plan_block = ""
    plan = state.content_plan
    if plan is not None:
        plan_lines: list[str] = ["## Content Plan (read-only context — evaluate only the letter)"]

        # Sections
        plan_lines.append("\nSections:")
        for section in plan.sections:
            claims = section.key_claims[:3]
            plan_lines.append(f"- {section.title}: {claims}")

        # Role Positioning (omit sub-block entirely when None). Feature 010
        # renames the field labels and adds risky_or_gap_areas.
        rp = plan.role_positioning
        if rp is not None:
            plan_lines.append("\nRole Positioning:")
            plan_lines.append(f"- role_family: {rp.role_family}")
            plan_lines.append(f"- primary_selling_point: {rp.primary_selling_point}")
            if rp.secondary_selling_points:
                plan_lines.append(f"- secondary_selling_points: {list(rp.secondary_selling_points)}")
            plan_lines.append(f"- opening_angle: {rp.opening_angle}")
            if rp.emphasise:
                plan_lines.append(f"- emphasise: {list(rp.emphasise)}")
            if rp.deemphasise:
                plan_lines.append(f"- deemphasise: {list(rp.deemphasise)}")
            if rp.risky_or_gap_areas:
                plan_lines.append(f"- risky_or_gap_areas: {list(rp.risky_or_gap_areas)}")

        # Known gaps (only when non-empty)
        known_gaps = list(plan.evidence_map.known_gaps) if plan.evidence_map else []
        if known_gaps:
            plan_lines.append("\nKnown gaps acknowledged in the plan:")
            for gap in known_gaps:
                plan_lines.append(f"- {gap}")

        content_plan_block = "\n".join(plan_lines) + "\n\n"

    # Active dimensions = configured + the 5 positioning dimensions (always on)
    configured_dims = [d.value for d in review_cfg.dimensions]
    all_dims = configured_dims + [d for d in _POSITIONING_DIMENSIONS if d not in configured_dims]
    active_dims = ", ".join(all_dims)

    craft_block = (
        "## Craft Dimensions (feature 013 — return as `craft_dimensions` object)\n"
        + "\n".join(f"- {d}" for d in _CRAFT_DIMENSIONS)
        + "\n\nEach craft dimension MUST be returned with severity (pass/warn/error), "
        "rationale (≤ 240 chars), and evidence_quote (verbatim from the letter; "
        "REQUIRED when severity is warn or error).\n\n"
    )

    content = (
        f"Review the following cover letter from the perspective of a hiring manager.\n\n"
        f"## Original Job Description (verbatim)\n{raw_job_text}\n\n"
        f"{parsed_context_block}"
        f"## Role Requirements\n"
        + "\n".join(req_lines)
        + f"\n\n{content_plan_block}"
        + f"## Evaluation Dimensions (evaluate ONLY these)\n{active_dims}\n\n"
        + craft_block
        + f"## Cover Letter\n{letter_text}\n\n"
        f"Identify each section of the letter and assess it across the listed dimensions only. "
        f"For each weakness on a positioning dimension "
        f"({', '.join(_POSITIONING_DIMENSIONS)}), tag the weakness text with "
        f"the dimension name (e.g. 'role_match: ...'). "
        f"Additionally produce the craft_dimensions object and a top-level "
        f"verdict (pass / needs_minor_revision / needs_major_revision)."
    )
    return [{"role": "user", "content": content}]


def parse_response(
    data: dict[str, Any],
    threshold: WeaknessSeverity,
) -> LetterReviewReport:
    """Parse LLM tool-use response into a LetterReviewReport.

    Pre-computes sections_to_rewrite based on the configured severity threshold.
    """
    threshold_rank = _SEVERITY_RANK[threshold]

    sections: list[SectionReview] = []
    sections_to_rewrite: list[str] = []

    for raw_section in data.get("sections", []):
        weaknesses: list[WeaknessEntry] = []
        max_severity_rank = -1

        for raw_w in raw_section.get("weaknesses", []):
            severity_str = raw_w.get("severity", "low")
            try:
                severity = WeaknessSeverity(severity_str)
            except ValueError:
                severity = WeaknessSeverity.low
            weaknesses.append(
                WeaknessEntry(
                    text=raw_w.get("text", ""),
                    severity=severity,
                    priority_fix=raw_w.get("priority_fix", ""),
                )
            )
            max_severity_rank = max(max_severity_rank, _SEVERITY_RANK[severity])

        section = SectionReview(
            section_name=raw_section.get("section_name", ""),
            strengths=raw_section.get("strengths", []),
            weaknesses=weaknesses,
            assessment=raw_section.get("assessment", ""),
        )
        sections.append(section)

        if max_severity_rank >= threshold_rank:
            sections_to_rewrite.append(section.section_name)

    # Feature 013 US3 — craft_dimensions + verdict + escalation
    craft = None
    raw_craft = data.get("craft_dimensions")
    if raw_craft is not None:
        try:
            craft = CraftDimensions.model_validate(raw_craft)
        except Exception as exc:
            warnings.warn(
                f"hiring_review craft_dimensions parse error: {exc}",
                stacklevel=2,
            )
            craft = None

    raw_verdict = data.get("verdict", "pass")
    if raw_verdict not in ("pass", "needs_minor_revision", "needs_major_revision"):
        raw_verdict = "pass"

    # Escalation: aida_restraint or transition_smoothness severity >= warn
    # forces verdict to at least needs_minor_revision.
    if craft is not None and raw_verdict == "pass":
        if (
            craft.aida_restraint.severity in ("warn", "error")
            or craft.transition_smoothness.severity in ("warn", "error")
        ):
            raw_verdict = "needs_minor_revision"

    return LetterReviewReport(
        sections=sections,
        overall_assessment=data.get("overall_assessment", ""),
        sections_to_rewrite=sections_to_rewrite,
        craft_dimensions=craft,
        verdict=raw_verdict,
    )


def _scan_over_analogy_phrases(letter_text: str) -> list[DeterministicFinding]:
    """Feature 013 US3 — deterministic German over-analogy phrase scan.

    Returns one DeterministicFinding per substring match (case-insensitive).
    The hiring_review node attaches the result to the parsed report.
    """
    findings: list[DeterministicFinding] = []
    if not letter_text:
        return findings
    lowered = letter_text.lower()
    for phrase in OVER_ANALOGY_PHRASES_DE:
        plower = phrase.lower()
        start = 0
        while True:
            idx = lowered.find(plower, start)
            if idx == -1:
                break
            ctx_start = max(0, idx - 40)
            ctx_end = min(len(letter_text), idx + len(phrase) + 40)
            findings.append(
                DeterministicFinding(
                    check_id="over_analogy_phrase_de",
                    severity="warn",
                    phrase=phrase,
                    char_start=idx,
                    char_end=idx + len(phrase),
                    context_snippet=letter_text[ctx_start:ctx_end],
                )
            )
            start = idx + len(phrase)
    return findings


def hiring_review(
    state: WorkflowState,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """LangGraph node: evaluate the generated letter from a hiring manager's perspective.

    The `client` parameter exists for dependency injection in tests.
    In production it defaults to the standard AnthropicLLMClient.
    """
    review_cfg = state.config.review_config

    # No-op guards
    if not review_cfg.enabled:
        return {}
    if not state.letter_draft:
        return {}
    if not state.requirements:
        return {}

    if client is None:
        from bewerbungs_agent.utils.llm_client import get_llm_client
        client = get_llm_client()

    messages = build_prompt(state)
    stage_th = resolve_stage_thinking(state.config, "hiring_review")

    try:
        response = client.call(
            messages,
            _REVIEW_SCHEMA,
            system=load_prompt("hiring_reviewer"),
            thinking=stage_th,
        )
        report = parse_response(response, review_cfg.rewrite_threshold)
    except Exception as exc:
        warnings.warn(
            f"hiring_review stage error (non-fatal): {exc}",
            stacklevel=2,
        )
        return {}

    if state.tracker:
        try:
            from bewerbungs_agent.utils.tracker import _compute_prompt_hash

            state.tracker.log_stage(
                stage_name="hiring_review",
                model=_MODEL,
                thinking=stage_th,
                prompt_name="hiring_reviewer",
                prompt_hash=_compute_prompt_hash("hiring_reviewer"),
            )
        except Exception:
            pass

    # Feature 013 US3 — deterministic German over-analogy phrase scan.
    # Runs AFTER the LLM review; findings are attached to the report.
    deterministic = _scan_over_analogy_phrases(state.letter_draft.text)
    if deterministic:
        report = report.model_copy(update={"deterministic_findings": deterministic})

    return {"letter_review": report}
