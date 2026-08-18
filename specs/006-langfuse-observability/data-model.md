# Phase 1 Data Model: Langfuse Observability

**Feature**: 006-langfuse-observability
**Date**: 2026-05-13

This feature introduces three new typed entities (configuration, span metadata, and a span-status enum) and adds one carrier field to `WorkflowState`. No existing state model semantics change.

---

## 1. New Pydantic models — `src/bewerbungs_agent/config/models.py`

### 1.1 `LangfuseConfig`

```python
class LangfuseConfig(BaseModel):
    """Langfuse-specific observability configuration.

    Read at CLI start. Combined with environment-variable credential presence
    to decide whether observability runs in no-op or active mode.
    """
    enabled: bool = False
    log_full_inputs: bool = False
    log_full_outputs: bool = False
    mask_pii: bool = True
```

**Field semantics**

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | False | Master switch in config. If False, observability is no-op even when env vars are set. |
| `log_full_inputs` | bool | False | When True, stage input spans receive the full pre-call state slice, not the summary. |
| `log_full_outputs` | bool | False | When True, stage output spans receive the full partial-update dict, not the summary. |
| `mask_pii` | bool | True | When True (default), PII regex pass runs in full-payload mode. Env-var-value redaction runs regardless. |

**Validation rules**: none beyond Pydantic types. No cross-field constraints.

### 1.2 `ObservabilityConfig`

```python
class ObservabilityConfig(BaseModel):
    """Container for all observability backends. Currently only Langfuse."""
    model_config = ConfigDict(extra="forbid")
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
```

**Why a container model**: leaves a clean namespace for future backends (e.g., `arize`, `phoenix`) without churning the operator config shape.

### 1.3 Insertions into `StarterTemplate` and `MergedConfig`

Both models gain one field:

```python
observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
```

Position: appended after `review_config` in both models so existing YAML files continue to parse unchanged.

### 1.4 `merge_config()` propagation

`src/bewerbungs_agent/utils/merge.py` MUST add to the explicit `base` dict (per the well-known `extra="forbid"` gotcha documented in `ENGINEERING.md` §15):

```python
base = {
    ...
    "observability": template.observability,
}
```

Omission would silently fall back to defaults — covered by `test_config_models.py::test_observability_config_flows_through_merge_config`.

---

## 2. Span metadata — `src/bewerbungs_agent/utils/observability.py`

Span metadata is held in a Pydantic dataclass rather than a free-form dict, so the redaction and summary layers can statically know what fields exist.

### 2.1 `SpanStatus` enum

```python
class SpanStatus(str, Enum):
    success = "success"
    error = "error"
```

### 2.2 `StageSpanRecord`

```python
class StageSpanRecord(BaseModel):
    """Everything the observability layer records for one stage execution.

    Built incrementally inside the stage-wrapping context manager:
    - on enter: stage_name, started_at, prompt_name, prompt_hash, model, input_summary
    - on exit (success):  ended_at, duration_ms, status="success", output_summary, token_usage, artifact_paths
    - on exit (error):    ended_at, duration_ms, status="error", error_type, error_message, error_trace_excerpt
    """

    stage_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: SpanStatus | None = None

    # Prompt + model — present only for LLM stages
    prompt_name: str | None = None
    prompt_hash: str | None = None
    model: str | None = None

    # Payload summaries / full payloads (mode-controlled)
    input_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None

    # Optional metadata
    token_usage: TokenUsage | None = None
    artifact_paths: list[str] = Field(default_factory=list)

    # Error info — present only when status == error
    error_type: str | None = None
    error_message: str | None = None
    error_trace_excerpt: str | None = None  # max 4 KB
```

### 2.3 `TokenUsage`

```python
class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
```

All fields optional because non-LLM stages do not produce usage; LLM stages that return only one field still produce a valid record.

---

## 3. Carrier field — `src/bewerbungs_agent/models/state.py`

`WorkflowState` gains one field, structurally identical to the existing `tracker` field:

```python
class WorkflowState(BaseModel):
    ...
    observability: Any | None = Field(default=None, exclude=True)
```

