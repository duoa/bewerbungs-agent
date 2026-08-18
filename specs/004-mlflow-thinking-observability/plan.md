# Implementation Plan: MLflow Observability and Thinking Config

**Branch**: `004-mlflow-thinking-observability` | **Date**: 2026-04-15 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/004-mlflow-thinking-observability/spec.md`

## Summary

Add lightweight, opt-in MLflow run tracking and per-stage Claude thinking configuration to the existing LangGraph pipeline. MLflow tracking wraps each run's lifecycle with non-blocking metadata logging (stage names, model, prompt hashes, output metrics). Thinking configuration adds a `ThinkingConfig` Pydantic model for global defaults and per-stage overrides, which flows through `MergedConfig` into each LLM call via an extended `LLMClient.call()` signature. The LangGraph graph topology is unchanged; changes are confined to: `config/models.py` (new config models), `utils/llm_client.py` (extended call signature), a new `utils/tracker.py` module, and thin instrumentation in each of the 6 LLM-calling stage files.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: mlflow ≥ 2.12, anthropic SDK ≥ 0.25, pydantic v2, langgraph 0.2+  
**Storage**: Local file-based MLflow tracking store (`mlruns/` directory, default)  
**Testing**: pytest, unittest.mock; MLflow calls are mocked in unit tests  
**Target Platform**: macOS/Linux CLI  
**Project Type**: CLI application  
**Performance Goals**: Tracking overhead <100ms per run; no pipeline latency increase visible to user  
**Constraints**: Tracking MUST be non-blocking; single exception handler around all MLflow calls; `extra="forbid"` on `MergedConfig` requires explicit field declarations  
**Scale/Scope**: Single-user local runs; no concurrency requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Factual Integrity | PASS | Tracking only logs metadata; no LLM content generation is altered |
| II. Approved Sources Only | PASS | Tracker reads only pipeline state and config; no new source types |
| III. Structured-Before-Generative | PASS | No pipeline stage order changes; tracking wraps existing stages |
| IV. Separation of Concerns | PASS | Tracker is a standalone utility; stage logic untouched |
| V. Deterministic Interfaces & Typed State | PASS | New ThinkingConfig / TrackingConfig are explicit Pydantic models; MergedConfig extra="forbid" respected by adding fields explicitly |
| VI. Test Coverage | PASS | Tracker + LLM client extensions require unit tests before implementation (TDD) |

**Post-design re-check**: All principles remain satisfied. No violations identified.

## Project Structure

### Documentation (this feature)

```text
specs/004-mlflow-thinking-observability/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code Changes

```text
src/bewerbungs_agent/
├── config/
│   └── models.py                    # MODIFIED: add ThinkingConfig, TrackingConfig, fields to MergedConfig
├── utils/
│   ├── llm_client.py                # MODIFIED: extend call() with thinking params; update Protocol
│   └── tracker.py                   # NEW: MLflow run tracker utility
└── stages/
    ├── extract_requirements.py      # MODIFIED: pass thinking config + tracking call
    ├── select_cv_variant.py         # MODIFIED: pass thinking config + tracking call
    ├── build_evidence_map.py        # MODIFIED: pass thinking config + tracking call
    ├── plan_content.py              # MODIFIED: pass thinking config + tracking call
    ├── write_letter.py              # MODIFIED: pass thinking config + tracking call
    └── tailor_cv.py                 # MODIFIED: pass thinking config + tracking call

tests/
├── unit/
│   ├── test_tracker.py              # NEW: tracker unit tests
│   ├── test_llm_client_thinking.py  # NEW: LLM client thinking config tests
│   └── test_config_models.py        # NEW: ThinkingConfig + TrackingConfig validation tests
└── integration/
    └── test_full_run.py             # MODIFIED: verify backward compatibility (no tracking config)
```

## Architecture

### ThinkingConfig & TrackingConfig (config/models.py)

Two new Pydantic models are added and referenced as optional fields on `MergedConfig`:

```python
class ThinkingEffort(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

class ThinkingConfig(BaseModel):
    enabled: bool = False
    effort: ThinkingEffort = ThinkingEffort.medium

class TrackingConfig(BaseModel):
    enabled: bool = False
    tracking_uri: str = "mlruns"          # relative = local file store
    experiment_name: str = "bewerbungs-agent"
```

