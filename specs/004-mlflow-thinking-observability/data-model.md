# Data Model: MLflow Observability and Thinking Config

**Feature**: 004-mlflow-thinking-observability  
**Date**: 2026-04-15

## New Entities

### ThinkingEffort (Enum)

| Field | Type | Values | Default |
|-------|------|--------|---------|
| value | str | "low", "medium", "high" | — |

Maps to Anthropic API `budget_tokens`: low=1024, medium=8000, high=16000.

---

### ThinkingConfig (Pydantic BaseModel)

Controls extended thinking for a single stage or as a global default.

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| enabled | bool | False | — |
| effort | ThinkingEffort | ThinkingEffort.medium | Must be a valid ThinkingEffort value |

**Validation**: If `enabled=False`, `effort` is ignored but must still be a valid enum value.  
**Location**: `src/bewerbungs_agent/config/models.py`

---

### TrackingConfig (Pydantic BaseModel)

Top-level tracking configuration. Opt-in; all fields have safe defaults.

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| enabled | bool | False | — |
| tracking_uri | str | "mlruns" | Non-empty string; relative = local file store |
| experiment_name | str | "bewerbungs-agent" | Non-empty string |

**Validation**: When `enabled=False`, no MLflow code executes — no `mlruns/` directory is created.  
**Location**: `src/bewerbungs_agent/config/models.py`

---

### PipelineTracker (Class, not Pydantic)

Runtime-only object. Never serialized. Wraps MLflow calls with non-blocking error handling.

| Attribute | Type | Description |
|-----------|------|-------------|
| _config | TrackingConfig | Tracking settings |
| _run_id | str | Agent run ID (linked to WorkflowState.run_id) |
| _mlflow | module | Lazily imported mlflow module |
| _active | bool | Whether a run was successfully started |

**Methods**:

| Method | Parameters | Side Effects |
|--------|-----------|--------------|
| `start_run` | `job_title: str \| None` | Calls `mlflow.start_run()`, logs run-level params |
| `log_stage` | `stage_name, model, thinking, prompt_name, prompt_hash, **extra` | Logs stage params/tags to active run |
| `log_outputs` | `evidence_count, gaps_count, letter_char_count, validation_passes, rewrite_count` | Logs final pipeline metrics |
| `end_run` | `status: str = "FINISHED"` | Calls `mlflow.end_run()` |

All methods are non-blocking: every MLflow call is wrapped in `try/except Exception` with `warnings.warn` on failure.  
**Location**: `src/bewerbungs_agent/utils/tracker.py`

---

### MLflow RunRecord (external, via mlflow SDK)

Not a Pydantic model — managed by MLflow. Documented here for traceability.

**Run-level parameters** (logged via `mlflow.log_param`):

| Key | Value |
|-----|-------|
| `run_id` | WorkflowState.run_id |
| `job_file` | str(config.job_file) |
| `template_id` | config.template_id |
| `language` | config.language |
| `mode` | config.mode.value |
| `model` | AnthropicLLMClient.MODEL |
| `thinking_enabled_global` | str(config.thinking.enabled) |
| `thinking_effort_global` | config.thinking.effort.value |
| `job_title` | extracted job title if available, else "" |

**Per-stage tags** (logged via `mlflow.set_tag`):

| Key Pattern | Value |
|-------------|-------|
| `stage.{name}.thinking_enabled` | "true" / "false" |
| `stage.{name}.thinking_effort` | "low" / "medium" / "high" |
| `stage.{name}.prompt_name` | e.g., "system", "writer" |
| `stage.{name}.prompt_hash` | 16-char SHA-256 prefix |
| `stage.{name}.model` | model identifier |

**Output metrics** (logged via `mlflow.log_metric`):

| Key | Value |
|-----|-------|
| `evidence_count` | len(evidence_map.items) |
| `gaps_count` | len(evidence_map.known_gaps) |
| `letter_char_count` | letter_draft.char_count |
| `validation_passes` | 1 if validation passed, 0 if not |
| `rewrite_count` | state.rewrite_count |

---

## Modified Entities

### MergedConfig (modified)

Three new fields added (all with safe defaults — backward compatible):

| New Field | Type | Default |
|-----------|------|---------|
| `thinking` | ThinkingConfig | `ThinkingConfig()` (thinking disabled) |
| `stage_thinking` | dict[str, ThinkingConfig] | `{}` (empty — no overrides) |
| `tracking` | TrackingConfig | `TrackingConfig()` (tracking disabled) |

**`extra="forbid"` constraint preserved**: Fields are explicitly declared, not dynamic.

---

### StarterTemplate (modified)

Three matching optional fields (same defaults as MergedConfig):

| New Field | Type | Default |
|-----------|------|---------|
| `thinking` | ThinkingConfig | `ThinkingConfig()` |
| `stage_thinking` | dict[str, ThinkingConfig] | `{}` |
| `tracking` | TrackingConfig | `TrackingConfig()` |

These flow through `merge_config()` into `MergedConfig` unchanged (no merge logic needed — they are direct assignments, not multi-source overrides).

---

### WorkflowState (modified)

One new field excluded from serialization:

| New Field | Type | Default | Serialized? |
|-----------|------|---------|-------------|
| `tracker` | `Any \| None` | `None` | No (`exclude=True`) |

The tracker is set by the CLI entry point after `WorkflowState` is constructed. It is accessed by stages as `state.tracker`.

---

### LLMClient Protocol (modified)

The `call()` method signature gains one optional parameter:

```python
def call(
    self,
    messages: list[dict[str, Any]],
    tool_schema: dict[str, Any],
    system: str = "",
    thinking: ThinkingConfig | None = None,  # NEW
) -> dict[str, Any]: ...
```

All existing callers remain valid (keyword argument with default `None`).

---

## Entity Relationships

```
MergedConfig
  ├── thinking: ThinkingConfig          # global default
  ├── stage_thinking: dict[str, ThinkingConfig]  # per-stage overrides
  └── tracking: TrackingConfig          # tracking settings

WorkflowState
  ├── config: MergedConfig
  └── tracker: PipelineTracker | None   # runtime only, not serialized

PipelineTracker
  ├── _config: TrackingConfig
  └── _run_id: str  →  WorkflowState.run_id

AnthropicLLMClient.call(thinking: ThinkingConfig | None)
  └── ThinkingConfig → Anthropic API budget_tokens
```

## Validation Rules

| Entity | Rule | Error |
|--------|------|-------|
| ThinkingConfig | `effort` must be a valid ThinkingEffort value | Pydantic ValidationError before any LLM call |
| TrackingConfig | `tracking_uri` and `experiment_name` must be non-empty strings | Pydantic ValidationError at config load |
| MergedConfig.stage_thinking | Keys must be valid stage names (not enforced at model level; silently ignored for non-LLM stages) | No error — ignorance is by design |
| ThinkingConfig (via API) | budget_tokens must be < max_tokens | Handled in AnthropicLLMClient.call() by setting max_tokens = max(existing, budget+1024) |
