"""Langfuse observability wrapper.

Two implementations behind one Protocol:
- ``NoOpObservability``: zero-cost, used when disabled or credentials missing.
- ``LangfuseObservability``: backed by the official langfuse SDK.

Stage modules remain observability-unaware. Integration happens at the
graph-wiring layer via ``_wrap_stage`` and at the CLI boundary.

All public methods MUST swallow internal exceptions; a Langfuse failure
MUST NOT abort the pipeline (FR-015).
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
import traceback
import warnings
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Iterator, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from bewerbungs_agent.config.models import ObservabilityConfig
    from bewerbungs_agent.models.state import WorkflowState
    from bewerbungs_agent.utils.prompt_registry import PromptReference

_LOGGER = logging.getLogger("bewerbungs_agent.observability")

# Module-level context variable so the LLM client can attach token usage to the
# active stage span without importing the Observability Protocol. The wrapper
# sets and resets this around each stage call (see _wrap_stage).
_active_span: contextvars.ContextVar["StageSpan | None"] = contextvars.ContextVar(
    "bewerbungs_active_span", default=None
)


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


class SpanStatus(str, Enum):
    success = "success"
    error = "error"


class TokenUsage(BaseModel):
    """LLM token usage. All fields optional — non-LLM stages produce no usage."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class StageSpan(Protocol):
    """Mutator handle yielded by ``Observability.stage_span(...)``.

    Methods are call-and-forget; implementations MUST swallow internal errors.
    """

    def set_prompt(self, prompt_name: str, prompt_hash: str) -> None: ...

    def set_model(self, model: str) -> None: ...

    def set_input(self, payload: Any, full: bool = False) -> None: ...

    def set_output(self, payload: Any, full: bool = False) -> None: ...

    def set_token_usage(self, usage: TokenUsage) -> None: ...

    def set_artifact_path(self, relative_path: str) -> None: ...

    def set_error(self, exc: BaseException) -> None: ...

    def set_prompt_reference(self, reference: "PromptReference") -> None: ...


class Observability(Protocol):
    """Internal observability surface.

    Implementations: NoOpObservability, LangfuseObservability.
    """

    def start_trace(self, run_id: str, tags: dict[str, str] | None = None) -> None: ...

    def stage_span(
        self,
        stage_name: str,
        *,
        prompt_name: str | None = None,
    ) -> Any:  # ContextManager[StageSpan]
        ...

    def trace_id(self) -> str | None: ...

    def trace_url(self) -> str | None: ...

    def flush(self, timeout_seconds: float = 3.0) -> None: ...

    def close(self) -> None: ...

    def attach_artifact_paths(self, stage_name: str, paths: list[str]) -> None: ...

    def underlying_client(self) -> Any | None: ...


# ---------------------------------------------------------------------------
# No-op implementation
# ---------------------------------------------------------------------------


class NoOpStageSpan:
    """A do-nothing StageSpan. All mutators are immediate returns."""

    __slots__ = ()

    def set_prompt(self, prompt_name: str, prompt_hash: str) -> None:
        pass

    def set_model(self, model: str) -> None:
        pass

    def set_input(self, payload: Any, full: bool = False) -> None:
        pass

    def set_output(self, payload: Any, full: bool = False) -> None:
        pass

    def set_token_usage(self, usage: TokenUsage) -> None:
        pass

    def set_artifact_path(self, relative_path: str) -> None:
        pass

    def set_error(self, exc: BaseException) -> None:
        pass

    def set_prompt_reference(self, reference: "PromptReference") -> None:
        pass


_NOOP_SPAN_SINGLETON = NoOpStageSpan()


class NoOpObservability:
    """Zero-cost Observability. Does not import langfuse."""

    __slots__ = ()

    def start_trace(self, run_id: str, tags: dict[str, str] | None = None) -> None:
        return

    @contextmanager
    def stage_span(
        self,
        stage_name: str,
        *,
        prompt_name: str | None = None,
    ) -> Iterator[StageSpan]:
        yield _NOOP_SPAN_SINGLETON

    def trace_id(self) -> str | None:
        return None

    def trace_url(self) -> str | None:
        return None

    def flush(self, timeout_seconds: float = 3.0) -> None:
        return

    def close(self) -> None:
        return

    def attach_artifact_paths(self, stage_name: str, paths: list[str]) -> None:
        return

    def underlying_client(self) -> Any | None:
        return None


# ---------------------------------------------------------------------------
# Langfuse-backed implementation
# ---------------------------------------------------------------------------


