"""Unit tests for the Langfuse observability wrapper.

Covers User Story 1 (P1):
- Factory selection (NoOp vs Langfuse) based on env + config
- NoOpObservability zero-cost behaviour
- _wrap_stage invariants: doesn't mutate state, returns identical dict,
  opens/closes span, captures exceptions on span and re-raises
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LangfuseConfig,
    LengthMode,
    MergedConfig,
    ObservabilityConfig,
    WritingMode,
)
from bewerbungs_agent.models.state import WorkflowState
from bewerbungs_agent.utils.observability import (
    LangfuseObservability,
    NoOpObservability,
    NoOpStageSpan,
    TokenUsage,
    _active_span,
    _wrap_stage,
    build_observability,
)


def _make_config(**overrides: Any) -> MergedConfig:
    defaults: dict[str, Any] = {
        "template_id": "default_de_neutral",
        "language": "DE",
        "length": LengthMode.normal,
        "tone": "neutral-professionell",
        "mode": WritingMode.standard,
        "cv_selection": CVSelectionMode.automatic,
        "cv_tailoring": True,
        "soft_skill_max": 3,
        "output_sections": ["letter"],
        "validation_rules": {},
        "job_file": Path("data/examples/jobs/sample.md"),
        "output_dir": Path("outputs"),
    }
    defaults.update(overrides)
    return MergedConfig(**defaults)


# ---------------------------------------------------------------------------
# build_observability factory
# ---------------------------------------------------------------------------


class TestBuildObservability:
    def test_returns_noop_when_creds_missing(self) -> None:
        """No public/secret key in env → NoOp regardless of config flag."""
        config = ObservabilityConfig(langfuse=LangfuseConfig(enabled=True))
        obs = build_observability(config, env={})
        assert isinstance(obs, NoOpObservability)

    def test_returns_noop_when_only_public_key_present(self) -> None:
        config = ObservabilityConfig(langfuse=LangfuseConfig(enabled=True))
        obs = build_observability(config, env={"LANGFUSE_PUBLIC_KEY": "pk-test"})
        assert isinstance(obs, NoOpObservability)

    def test_returns_noop_when_config_disabled(self) -> None:
        """Config flag off → NoOp even with both creds present."""
        config = ObservabilityConfig(langfuse=LangfuseConfig(enabled=False))
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
        }
        obs = build_observability(config, env=env)
        assert isinstance(obs, NoOpObservability)

    def test_returns_langfuse_when_enabled_and_creds_present(self, mocker: Any) -> None:
        """Config on + both creds → LangfuseObservability instance.

        Patches the Langfuse SDK constructor so no real network call happens.
        """
        fake_client = MagicMock(name="Langfuse")
        mocker.patch("langfuse.Langfuse", return_value=fake_client)
        config = ObservabilityConfig(langfuse=LangfuseConfig(enabled=True))
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
        }
        obs = build_observability(config, env=env)
        assert isinstance(obs, LangfuseObservability)

    def test_never_raises_when_sdk_constructor_explodes(self, mocker: Any) -> None:
        """SDK constructor exception → falls back to NoOp silently."""
        mocker.patch("langfuse.Langfuse", side_effect=RuntimeError("auth failed"))
        config = ObservabilityConfig(langfuse=LangfuseConfig(enabled=True))
        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        obs = build_observability(config, env=env)
        assert isinstance(obs, NoOpObservability)


# ---------------------------------------------------------------------------
# NoOpObservability
# ---------------------------------------------------------------------------


class TestNoOpObservability:
    def test_all_methods_immediate_return(self) -> None:
        obs = NoOpObservability()
        # No exceptions on any method, regardless of arguments
        assert obs.start_trace("run-id", tags={"a": "b"}) is None
        with obs.stage_span("foo") as span:
            assert isinstance(span, NoOpStageSpan)
            span.set_prompt("p", "h")
            span.set_model("m")
            span.set_input({"a": 1})
            span.set_output({"b": 2})
            span.set_token_usage(TokenUsage(input_tokens=10))
            span.set_artifact_path("artifacts/foo.json")
            span.set_error(RuntimeError("ignored"))
        assert obs.trace_id() is None
        assert obs.trace_url() is None
        obs.flush(timeout_seconds=0.1)
        obs.close()
        obs.attach_artifact_paths("foo", ["x"])

    def test_stage_span_yields_singleton(self) -> None:
        obs = NoOpObservability()
        with obs.stage_span("a") as s1, obs.stage_span("b") as s2:
            assert s1 is s2  # singleton, zero allocation


# ---------------------------------------------------------------------------
# _wrap_stage helper
# ---------------------------------------------------------------------------


class _RecordingSpan:
    """A test-only span that records every mutator call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def set_prompt(self, prompt_name: str, prompt_hash: str) -> None:
        self._record("set_prompt", prompt_name, prompt_hash)

    def set_model(self, model: str) -> None:
        self._record("set_model", model)

    def set_input(self, payload: Any, full: bool = False) -> None:
        self._record("set_input", payload, full=full)

    def set_output(self, payload: Any, full: bool = False) -> None:
        self._record("set_output", payload, full=full)

    def set_token_usage(self, usage: TokenUsage) -> None:
        self._record("set_token_usage", usage)

    def set_artifact_path(self, relative_path: str) -> None:
        self._record("set_artifact_path", relative_path)

    def set_error(self, exc: BaseException) -> None:
        self._record("set_error", exc)


