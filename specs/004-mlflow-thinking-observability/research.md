# Research: MLflow Observability and Thinking Config

**Feature**: 004-mlflow-thinking-observability  
**Date**: 2026-04-15

## Topic 1: MLflow Python API — Local File Tracking

### Decision
Use `mlflow` Python SDK with the default local file-based tracking store (`mlruns/` directory). No server setup required. Use `mlflow.start_run()` / `mlflow.end_run()` lifecycle with `mlflow.log_param()`, `mlflow.log_metric()`, and `mlflow.set_tag()` for metadata.

### Key API Facts

```python
import mlflow

# Point to local directory (default is ./mlruns)
mlflow.set_tracking_uri("mlruns")

# Create or reuse experiment
mlflow.set_experiment("bewerbungs-agent")

# Run lifecycle
with mlflow.start_run(run_name="integration-test"):
    mlflow.log_param("model", "claude-sonnet-4-6")
    mlflow.log_param("stage", "extract_requirements")
    mlflow.log_metric("evidence_count", 12)
    mlflow.set_tag("job_title", "Senior Software Engineer")
# run auto-ended by context manager
```

Alternatively: `mlflow.start_run()` / `mlflow.end_run()` without `with` for imperative control across a pipeline run.

### Non-blocking Pattern

```python
try:
    mlflow.log_param(key, value)
except Exception as exc:
    import warnings
    warnings.warn(f"MLflow tracking error (non-fatal): {exc}", stacklevel=2)
```

This pattern must wrap every MLflow call. A disk-full or permissions error MUST NOT abort the pipeline.

### Lazy Import

```python
class PipelineTracker:
    def __init__(self, config, run_id):
        import mlflow as _mlflow  # lazy: only executed when tracking enabled
        self._mlflow = _mlflow
```

This ensures `import mlflow` never executes when tracking is disabled (FR-005).

### Test Strategy

In unit tests, patch `mlflow` at the module level:
```python
with patch("bewerbungs_agent.utils.tracker.mlflow") as mock_mlflow:
    tracker.start_run()
    mock_mlflow.start_run.assert_called_once()
```

Alternatively, use `mlflow.set_tracking_uri("file:///tmp/mlruns-test")` in integration tests to write to a temp directory and assert run records exist.

### Rationale
Local file store requires zero infrastructure. MLflow ≥ 2.12 is stable and well-maintained. The `mlflow.MlflowClient` API can query runs programmatically for test assertions. The `mlruns/` directory should be added to `.gitignore`.

### Alternatives Considered
- **Weights & Biases**: More features but requires account/API key; too heavy for v1.
- **Custom JSON log file**: Simpler but no UI; makes comparison harder.
- **OpenTelemetry**: Better for distributed tracing; overkill for single-process CLI.

---

## Topic 2: Anthropic Extended Thinking API

### Decision
Use `thinking` parameter in `anthropic.messages.create()` with `budget_tokens` mapped from named effort levels: `low=1024`, `medium=8000`, `high=16000`. Thinking is incompatible with streaming; the existing non-streaming tool-use pattern is compatible.

