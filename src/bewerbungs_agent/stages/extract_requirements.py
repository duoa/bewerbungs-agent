"""Stage: extract_requirements — LLM stage extracting structured job requirements."""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.models.state import RequirementExtraction, WorkflowState
from bewerbungs_agent.utils.prompts import load_prompt


def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Build the message list for the requirement extraction LLM call.

    Only uses state.job_context. Does not access InternalKnowledge.
    """
    extraction_instructions = load_prompt("requirements")

    job_text = state.job_context.raw_job_text if state.job_context else ""
    company_text = (
        state.job_context.raw_company_text
        if state.job_context and state.job_context.raw_company_text
        else None
    )

    user_content = f"# Job Description\n\n{job_text}"
    if company_text:
        user_content += f"\n\n# Company Information\n\n{company_text}"
    user_content += f"\n\n---\n\nInstructions:\n{extraction_instructions}"

    return [{"role": "user", "content": user_content}]


def parse_response(data: dict[str, Any]) -> RequirementExtraction:
    """Validate and parse the LLM tool-use response into RequirementExtraction.

    Raises:
        ValueError: If core_requirement is empty.
    """
    core = data.get("core_requirement", "")
    if not core or not core.strip():
        raise ValueError(
            "core_requirement is empty — LLM must extract a core job requirement."
        )

    return RequirementExtraction.model_validate(data)


def extract_requirements(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: extract structured requirements from the job description."""
    from bewerbungs_agent.config.models import resolve_stage_thinking
    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient, get_llm_client
    from bewerbungs_agent.utils.tracker import _compute_prompt_hash

    client = get_llm_client()
    messages = build_prompt(state)
    schema = RequirementExtraction.model_json_schema()
    schema["title"] = "extract_requirements"
    stage_th = resolve_stage_thinking(state.config, "extract_requirements")
    response = client.call(messages, schema, system=load_prompt("system"), thinking=stage_th)
    if state.tracker:
        state.tracker.log_stage(
            stage_name="extract_requirements",
            model=AnthropicLLMClient.MODEL,
            thinking=stage_th,
            prompt_name="system",
            prompt_hash=_compute_prompt_hash("system"),
        )
    return {"requirements": parse_response(response)}
