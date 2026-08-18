"""Stage: targeted_rewrite — rewrite only sections flagged as weak by hiring_review.

Inputs:  letter_draft, letter_review (LetterReviewReport), requirements
Outputs: letter_draft (updated; overwrites write_letter output so validate_outputs is unchanged)

Non-blocking: any LLM failure returns {} and leaves letter_draft unchanged.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from bewerbungs_agent.config.models import resolve_stage_thinking
from bewerbungs_agent.models.state import LetterDraft, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt

if TYPE_CHECKING:
    from bewerbungs_agent.utils.llm_client import LLMClient

_MODEL = "claude-sonnet-4-6"

_REWRITE_SCHEMA: dict[str, Any] = {
    "title": "targeted_rewrite",
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": (
                "The complete cover letter text in Markdown. "
                "Weak sections are improved; strong sections are reproduced verbatim."
            ),
        },
    },
    "required": ["text"],
}


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the user message for the targeted_rewrite LLM call.

    Includes only letter text, structured review, and role requirements.
    Does NOT include InternalKnowledge, ContentPlan, or any profile documents.
    """
    letter_text = state.letter_draft.text if state.letter_draft else ""
    review = state.letter_review
    reqs = state.requirements

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

    # Format review — include only the sections flagged for rewriting
    sections_to_rewrite = review.sections_to_rewrite if review else []
    review_lines = [f"Sections to rewrite: {', '.join(sections_to_rewrite)}"]
    if review:
        for sec in review.sections:
            if sec.section_name in sections_to_rewrite:
                review_lines.append(f"\n### Section: {sec.section_name}")
                for w in sec.weaknesses:
                    review_lines.append(
                        f"  - Weakness ({w.severity.value}): {w.text}"
                        f"\n    Fix: {w.priority_fix}"
                    )

    content = (
        f"Rewrite only the flagged sections of the cover letter below.\n\n"
        f"## Role Requirements\n"
        + "\n".join(req_lines)
        + f"\n\n## Review Feedback\n"
        + "\n".join(review_lines)
        + f"\n\n## Original Cover Letter\n{letter_text}\n\n"
        f"Return the complete letter with flagged sections improved and all other sections unchanged."
    )
    return [{"role": "user", "content": content}]


def parse_response(data: dict[str, Any], original_draft: LetterDraft) -> LetterDraft:
    """Parse LLM tool-use response into a LetterDraft.

    Preserves mode and content_plan_hash from the original draft.
    """
    new_text = data.get("text", "")
    if not new_text or not new_text.strip():
        raise ValueError("targeted_rewrite: LLM returned empty text")

    return LetterDraft(
        text=new_text,
        char_count=len(new_text),
        mode=original_draft.mode,
        content_plan_hash=original_draft.content_plan_hash,
    )


def targeted_rewrite(
    state: WorkflowState,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """LangGraph node: rewrite only weak sections identified by hiring_review.

    The `client` parameter exists for dependency injection in tests.
    In production it defaults to the standard AnthropicLLMClient.
    """
    # No-op guards
    if state.letter_review is None:
        return {}
    if not state.letter_review.sections_to_rewrite:
        return {}
    if not state.letter_draft:
        return {}

    if client is None:
        from bewerbungs_agent.utils.llm_client import get_llm_client
        client = get_llm_client()

    messages = build_prompt(state)
    stage_th = resolve_stage_thinking(state.config, "targeted_rewrite")

    try:
        response = client.call(
            messages,
            _REWRITE_SCHEMA,
            system=load_prompt("targeted_rewriter"),
            thinking=stage_th,
        )
        new_draft = parse_response(response, state.letter_draft)
    except Exception as exc:
        warnings.warn(
            f"targeted_rewrite stage error (non-fatal): {exc}",
            stacklevel=2,
        )
        return {}

    if state.tracker:
        try:
            from bewerbungs_agent.utils.tracker import _compute_prompt_hash

            state.tracker.log_stage(
                stage_name="targeted_rewrite",
                model=_MODEL,
                thinking=stage_th,
                prompt_name="targeted_rewriter",
                prompt_hash=_compute_prompt_hash("targeted_rewriter"),
            )
        except Exception:
            pass

    return {"letter_draft": new_draft}
