"""Injectable LLM client: AnthropicLLMClient + factory function.

All stages call get_llm_client() to obtain a client. Tests substitute a mock
via dependency injection — no monkey-patching required.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

import anthropic

if TYPE_CHECKING:
    from bewerbungs_agent.config.models import ThinkingConfig

# Effort level → Anthropic budget_tokens mapping
_EFFORT_TO_BUDGET: dict[str, int] = {
    "low": 1024,
    "medium": 8000,
    "high": 16000,
}


class LLMClient(Protocol):
    """Protocol all LLM client implementations must satisfy."""

    def call(
        self,
        messages: list[dict[str, Any]],
        tool_schema: dict[str, Any],
        system: str = "",
        thinking: ThinkingConfig | None = None,
    ) -> dict[str, Any]:
        """Send *messages* to the LLM and return the tool-use response as a dict.

        Args:
            messages:    Anthropic-format message list.
            tool_schema: JSON Schema dict describing the expected structured output.
            system:      Optional system prompt text.
            thinking:    Optional per-call thinking configuration.

        Returns:
            Parsed tool-use input dict (the structured output from the model).
        """
        ...


class AnthropicLLMClient:
    """Production LLM client backed by the Anthropic Messages API."""

    MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def call(
        self,
        messages: list[dict[str, Any]],
        tool_schema: dict[str, Any],
        system: str = "",
        thinking: ThinkingConfig | None = None,
    ) -> dict[str, Any]:
        """Send messages and return structured tool-use output as a plain dict."""
        tool_name = tool_schema.get("title", "structured_output")
        tools = [
            {
                "name": tool_name,
                "description": tool_schema.get("description", "Return structured output"),
                "input_schema": tool_schema,
            }
        ]
        kwargs: dict[str, Any] = {
            "model": self.MODEL,
            "max_tokens": 4096,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": tool_name},
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        if thinking and thinking.enabled:
            budget = _EFFORT_TO_BUDGET[thinking.effort.value]
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["max_tokens"] = max(kwargs["max_tokens"], budget + 1024)

        response = self._client.messages.create(**kwargs)

        # Surface token usage to the active observability span (if any).
        # The LLM client depends only on the contextvar object, not on the
        # full Observability Protocol — coupling stays minimal.
        try:
            from bewerbungs_agent.utils.observability import TokenUsage, _active_span

            span = _active_span.get()
            usage = getattr(response, "usage", None)
            if span is not None and usage is not None:
                span.set_token_usage(
                    TokenUsage(
                        input_tokens=getattr(usage, "input_tokens", None),
                        output_tokens=getattr(usage, "output_tokens", None),
                        total_tokens=(
                            (getattr(usage, "input_tokens", 0) or 0)
                            + (getattr(usage, "output_tokens", 0) or 0)
                        ) or None,
                    )
                )
        except Exception:  # noqa: BLE001
            # Observability must never break the LLM call.
            pass

        for block in response.content:
            if isinstance(block, anthropic.types.ToolUseBlock):
                return dict(block.input)

        raise ValueError(f"LLM did not return a tool-use block. Response: {response}")


def get_llm_client(api_key: str | None = None) -> LLMClient:
    """Factory: return an AnthropicLLMClient using the env API key."""
    return AnthropicLLMClient(api_key=api_key)