class _RecordingObservability:
    """A test-only Observability that records every stage_span request."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, _RecordingSpan]] = []
        self.enter_count = 0
        self.exit_count = 0

    def start_trace(self, run_id: str, tags: Any = None) -> None:
        return

    def stage_span(self, stage_name: str, *, prompt_name: Any = None) -> Any:
        span = _RecordingSpan()
        self.spans.append((stage_name, span))
        outer = self

        class _CM:
            def __enter__(self_inner) -> _RecordingSpan:
                outer.enter_count += 1
                return span

            def __exit__(self_inner, *exc: Any) -> None:
                outer.exit_count += 1

        return _CM()

    def trace_id(self) -> Any:
        return None

    def trace_url(self) -> Any:
        return None

    def flush(self, timeout_seconds: float = 3.0) -> None:
        return

    def close(self) -> None:
        return

    def attach_artifact_paths(self, stage_name: str, paths: list[str]) -> None:
        return


class TestWrapStage:
    def test_invokes_underlying_stage_with_unchanged_state_and_returns_unchanged_dict(self) -> None:
        config = _make_config()
        state = WorkflowState(config=config, observability=_RecordingObservability())

        seen_states: list[WorkflowState] = []

        def my_stage(s: WorkflowState) -> dict[str, Any]:
            seen_states.append(s)
            return {"requirements": None, "answer": 42}

        wrapped = _wrap_stage(my_stage, "extract_requirements", prompt_name="requirements")
        result = wrapped(state)
        assert result == {"requirements": None, "answer": 42}
        # State identity preserved (no clone), state not mutated:
        assert seen_states[0] is state

    def test_opens_and_closes_span(self) -> None:
        config = _make_config()
        rec = _RecordingObservability()
        state = WorkflowState(config=config, observability=rec)

        def my_stage(_: WorkflowState) -> dict[str, Any]:
            return {}

        wrapped = _wrap_stage(my_stage, "my_stage_name")
        wrapped(state)
        assert len(rec.spans) == 1
        assert rec.spans[0][0] == "my_stage_name"
        assert rec.enter_count == 1
        assert rec.exit_count == 1

    def test_captures_exception_and_reraises(self) -> None:
        config = _make_config()
        rec = _RecordingObservability()
        state = WorkflowState(config=config, observability=rec)

        def boom(_: WorkflowState) -> dict[str, Any]:
            raise RuntimeError("kaboom")

        wrapped = _wrap_stage(boom, "boom_stage")
        with pytest.raises(RuntimeError, match="kaboom"):
            wrapped(state)
        # Span recorded the error and was still closed.
        assert rec.exit_count == 1
        _, span = rec.spans[0]
        error_calls = [c for c in span.calls if c[0] == "set_error"]
        assert len(error_calls) == 1
        assert isinstance(error_calls[0][1][0], RuntimeError)

    def test_no_observability_attached_runs_stage_normally(self) -> None:
        """When observability is None (unit-test path), wrapper still works."""
        config = _make_config()
        state = WorkflowState(config=config)  # no observability
        assert state.observability is None

        def my_stage(_: WorkflowState) -> dict[str, Any]:
            return {"ok": True}

        wrapped = _wrap_stage(my_stage, "load_job")
        assert wrapped(state) == {"ok": True}

    def test_sets_prompt_metadata_for_llm_stages(self) -> None:
        config = _make_config()
        rec = _RecordingObservability()
        state = WorkflowState(config=config, observability=rec)

        def my_stage(_: WorkflowState) -> dict[str, Any]:
            return {}

        wrapped = _wrap_stage(my_stage, "plan_content", prompt_name="planner")
        wrapped(state)
        _, span = rec.spans[0]
        prompt_calls = [c for c in span.calls if c[0] == "set_prompt"]
        assert len(prompt_calls) == 1
        # First positional arg is prompt_name, second is the 16-char hash.
        assert prompt_calls[0][1][0] == "planner"
        assert len(prompt_calls[0][1][1]) > 0

    def test_does_not_set_prompt_for_non_llm_stages(self) -> None:
        config = _make_config()
        rec = _RecordingObservability()
        state = WorkflowState(config=config, observability=rec)

        def my_stage(_: WorkflowState) -> dict[str, Any]:
            return {}

        wrapped = _wrap_stage(my_stage, "load_job")  # prompt_name=None
        wrapped(state)
        _, span = rec.spans[0]
        prompt_calls = [c for c in span.calls if c[0] == "set_prompt"]
        assert prompt_calls == []
        model_calls = [c for c in span.calls if c[0] == "set_model"]
        assert model_calls == []

    def test_active_span_contextvar_is_set_during_stage(self) -> None:
        """The contextvar is set inside the stage and reset on exit."""
        config = _make_config()
        rec = _RecordingObservability()
        state = WorkflowState(config=config, observability=rec)
        captured: list[Any] = []

        def my_stage(_: WorkflowState) -> dict[str, Any]:
            captured.append(_active_span.get())
            return {}

        wrapped = _wrap_stage(my_stage, "any")
        wrapped(state)
        # Outside the stage the contextvar is back to None.
        assert _active_span.get() is None
        # Inside the stage it was set to the recording span.
        assert captured[0] is rec.spans[0][1]


# ---------------------------------------------------------------------------
# LangfuseObservability safety (mocked SDK)
# ---------------------------------------------------------------------------


class TestLangfuseObservabilitySafety:
    def test_start_trace_swallows_sdk_exception(self) -> None:
        client = MagicMock()
        client.create_trace_id.side_effect = RuntimeError("api down")
        obs = LangfuseObservability(client)
        # Must not raise; healthy flag flips
        obs.start_trace("run-id", tags={"a": "b"})
        assert obs._healthy is False

    def test_stage_span_falls_through_when_unhealthy(self) -> None:
        client = MagicMock()
        obs = LangfuseObservability(client)
        obs._healthy = False
        with obs.stage_span("x") as span:
            assert isinstance(span, NoOpStageSpan)
        # No SDK calls made
        client.start_observation.assert_not_called()

    def test_stage_span_falls_through_when_no_trace_id(self) -> None:
        client = MagicMock()
        obs = LangfuseObservability(client)
        # trace_id is None initially
        with obs.stage_span("x") as span:
            assert isinstance(span, NoOpStageSpan)
        client.start_observation.assert_not_called()

    def test_flush_is_bounded(self) -> None:
        """If client.flush hangs forever, our flush still returns within timeout."""
        import threading

        slow_event = threading.Event()
        client = MagicMock()
        client.flush.side_effect = lambda: slow_event.wait()  # blocks until set
        obs = LangfuseObservability(client)
        obs._trace_id = "fake"

        import time

        start = time.monotonic()
        obs.flush(timeout_seconds=0.3)
        elapsed = time.monotonic() - start
        slow_event.set()  # let the orphan thread finish
        assert elapsed < 1.0, f"flush did not respect timeout (elapsed={elapsed:.2f}s)"

    def test_close_swallows_sdk_exception(self) -> None:
        client = MagicMock()
        client.shutdown.side_effect = RuntimeError("disconnect failed")
        obs = LangfuseObservability(client)
        obs.close()  # must not raise
        assert obs._healthy is False

    def test_warns_only_once_across_many_failures(self) -> None:
        import warnings as warn_mod

        client = MagicMock()
        client.create_trace_id.side_effect = RuntimeError("boom1")
        client.start_observation.side_effect = RuntimeError("boom2")
        client.shutdown.side_effect = RuntimeError("boom3")
        obs = LangfuseObservability(client)
        with warn_mod.catch_warnings(record=True) as caught:
            warn_mod.simplefilter("always")
            obs.start_trace("r")
            with obs.stage_span("x"):
                pass
            obs.close()
        assert len(caught) == 1, f"expected 1 warning, got {len(caught)}"