**Why `Any`**: avoids a circular import (observability module imports `WorkflowState` for type hints in the wrapper). `exclude=True` ensures the SDK object is never serialised into JSON if a stage or artifact writer happens to dump state.

**Position**: appended after `tracker` so existing serialisation/deserialisation behaviour is unchanged.

---

## 4. Lifecycle and state transitions

### 4.1 `StageSpanRecord` lifecycle

```
[constructed on stage enter]
        │
        ▼
   stage runs ─┬─ success path ──▶ ended_at, duration_ms, output_summary,
               │                   token_usage, artifact_paths, status=success
               │
               └─ exception path ─▶ ended_at, duration_ms, error_type, error_message,
                                   error_trace_excerpt, status=error
        │
        ▼
[sent to Langfuse OR dropped if no-op]
```

Records are not held in memory beyond one stage execution; once the span is closed on the SDK side, the record is dropped.

### 4.2 Observability lifecycle (per CLI run)

```
cli.run() entry
   │
   ▼
build_observability(merged_config)  ──▶  NoOpObservability   (if disabled or creds missing)
                                  └──▶  LangfuseObservability  (if enabled + creds present)
   │
   ▼
observability.start_trace(run_id, tags={template_id, cv_variant, ...})
   │
   ▼
state.observability = observability   ──▶  threaded through LangGraph
   │
   ▼
[stage spans nested under the trace, see §4.1]
   │
   ▼
finally:
    observability.flush(timeout=3.0)
    observability.close()
```

`KeyboardInterrupt` and uncaught exceptions still reach the `finally` block (Python guarantee).

---

## 5. Validation rules

| Rule | Where enforced | What fails |
|---|---|---|
| `ObservabilityConfig` has no unknown sub-keys | Pydantic `extra="forbid"` | YAML key typo (e.g., `langfues:`) raises at config load |
| `LangfuseConfig.log_full_inputs == True` requires `enabled == True` | runtime check in `build_observability()` | a single-line warning + downgrade to disabled, NOT a hard fail (consistent with FR-015 non-fatal posture) |
| `StageSpanRecord.error_trace_excerpt` ≤ 4 KB | producer in `observability.py` | truncated with `...[truncated]` marker |
| `TokenUsage.input_tokens >= 0` | Pydantic `Field(ge=0)` on each | invalid LLM response |
| Run ID matches `^[a-f0-9]{8,}$` (existing convention) | producer side | n/a — reuses existing run_id generation |

---

## 6. Relationship diagram

```
ObservabilityConfig
  └── LangfuseConfig
         (read once at CLI start)
                │
                ▼
        build_observability()
                │
   ┌────────────┴────────────┐
   │                         │
NoOpObservability      LangfuseObservability
   │                         │
   └───────────┬─────────────┘
               │ (Protocol: Observability)
               ▼
        WorkflowState.observability  (Any | None, exclude=True)
               │
               ▼
        _wrap_stage(...)  in workflow.py
               │
               ▼
        StageSpanRecord  (per stage execution)
               │
               ├── prompt_name, prompt_hash  (from existing _compute_prompt_hash)
               ├── model                      (from AnthropicLLMClient.MODEL)
               ├── input_summary / full input (from utils/summaries.py)
               ├── output_summary / full output
               ├── token_usage                (from LLM response.usage)
               ├── artifact_paths             (from writer return value)
               └── status / error_*           (from try/except in wrapper)
                                │
                                ▼
                       redaction pass (utils/redaction.py)
                                │
                                ▼
                       Langfuse SDK call
```

---

## 7. Backward-compatibility audit

- Existing starter-template YAML files: continue to parse — `observability` field has a default.
- Existing `WorkflowState` serialisation (artifact JSON writers): unchanged — `exclude=True` keeps the new field out.
- Existing `MergedConfig` consumers (every stage): unchanged — they read the fields they already used.
- Existing `MLflow PipelineTracker` behaviour: unchanged — one new method (`log_langfuse_link`) is purely additive.

No migration step required.
