# Contract: `Observability` Protocol

**Feature**: 006-langfuse-observability
**Module**: `src/bewerbungs_agent/utils/observability.py`
**Date**: 2026-05-13

This contract defines the single internal surface that the rest of the codebase calls. Two implementations satisfy it: `NoOpObservability` and `LangfuseObservability`. A factory function chooses between them at CLI startup.

---

## 1. The Protocol

```python
from typing import Protocol, ContextManager

class Observability(Protocol):
    """Internal observability surface.

    Implementations: NoOpObservability, LangfuseObservability.
    All methods MUST be exception-safe: a failure inside an implementation
    MUST NOT propagate to the caller (FR-015).
    """

    def start_trace(
        self,
        run_id: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Open the parent trace for a single CLI invocation.

        Called exactly once per process at the top of `cli.run`.
        For NoOp, immediate return.
        """

    def stage_span(
        self,
        stage_name: str,
        *,
        prompt_name: str | None = None,
        input_summary: dict | None = None,
        attempt: int = 1,
    ) -> ContextManager["StageSpan"]:
        """Open one nested span around a stage execution.

        Returns a context manager that yields a StageSpan handle.
        Caller uses the handle to attach output_summary, token_usage,
        artifact_paths, and error info before exit.
        """

    def trace_id(self) -> str | None:
        """Return the active trace ID, or None when disabled."""

    def trace_url(self) -> str | None:
        """Return a human-clickable URL for the trace, or None when disabled."""

    def flush(self, timeout_seconds: float = 3.0) -> None:
        """Block up to `timeout_seconds` for the SDK to drain queued events.

        MUST return regardless of whether the drain completed.
        MUST NOT raise.
        """

    def close(self) -> None:
        """Release any background resources (threads, sockets)."""
```

### 1.1 `StageSpan` handle

```python
class StageSpan(Protocol):
    """Mutator handle yielded by stage_span(...) context manager.

    Methods are call-and-forget; mutation order does not matter.
    Implementations MUST swallow internal exceptions.
    """

    def set_prompt(self, prompt_name: str, prompt_hash: str) -> None: ...
    def set_model(self, model: str) -> None: ...
    def set_input(self, payload: dict, full: bool = False) -> None: ...
    def set_output(self, payload: dict, full: bool = False) -> None: ...
    def set_token_usage(self, usage: "TokenUsage") -> None: ...
    def set_artifact_path(self, relative_path: str) -> None: ...
    def set_error(self, exc: BaseException) -> None: ...
```

---

## 2. Factory function

```python
def build_observability(
    config: "ObservabilityConfig",
    env: Mapping[str, str] | None = None,
) -> Observability:
    """Decide which Observability implementation to construct.

    Decision matrix:

      config.langfuse.enabled == False               → NoOpObservability
      LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY     → NoOpObservability
        missing in env (FR-011)                       (single debug log line)
      langfuse SDK import fails                      → NoOpObservability
                                                       (single debug log line)
      otherwise                                       → LangfuseObservability

    `env` parameter exists for tests; defaults to os.environ.
    """
```

**Decision invariants**:
- The function MUST NOT raise, regardless of misconfiguration.
- The function MUST run in under 50 ms when returning `NoOpObservability` (no network calls).

---

## 3. `NoOpObservability` contract

| Method | Behaviour |
|---|---|
| `start_trace` | Immediate return. |
| `stage_span` | Returns a context manager whose `StageSpan` is a no-op mutator. Enter/exit allocate at most one tiny object. |
| `trace_id` | Returns `None`. |
| `trace_url` | Returns `None`. |
| `flush` | Immediate return. |
| `close` | Immediate return. |

**Cost target**: ≤ 1 ms wall-clock per `stage_span(...)` enter+exit cycle when disabled.

---

## 4. `LangfuseObservability` contract

| Method | Behaviour |
|---|---|
| `start_trace(run_id, tags)` | Calls `self._client.trace(name=run_id, id=run_id, tags=tags)`. On SDK exception, emits one warning and switches `self._healthy = False`; all subsequent calls behave like NoOp for the rest of the run. |
| `stage_span(stage_name, ...)` | If healthy, calls `self._trace.span(name=stage_name, input=…)`. Returns a context manager wrapping the SDK span. On any SDK exception inside the context, swallow, emit one warning per trace, mark unhealthy. |
| `trace_id` | Returns the SDK-assigned ID, or `None` if start_trace failed. |
| `trace_url` | Returns a URL composed from `LANGFUSE_BASE_URL` and the trace ID; `None` if either is missing. |
| `flush(timeout_seconds)` | Calls `self._client.flush(timeout=timeout_seconds)`; if the SDK does not expose `timeout=`, wraps the call in a thread with `Thread.join(timeout)`. MUST return within the timeout. |
| `close` | Calls `self._client.shutdown()` if available; otherwise no-op. |

**Healthy-state invariant**: once `self._healthy` flips to False (any SDK failure), all subsequent observability calls in the same process behave as NoOp. Operator sees one warning, not N.

---

## 5. Stage-wrapping helper contract