class LangfuseStageSpan:
    """StageSpan backed by a Langfuse SDK observation.

    Holds a reference to the underlying SDK span object and forwards mutator
    calls. Every SDK call is wrapped in try/except — a span error never
    propagates and never aborts the pipeline (FR-015).
    """

    __slots__ = ("_sdk_span", "_log_full_inputs", "_log_full_outputs", "_redact", "_owner")

    def __init__(
        self,
        sdk_span: Any,
        *,
        log_full_inputs: bool,
        log_full_outputs: bool,
        redact: Callable[[Any, str], Any],
        owner: "LangfuseObservability",
    ) -> None:
        self._sdk_span = sdk_span
        self._log_full_inputs = log_full_inputs
        self._log_full_outputs = log_full_outputs
        self._redact = redact
        self._owner = owner

    def _safe_update(self, **kwargs: Any) -> None:
        try:
            self._sdk_span.update(**kwargs)
        except Exception as exc:  # noqa: BLE001
            self._owner._note_failure(f"span.update: {exc}")

    def set_prompt(self, prompt_name: str, prompt_hash: str) -> None:
        self._safe_update(metadata={"prompt_name": prompt_name, "prompt_hash": prompt_hash})

    def set_model(self, model: str) -> None:
        self._safe_update(metadata={"model": model})

    def set_input(self, payload: Any, full: bool = False) -> None:
        # `full` mirrors the wrapper's intent: when False the payload is a
        # summary; when True the caller wants the raw payload sent.
        # Redaction runs regardless of `full` — secrets are always stripped;
        # PII is stripped only in full mode (handled by the redactor).
        mode = "full" if full else "summary"
        cleaned = self._redact(payload, mode)
        self._safe_update(input=cleaned)

    def set_output(self, payload: Any, full: bool = False) -> None:
        mode = "full" if full else "summary"
        cleaned = self._redact(payload, mode)
        self._safe_update(output=cleaned)

    def set_token_usage(self, usage: TokenUsage) -> None:
        details: dict[str, int] = {}
        if usage.input_tokens is not None:
            details["input"] = usage.input_tokens
        if usage.output_tokens is not None:
            details["output"] = usage.output_tokens
        if usage.total_tokens is not None:
            details["total"] = usage.total_tokens
        if not details:
            return
        self._safe_update(usage_details=details)

    def set_artifact_path(self, relative_path: str) -> None:
        self._safe_update(metadata={"artifact_path": relative_path})

    def set_error(self, exc: BaseException) -> None:
        trace_excerpt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if len(trace_excerpt) > 4096:
            trace_excerpt = trace_excerpt[:4096] + "\n...[truncated]"
        try:
            self._sdk_span.update(
                level="ERROR",
                status_message=f"{type(exc).__name__}: {exc}",
                metadata={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "error_trace_excerpt": trace_excerpt,
                },
            )
        except Exception as inner:  # noqa: BLE001
            self._owner._note_failure(f"span.set_error: {inner}")

    def set_prompt_reference(self, reference: "PromptReference") -> None:
        self._safe_update(metadata={
            "prompt_name": reference.prompt_name,
            "prompt_version": (
                reference.prompt_version if reference.prompt_version is not None else "unsynced"
            ),
            "prompt_content_hash": reference.content_hash,
            "prompt_label_at_resolve": reference.label_at_resolve,
        })


