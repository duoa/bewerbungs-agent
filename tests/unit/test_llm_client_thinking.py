"""Unit tests for AnthropicLLMClient extended thinking parameter support."""

from __future__ import annotations

from unittest.mock import MagicMock  # noqa: E402

import anthropic

from bewerbungs_agent.config.models import ThinkingConfig, ThinkingEffort
from bewerbungs_agent.utils.llm_client import AnthropicLLMClient


def _make_mock_client() -> tuple[AnthropicLLMClient, MagicMock]:
    """Return a client wired to a mock Anthropic _client with a captured create mock."""

    client = AnthropicLLMClient.__new__(AnthropicLLMClient)

    # Build a real-spec mock response with a ToolUseBlock
    mock_block = MagicMock(spec=anthropic.types.ToolUseBlock)
    mock_block.input = {"result": "ok"}
    mock_response = MagicMock()
    mock_response.content = [mock_block]

    mock_create = MagicMock(return_value=mock_response)
    mock_inner = MagicMock()
    mock_inner.messages.create = mock_create
    client._client = mock_inner  # type: ignore[attr-defined]

    return client, mock_create


class TestAnthropicLLMClientThinking:
    _SCHEMA = {"title": "t", "type": "object", "properties": {}, "required": []}
    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_call_includes_thinking_when_enabled(self) -> None:
        """When thinking is enabled, API call receives thinking dict with budget_tokens."""
        client, mock_create = _make_mock_client()
        client.call(
            self._MESSAGES,
            self._SCHEMA,
            thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.medium),
        )

        kwargs = mock_create.call_args.kwargs
        assert "thinking" in kwargs
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 8000}
        assert kwargs["max_tokens"] >= 9024

    def test_call_no_thinking_when_disabled(self) -> None:
        """When thinking is disabled, API call does not include a thinking key."""
        client, mock_create = _make_mock_client()
        client.call(
            self._MESSAGES,
            self._SCHEMA,
            thinking=ThinkingConfig(enabled=False),
        )

        kwargs = mock_create.call_args.kwargs
        assert "thinking" not in kwargs

    def test_call_no_thinking_when_none(self) -> None:
        """When thinking param is omitted (None), API call has no thinking key."""
        client, mock_create = _make_mock_client()
        client.call(self._MESSAGES, self._SCHEMA)

        kwargs = mock_create.call_args.kwargs
        assert "thinking" not in kwargs

    def test_call_low_effort_maps_to_1024_budget(self) -> None:
        """Low effort level maps to 1024 budget_tokens."""
        client, mock_create = _make_mock_client()
        client.call(
            self._MESSAGES,
            self._SCHEMA,
            thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.low),
        )
        kwargs = mock_create.call_args.kwargs
        assert kwargs["thinking"]["budget_tokens"] == 1024

    def test_call_high_effort_maps_to_16000_budget(self) -> None:
        """High effort level maps to 16000 budget_tokens."""
        client, mock_create = _make_mock_client()
        client.call(
            self._MESSAGES,
            self._SCHEMA,
            thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.high),
        )
        kwargs = mock_create.call_args.kwargs
        assert kwargs["thinking"]["budget_tokens"] == 16000
        assert kwargs["max_tokens"] >= 17024
