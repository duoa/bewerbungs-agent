"""Stage: rewrite — targeted rewrite of failing letter sections."""

from __future__ import annotations

import hashlib
from typing import Any

from bewerbungs_agent.models.state import LetterDraft, WorkflowState
from bewerbungs_agent.utils.llm_client import get_llm_client
from bewerbungs_agent.utils.prompts import load_prompt

_REWRITE_SCHEMA: dict[str, Any] = {
    "title": "rewrite_letter",
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "The revised cover letter text in Markdown.",
        },
        "mode": {
            "type": "string",
            "enum": ["standard", "aida"],
            "description": "The writing mode used.",
        },
    },
    "required": ["text", "mode"],
}


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build message list for targeted rewrite.

    Includes only:
    - The current letter text
    - The specific validation violations and their details
    - The ContentPlan JSON (evidence-grounded facts to stay within)

    Does NOT include raw InternalKnowledge.
    """
    letter = state.letter_draft
    report = state.letter_validation
    plan = state.content_plan

    letter_text = letter.text if letter else ""
    plan_json = plan.model_dump_json(indent=2) if plan else "{}"

    violations_text = ""
    if report:
        violation_lines = []
        for result in report.results:
            if result.detail:
                violation_lines.append(f"- Rule '{result.rule}': {result.detail}")
            else:
                violation_lines.append(f"- Rule '{result.rule}': failed")
        violations_text = "\n".join(violation_lines)

    rewrite_count = state.rewrite_count

    content = (
        f"Rewrite the cover letter below to fix the following validation failures "
        f"(rewrite attempt {rewrite_count + 1}).\n\n"
        f"# Validation Failures\n{violations_text}\n\n"
        f"# Content Plan (stay within these facts only)\n```json\n{plan_json}\n```\n\n"
        f"# Current Letter\n{letter_text}\n\n"
        f"Fix only what is flagged above. Do not change passing sections. "
        f"Do not add facts not present in the Content Plan."
    )
    return [{"role": "user", "content": content}]


def rewrite_if_needed(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: rewrite the letter if validation failed and rewrites remain.

    Returns an empty dict if:
    - No letter draft exists, or
    - rewrite_count has reached max_rewrites (no further rewrites allowed).
    """
    if not state.letter_draft:
        return {}

    if state.rewrite_count >= state.max_rewrites:
        return {"rewrite_count": state.rewrite_count}

    client = get_llm_client()
    messages = build_prompt(state)
    response = client.call(messages, _REWRITE_SCHEMA, system=load_prompt("system"))

    new_text = response.get("text", "")
    if not new_text or not new_text.strip():
        return {"rewrite_count": state.rewrite_count + 1}

    # Rebuild LetterDraft with new text and updated hash
    plan = state.content_plan
    new_hash = (
        hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        if plan else ""
    )
    new_draft = LetterDraft(
        text=new_text,
        char_count=len(new_text),
        mode=state.letter_draft.mode,
        content_plan_hash=new_hash,
    )

    return {
        "letter_draft": new_draft,
        "rewrite_count": state.rewrite_count + 1,
    }


# Alias used by the graph builder
rewrite = rewrite_if_needed