```python
def _wrap_stage(
    stage_fn: Callable[[WorkflowState], dict[str, Any]],
    stage_name: str,
    *,
    prompt_name: str | None = None,
    artifact_writer: Callable[[dict[str, Any]], list[str]] | None = None,
) -> Callable[[WorkflowState], dict[str, Any]]:
    """Wrap a LangGraph node with one observability span.

    Behaviour:
      1. Read state.observability (may be None during tests not using the wrapper).
      2. Compute input_summary from state via utils/summaries.py.
      3. Open span via state.observability.stage_span(stage_name, ...).
      4. Call stage_fn(state) inside the context.
      5. Compute output_summary from the partial-update dict.
      6. If artifact_writer provided, record returned paths via span.set_artifact_path(...).
      7. On exception: span.set_error(exc); RE-RAISE (LangGraph must see the error).
      8. Return the partial-update dict unchanged.

    MUST NOT mutate state.
    MUST NOT change stage_fn's signature or return shape.
    MUST NOT swallow stage exceptions (they belong to LangGraph control flow).
    """
```

**Critical invariant**: `_wrap_stage` adds observability SIDE EFFECTS only. The return value of the wrapped function is byte-identical to the unwrapped function's return value. This is what makes FR-013 hold.

---

## 6. Workflow wiring contract

In `src/bewerbungs_agent/graph/workflow.py`, the existing `_import_stage(...)` pattern is unchanged. Each `graph.add_node(...)` call is wrapped:

```python
graph.add_node("extract_requirements", _wrap_stage(extract_req_fn, "extract_requirements", prompt_name="requirements"))
graph.add_node("build_evidence_map",   _wrap_stage(build_evidence_fn, "build_evidence_map", prompt_name="evidence"))
graph.add_node("plan_content",         _wrap_stage(plan_content_fn,   "plan_content",       prompt_name="planner"))
graph.add_node("write_letter",         _wrap_stage(write_letter_fn,   "write_letter",       prompt_name="writer"))
graph.add_node("tailor_cv",            _wrap_stage(tailor_cv_fn,      "tailor_cv",          prompt_name="tailor_cv"))
graph.add_node("hiring_review",        _wrap_stage(hiring_review_fn,  "hiring_review",      prompt_name="hiring_reviewer"))
graph.add_node("targeted_rewrite",     _wrap_stage(targeted_rewrite_fn,"targeted_rewrite",  prompt_name="targeted_rewriter"))
graph.add_node("validate_outputs",     _wrap_stage(validate_fn,       "validate_outputs"))
graph.add_node("rewrite_if_needed",    _wrap_stage(rewrite_fn,        "rewrite_if_needed",  prompt_name="writer"))
# load_job, load_profile, select_cv_variant — wrapped too but with prompt_name=None
```

**Per FR-016a**, no synthetic parent span is added around the `write_letter`+`tailor_cv` branches. Sibling order is whatever LangGraph emits.

---

## 7. CLI lifecycle contract

In `src/bewerbungs_agent/cli.py`, the `run` command MUST follow this skeleton:

```python
def run(...):
    merged_config = merge_config(template, run_input)
    run_id = _new_run_id()

    tracker = PipelineTracker(merged_config.tracking, run_id)
    tracker.start_run(job_title=...)

    observability = build_observability(merged_config.observability)
    observability.start_trace(
        run_id=run_id,
        tags={"template_id": merged_config.template_id, "cv_variant": "..."},
    )
    tracker.log_langfuse_link(observability.trace_id(), observability.trace_url())

    try:
        state = WorkflowState(config=merged_config, observability=observability, tracker=tracker, run_id=run_id)
        final_state = graph.invoke(state)
        _write_artifacts(final_state, output_dir)
    finally:
        observability.flush(timeout_seconds=3.0)
        observability.close()
        tracker.end_run()
```

The `try/finally` MUST cover both `graph.invoke` and `_write_artifacts` so a write-time exception still flushes.

---

## 8. Test surface implied by the contract

| Behaviour to test | Test file | Key assertion |
|---|---|---|
| `build_observability` returns NoOp when env vars missing | `test_observability.py` | `isinstance(o, NoOpObservability)` |
| `build_observability` returns NoOp when config disabled | `test_observability.py` | same as above with env vars present |
| `build_observability` returns Langfuse impl when both present | `test_observability.py` | `isinstance(o, LangfuseObservability)`, no SDK call yet |
| `_wrap_stage` calls underlying stage with unchanged state and returns unchanged dict | `test_observability.py` | output dict equality |
| `_wrap_stage` opens and closes a span around the call | `test_observability.py` | mock span receives `__enter__` and `__exit__` |
| `_wrap_stage` records error on exception and re-raises | `test_observability.py` | `pytest.raises(...)` + mock span.set_error called |
| Redaction strips API keys and PII (full mode) | `test_redaction.py` | every distinctive string removed |
| Full pipeline produces identical artifacts enabled vs disabled | `test_full_run.py` | `filecmp.cmp(..., shallow=False)` true for every output file |
| Full pipeline emits spans for every stage when enabled | `test_full_run.py` | recorded span names equal expected set |
| Stage exception captured on span as `error` | `test_full_run.py` | span recorded with `status=error`, type+message present |

All FRs FR-001 through FR-025 are covered by the matrix in `research.md` §R11.