### Key API Facts

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=9000,  # must be > budget_tokens
    thinking={
        "type": "enabled",
        "budget_tokens": 8000  # medium effort
    },
    tools=[...],
    tool_choice={"type": "tool", "name": tool_name},
    messages=[...],
)
```

The response content will include a `ThinkingBlock` before the `ToolUseBlock`. The existing parsing loop (`for block in response.content: if isinstance(block, ToolUseBlock)`) is unaffected — thinking blocks are simply skipped.

### Effort Level Mapping

| Named Level | budget_tokens | Use Case |
|-------------|--------------|----------|
| low | 1024 | Fast stages where reasoning adds little value (e.g., extract_requirements) |
| medium | 8000 | Complex planning stages (e.g., plan_content) |
| high | 16000 | High-stakes generation (e.g., write_letter with complex plan) |

`max_tokens` must be at least `budget_tokens + 1024` to leave room for the actual response. The implementation sets `max_tokens = max(existing_max, budget_tokens + 1024)`.

### Tool Use Compatibility

Extended thinking is compatible with tool use (forced via `tool_choice`). The model reasons via thinking blocks, then produces the tool-use block. No changes needed to tool schema or response parsing.

### Backward Compatibility

When `thinking` param is absent or `None`, the API behaves identically to today. All existing stage calls pass no `thinking` arg and remain unaffected.

### Rationale
Named levels decouple the config schema from raw API values, allowing effort tuning without config changes. The `budget_tokens` values are chosen conservatively: `low` covers most structured extraction tasks; `medium` handles multi-step planning; `high` is reserved for prose generation where quality matters most.

### Alternatives Considered
- **Raw `budget_tokens` in config**: Directly exposes API internals; breaks abstraction.
- **Boolean `extended_thinking` only**: Loses effort control, can't optimize cost.
- **Per-model thinking configuration**: Over-engineering for v1; model is fixed as `claude-sonnet-4-6`.

---

## Topic 3: Pydantic `exclude=True` for Non-Serialized State Fields

### Decision
Use `Field(default=None, exclude=True)` on the `tracker` field in `WorkflowState`. This field holds a `PipelineTracker` instance at runtime but is excluded from Pydantic serialization (`.model_dump()`, `.model_dump_json()`) and from LangGraph's state diffing/merging.

### Key Facts

```python
from pydantic import BaseModel, Field
from typing import Any

class WorkflowState(BaseModel):
    # ... existing fields ...
    tracker: Any | None = Field(default=None, exclude=True)
```

- `exclude=True` on a field removes it from `.model_dump()` output
- LangGraph uses Pydantic's serialization for state checkpointing; excluded fields are not checkpointed
- The type annotation `Any` avoids importing `PipelineTracker` into `state.py`, preventing circular imports
- Setting `tracker` on a state copy: `state.model_copy(update={"tracker": tracker_instance})`

### Test Implications
- `WorkflowState.model_dump()` must NOT contain a `"tracker"` key — assert in existing model tests
- The tracker instance survives through stage calls because LangGraph passes the full state object (not a re-parsed copy) within a single invocation

### Rationale
This is the standard Pydantic pattern for carrying non-serializable runtime objects alongside serializable config. It is used in other frameworks (e.g., SQLAlchemy sessions in request state). The `exclude=True` approach is cleaner than `PrivateAttr` because it allows the field to be set via `model_copy(update=...)` or constructor.

### Alternatives Considered
- **`PrivateAttr`**: More idiomatic for truly private fields, but cannot be set via constructor or `model_copy(update=...)` — makes test setup harder.
- **Thread-local / global tracker**: Creates hidden coupling between stages and breaks testability.
- **Pass tracker explicitly to each stage function**: Would require changing the LangGraph node signature, which conflicts with the graph-topology-unchanged constraint.

---

## Topic 4: SHA-256 Prompt Version Hashing

### Decision
Compute SHA-256 of the prompt file's raw bytes at call time, return a 16-character hex prefix as the version hash. Store hashes in MLflow as parameters (one per stage).

### Implementation

```python
import hashlib
from pathlib import Path

def _compute_prompt_hash(prompt_name: str) -> str:
    """16-char SHA-256 prefix of prompt file bytes at call time."""
    from bewerbungs_agent.utils.prompts import PROMPT_DIR
    path = PROMPT_DIR / f"{prompt_name}.md"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return "unknown"
```

A 16-character hex string provides 64 bits of collision resistance — sufficient for detecting prompt file changes across runs. The full 64-character SHA-256 is available if needed by changing the slice.

### Rationale
Hashing the file content (not a version number) means changes are detected automatically without maintaining a version counter. The `[:16]` prefix keeps MLflow parameter values short and readable in the UI.

### Alternatives Considered
- **Full SHA-256**: Correct but noisy in the UI; 16 chars is a practical compromise.
- **File modification time**: Fragile — git checkout changes mtime without changing content.
- **Git blame / commit hash for prompt file**: Adds a git dependency and fails in dirty working trees.