class LangfuseObservability:
    """Observability backed by the official langfuse SDK (v2+/v4+ compatible).

    Lifecycle:
      start_trace(run_id, tags)  → derives deterministic trace_id from run_id
                                    and opens one root span carrying tags.
      stage_span(name)           → opens one child observation under the trace.
      flush(timeout_seconds)     → bounded by thread.join(timeout); 3 s default.
      close()                    → calls SDK shutdown().

    On any SDK failure ``self._healthy`` flips to False; all subsequent calls
    become no-ops for the rest of the process (single warning per session).
    """

    def __init__(
        self,
        sdk_client: Any,
        *,
        log_full_inputs: bool = False,
        log_full_outputs: bool = False,
        mask_pii: bool = True,
    ) -> None:
        self._client = sdk_client
        self._log_full_inputs = log_full_inputs
        self._log_full_outputs = log_full_outputs
        self._mask_pii = mask_pii
        self._trace_id: str | None = None
        self._healthy: bool = True
        self._warned: bool = False
        # Stage name -> most recent live SDK span (for artifact-path attach).
        self._live_spans: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _note_failure(self, message: str) -> None:
        """Mark unhealthy and emit at most one warning per process."""
        self._healthy = False
        if not self._warned:
            self._warned = True
            warnings.warn(f"langfuse observability error (non-fatal): {message}", stacklevel=2)

    def _redact(self, payload: Any, mode: str) -> Any:
        try:
            from bewerbungs_agent.utils.redaction import redact
        except ImportError:
            return payload
        try:
            return redact(payload, mode=mode, mask_pii=self._mask_pii)
        except Exception as exc:  # noqa: BLE001
            # Redaction failure → drop payload entirely; never ship un-redacted.
            self._note_failure(f"redaction: {exc}")
            return None

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def start_trace(self, run_id: str, tags: dict[str, str] | None = None) -> None:
        if not self._healthy:
            return
        try:
            self._trace_id = self._client.create_trace_id(seed=run_id)
            tag_metadata: dict[str, Any] = {"run_id": run_id}
            if tags:
                tag_metadata.update(tags)
            root = self._client.start_observation(
                name=f"run:{run_id}",
                as_type="span",
                trace_context={"trace_id": self._trace_id},
                metadata=tag_metadata,
            )
            try:
                root.end()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"start_trace: {exc}")

    @contextmanager
    def stage_span(
        self,
        stage_name: str,
        *,
        prompt_name: str | None = None,
    ) -> Iterator[StageSpan]:
        if not self._healthy or self._trace_id is None:
            yield _NOOP_SPAN_SINGLETON
            return

        sdk_span = None
        try:
            sdk_span = self._client.start_observation(
                name=stage_name,
                as_type="span",
                trace_context={"trace_id": self._trace_id},
                metadata={"stage_name": stage_name},
            )
            self._live_spans[stage_name] = sdk_span
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"start_observation({stage_name}): {exc}")
            yield _NOOP_SPAN_SINGLETON
            return

        span = LangfuseStageSpan(
            sdk_span,
            log_full_inputs=self._log_full_inputs,
            log_full_outputs=self._log_full_outputs,
            redact=self._redact,
            owner=self,
        )
        try:
            yield span
        finally:
            try:
                sdk_span.end()
            except Exception as exc:  # noqa: BLE001
                self._note_failure(f"span.end({stage_name}): {exc}")

    def trace_id(self) -> str | None:
        return self._trace_id

    def trace_url(self) -> str | None:
        if self._trace_id is None:
            return None
        try:
            base = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
            if not base:
                return None
            base = base.rstrip("/")
            return f"{base}/trace/{self._trace_id}"
        except Exception:  # noqa: BLE001
            return None

    def flush(self, timeout_seconds: float = 3.0) -> None:
        if not self._healthy:
            return
        # langfuse SDK v4 flush() takes no timeout argument; bound via thread.
        done = threading.Event()
        error_holder: list[BaseException] = []

        def _runner() -> None:
            try:
                self._client.flush()
            except BaseException as exc:  # noqa: BLE001
                error_holder.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_runner, name="langfuse-flush", daemon=True)
        start = time.monotonic()
        thread.start()
        thread.join(timeout=timeout_seconds)
        elapsed = time.monotonic() - start
        if not done.is_set():
            self._note_failure(f"flush exceeded {timeout_seconds}s (elapsed {elapsed:.2f}s); trace events may be lost")
            return
        if error_holder:
            self._note_failure(f"flush: {error_holder[0]}")

    def close(self) -> None:
        try:
            self._client.shutdown()
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"shutdown: {exc}")

    def attach_artifact_paths(self, stage_name: str, paths: list[str]) -> None:
        if not self._healthy or not paths:
            return
        span = self._live_spans.get(stage_name)
        if span is None:
            return
        try:
            span.update(metadata={"artifact_paths": list(paths)})
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"attach_artifact_paths({stage_name}): {exc}")

    def underlying_client(self) -> Any | None:
        if not self._healthy:
            return None
        return self._client


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_observability(
    config: "ObservabilityConfig",
    env: Mapping[str, str] | None = None,
) -> Observability:
    """Choose NoOp or Langfuse based on config and environment.

    Decision matrix:
      config.langfuse.enabled == False           → NoOp
      LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY → NoOp (single debug log)
        missing in env
      langfuse SDK import / construction fails    → NoOp (single debug log)
      otherwise                                   → LangfuseObservability

    Never raises.
    """
    if env is None:
        env = os.environ

    lf_cfg = config.langfuse
    if not lf_cfg.enabled:
        return NoOpObservability()

    public_key = env.get("LANGFUSE_PUBLIC_KEY")
    secret_key = env.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        _LOGGER.debug("Langfuse credentials missing; observability disabled.")
        return NoOpObservability()

    base_url = env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST")

    try:
        from langfuse import Langfuse
    except ImportError as exc:
        _LOGGER.debug("langfuse SDK not installed (%s); observability disabled.", exc)
        return NoOpObservability()

    try:
        kwargs: dict[str, Any] = {"public_key": public_key, "secret_key": secret_key}
        if base_url:
            kwargs["host"] = base_url
        client = Langfuse(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Langfuse client construction failed (%s); observability disabled.", exc)
        return NoOpObservability()

    return LangfuseObservability(
        client,
        log_full_inputs=lf_cfg.log_full_inputs,
        log_full_outputs=lf_cfg.log_full_outputs,
        mask_pii=lf_cfg.mask_pii,
    )


# ---------------------------------------------------------------------------
# Stage-wrapping helper
# ---------------------------------------------------------------------------


def _wrap_stage(
    stage_fn: Any,
    stage_name: str,
    *,
    prompt_name: str | None = None,
) -> Any:
    # Typed as Any to match the broad node-callable contract LangGraph accepts
    # internally; the runtime signature is (WorkflowState) -> dict[str, Any].
    """Wrap a LangGraph node with one observability span.

    Behaviour:
      1. Read state.observability (None ⇒ no-op, for tests that bypass CLI).
      2. Compute input summary via summaries.summarise_state_for_stage(...).
      3. Open span via observability.stage_span(stage_name, ...).
      4. Set prompt metadata + model name (LLM stages).
      5. Call stage_fn(state) inside the context with `_active_span` set.
      6. Compute output summary via summaries.summarise_partial_update(...).
      7. On exception: span.set_error(exc); RE-RAISE (LangGraph needs the error).
      8. Return the stage's partial-update dict unchanged.

    MUST NOT mutate state. MUST NOT swallow stage exceptions.
    """

    def _wrapped(state: "WorkflowState") -> dict[str, Any]:
        obs = getattr(state, "observability", None)
        if obs is None:
            # No observability attached (unit tests, validate-only path) — call
            # the underlying stage directly. No span recording.
            result: dict[str, Any] = stage_fn(state)
            return result

        # Lazy import to avoid circular dependency at module load.
        try:
            from bewerbungs_agent.utils.summaries import (
                summarise_partial_update,
                summarise_state_for_stage,
            )
        except ImportError:  # pragma: no cover
            summarise_state_for_stage = None  # type: ignore[assignment]
            summarise_partial_update = None  # type: ignore[assignment]

        try:
            from bewerbungs_agent.utils.tracker import _compute_prompt_hash
        except ImportError:  # pragma: no cover
            def _compute_prompt_hash(prompt_name: str) -> str:
                return "unknown"

        # Resolve full-payload flags from config when present
        log_full_inputs = False
        log_full_outputs = False
        cfg_obs = getattr(state.config, "observability", None)
        if cfg_obs is not None:
            log_full_inputs = cfg_obs.langfuse.log_full_inputs
            log_full_outputs = cfg_obs.langfuse.log_full_outputs

        with obs.stage_span(stage_name, prompt_name=prompt_name) as span:
            # Prompt + model metadata
            if prompt_name:
                local_hash = _compute_prompt_hash(prompt_name)
                # Backward-compatible setter (kept for any older consumers).
                span.set_prompt(prompt_name, local_hash)
                # All LLM stages currently use this model
                try:
                    from bewerbungs_agent.utils.llm_client import AnthropicLLMClient

                    span.set_model(AnthropicLLMClient.MODEL)
                except Exception:  # noqa: BLE001
                    pass
                # Feature 007: attach a Langfuse Prompt Registry reference.
                # Resolution is cached per (qualified_name, local_hash) so
                # this incurs at most one Langfuse round-trip per process.
                try:
                    from bewerbungs_agent.utils.prompt_registry import runtime_reference

                    qualified = f"bewerbungs-agent/{prompt_name}"
                    reference = runtime_reference(
                        qualified, local_hash, client=obs.underlying_client()
                    )
                    span.set_prompt_reference(reference)
                except Exception:  # noqa: BLE001
                    # Never let registry resolution affect the stage execution.
                    pass

            # Input summary or full payload
            try:
                if log_full_inputs and summarise_state_for_stage is not None:
                    # Full mode: ship the typed input view; redaction runs on send.
                    payload = summarise_state_for_stage(stage_name, state, full=True)
                    span.set_input(payload, full=True)
                elif summarise_state_for_stage is not None:
                    payload = summarise_state_for_stage(stage_name, state, full=False)
                    span.set_input(payload, full=False)
            except Exception:  # noqa: BLE001
                pass

            # Attach span to context var so the LLM client can record usage
            token = _active_span.set(span)
            update: dict[str, Any]
            try:
                update = stage_fn(state)
            except BaseException as exc:
                span.set_error(exc)
                raise
            finally:
                _active_span.reset(token)

            # Output summary or full payload
            try:
                if summarise_partial_update is not None:
                    if log_full_outputs:
                        span.set_output(update, full=True)
                    else:
                        span.set_output(summarise_partial_update(stage_name, update), full=False)
            except Exception:  # noqa: BLE001
                pass

            return update

    _wrapped.__name__ = f"wrapped_{stage_name}"
    return _wrapped