Added to `MergedConfig` (`extra="forbid"` respected by declaring explicitly):

```python
thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
stage_thinking: dict[str, ThinkingConfig] = Field(default_factory=dict)
tracking: TrackingConfig = Field(default_factory=TrackingConfig)
```

`StarterTemplate` gets matching optional fields with same defaults.

### LLM Client Extension (utils/llm_client.py)

The `LLMClient` Protocol and `AnthropicLLMClient.call()` gain an optional `thinking` parameter:

```python
def call(
    self,
    messages: list[dict],
    tool_schema: dict,
    system: str = "",
    thinking: ThinkingConfig | None = None,
) -> dict:
    ...
    if thinking and thinking.enabled:
        # Map effort level to Anthropic budget_tokens
        budget = {"low": 1024, "medium": 8000, "high": 16000}[thinking.effort]
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs["max_tokens"] = max(kwargs["max_tokens"], budget + 1024)
```

The Protocol is updated to match. Existing callers pass no `thinking` arg — backward compatible.

### Tracker Utility (utils/tracker.py)

A non-blocking wrapper around MLflow. Every method wraps its body in `try/except Exception` and emits a `warnings.warn` on failure — never raises:

```python
class PipelineTracker:
    def __init__(self, config: TrackingConfig, run_id: str): ...
    def start_run(self, job_title: str | None = None) -> None: ...
    def log_stage(self, stage_name: str, model: str,
                  thinking: ThinkingConfig, prompt_name: str,
                  prompt_hash: str, **extra) -> None: ...
    def log_outputs(self, evidence_count: int, gaps_count: int,
                    letter_char_count: int, validation_passes: int,
                    rewrite_count: int) -> None: ...
    def end_run(self, status: str = "FINISHED") -> None: ...
```

`mlflow` is imported lazily inside `PipelineTracker.__init__` so it is never imported when tracking is disabled (FR-005).

### Stage Instrumentation Pattern

Each of the 6 LLM-calling stages gets two small additions:

1. **Thinking config lookup** before `client.call()`:
   ```python
   stage_thinking = state.config.stage_thinking.get(
       "extract_requirements", state.config.thinking
   )
   response = client.call(messages, SCHEMA, thinking=stage_thinking)
   ```

2. **Tracker call** after `client.call()`:
   ```python
   if state.tracker:
       state.tracker.log_stage(
           stage_name="extract_requirements",
           model=AnthropicLLMClient.MODEL,
           thinking=stage_thinking,
           prompt_name="system",
           prompt_hash=_compute_prompt_hash("system"),
       )
   ```

### WorkflowState Extension

One new field excluded from LangGraph serialization:

```python
tracker: Any | None = Field(default=None, exclude=True)
```

Using `Any` avoids importing `PipelineTracker` into `state.py`. `exclude=True` means LangGraph never diffs/merges this field. The tracker is initialized in the CLI entry point when tracking is enabled.

### Prompt Hash Computation

```python
def _compute_prompt_hash(prompt_name: str) -> str:
    """SHA-256 (16-char prefix) of prompt file content at call time."""
    path = PROMPT_DIR / f"{prompt_name}.md"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
```

## Complexity Tracking

| Decision | Justification |
|----------|--------------|
| `tracker: Any` in WorkflowState | Avoids circular import between state.py and tracker.py; exclude=True keeps LangGraph serialization clean |
| 16-char prompt hash prefix | Full SHA-256 is 64 chars; 16 chars is sufficient for run comparison while keeping MLflow UI readable |
| Named effort levels mapped to budget_tokens | Decouples config from Anthropic API specifics; easy to tune without config schema changes |
| No tracking for load_job, load_profile | These stages make no LLM calls; tracking non-LLM I/O adds complexity with no debuggability benefit (FR-003) |
| Lazy mlflow import inside tracker __init__ | Keeps mlflow out of the main module graph; when tracking disabled, mlflow is never imported |
| ThinkingConfig default thinking=False | Ensures backward compatibility (SC-004); existing runs produce identical outputs |
