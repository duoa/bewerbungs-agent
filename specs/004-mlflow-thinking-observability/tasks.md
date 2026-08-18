# Tasks: MLflow Observability and Thinking Config

**Input**: Design documents from `/specs/004-mlflow-thinking-observability/`  
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, quickstart.md ✓

**Scope**: 3 config/state files change; 1 new utility file; 5 stage files instrumented; 2 new test files; 1 integration test added.  
**Tests**: Included — constitution mandates TDD (write test → confirm fail → implement → confirm pass).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to user story (US1, US2)

---

## Phase 1: Setup

**Purpose**: Confirm baseline before any changes.

- [x] T001 Run full test suite (`uv run pytest tests/`) and confirm all tests pass as baseline

---

## Phase 2: Foundational — Config Schema & State Extension

**Purpose**: Add `ThinkingConfig`, `TrackingConfig`, and related fields to config and state models. Both US1 and US2 depend on these. No tests are broken — all new fields have safe defaults.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T002 Add `ThinkingEffort(str, Enum)` with values `low`, `medium`, `high`; add `ThinkingConfig(BaseModel)` with fields `enabled: bool = False` and `effort: ThinkingEffort = ThinkingEffort.medium`; add `TrackingConfig(BaseModel)` with fields `enabled: bool = False`, `tracking_uri: str = "mlruns"`, `experiment_name: str = "bewerbungs-agent"` — all in `src/bewerbungs_agent/config/models.py` after the existing enum classes

- [x] T003 Add three explicit fields to `MergedConfig` in `src/bewerbungs_agent/config/models.py` (after `profile_dir`): `thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)`, `stage_thinking: dict[str, ThinkingConfig] = Field(default_factory=dict)`, `tracking: TrackingConfig = Field(default_factory=TrackingConfig)`

- [x] T004 [P] Add matching fields to `StarterTemplate` in `src/bewerbungs_agent/config/models.py` (same three fields, same defaults as MergedConfig); also add `from bewerbungs_agent.config.models import ThinkingConfig, TrackingConfig` as needed (they are in the same file, so just add the field declarations)

- [x] T005 [P] Add `tracker: Any | None = Field(default=None, exclude=True)` to `WorkflowState` in `src/bewerbungs_agent/models/state.py`; ensure `from typing import Any` is imported at the top of the file

- [x] T006 Run `uv run pytest tests/` and confirm all tests still pass after foundational model changes

**Checkpoint**: `ThinkingConfig`, `TrackingConfig`, `MergedConfig.thinking/stage_thinking/tracking`, and `WorkflowState.tracker` exist with safe defaults; all existing tests green.

---

## Phase 3: User Story 1 — Run Tracking via MLflow (Priority: P1) 🎯 MVP

**Goal**: Every pipeline run is optionally logged to a local MLflow tracking store. Each LLM-calling stage records its name, model, thinking settings, prompt hash, and basic output metrics. Tracking failures never abort the pipeline.

**Independent Test**: `uv run pytest tests/unit/test_tracker.py` — all tracker tests pass; mock verifies MLflow is called with correct params; failure test verifies no exception raised when MLflow errors.

### Tests for User Story 1

> **Write these tests FIRST; confirm they FAIL before implementing T009–T016.**

- [x] T007 [US1] Create `tests/unit/test_tracker.py` with the following test class and methods:
  - `TestPipelineTracker.test_start_run_logs_required_params` — create `PipelineTracker(TrackingConfig(enabled=True), run_id="test-run")`, patch `bewerbungs_agent.utils.tracker.mlflow`, call `tracker.start_run(job_title="Engineer")`, assert `mlflow.log_param` was called with `("run_id", "test-run")` and `("model", "claude-sonnet-4-6")`
  - `TestPipelineTracker.test_start_run_silently_ignores_mlflow_error` — patch mlflow.start_run to raise `PermissionError("disk full")`, call `tracker.start_run()`, assert no exception is raised
  - `TestPipelineTracker.test_log_stage_logs_tags_and_params` — call `tracker.log_stage(stage_name="plan_content", model="claude-sonnet-4-6", thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.high), prompt_name="system", prompt_hash="abc123")`, assert `mlflow.set_tag` called with `"stage.plan_content.thinking_enabled"` and `"stage.plan_content.prompt_hash"`
  - `TestPipelineTracker.test_log_outputs_logs_five_metrics` — call `tracker.log_outputs(evidence_count=5, gaps_count=2, letter_char_count=2500, validation_passes=1, rewrite_count=0)`, assert `mlflow.log_metric` was called exactly 5 times with the correct key-value pairs
  - `TestPipelineTracker.test_noop_when_tracking_disabled` — create `PipelineTracker(TrackingConfig(enabled=False), run_id="x")`, call `start_run()`, `log_stage(...)`, `log_outputs(...)`, `end_run()`, assert mlflow was never imported or called (use `sys.modules` check or assert no mlflow attribute on tracker)

- [x] T008 [US1] Run `uv run pytest tests/unit/test_tracker.py` and confirm ALL tests FAIL (module `bewerbungs_agent.utils.tracker` does not exist yet)

### Implementation for User Story 1

- [x] T009 [US1] Create `src/bewerbungs_agent/utils/tracker.py` with `PipelineTracker` class: `__init__(self, config: TrackingConfig, run_id: str)` lazily imports mlflow only when `config.enabled is True` and stores it as `self._mlflow`; if disabled stores `self._mlflow = None`; implement `start_run(job_title: str | None = None)` that calls `self._mlflow.set_tracking_uri(...)`, `.set_experiment(...)`, `.start_run(run_name=self._run_id)`, `.log_params({...})` — all wrapped in `try/except Exception` with `warnings.warn`; when disabled, method is a no-op

- [x] T010 [US1] Add `log_stage(self, stage_name: str, model: str, thinking: ThinkingConfig, prompt_name: str, prompt_hash: str) -> None` to `PipelineTracker` in `src/bewerbungs_agent/utils/tracker.py` — calls `self._mlflow.set_tag(f"stage.{stage_name}.thinking_enabled", str(thinking.enabled).lower())`, `self._mlflow.set_tag(f"stage.{stage_name}.thinking_effort", thinking.effort.value)`, `self._mlflow.set_tag(f"stage.{stage_name}.prompt_name", prompt_name)`, `self._mlflow.set_tag(f"stage.{stage_name}.prompt_hash", prompt_hash)`, `self._mlflow.set_tag(f"stage.{stage_name}.model", model)` — wrapped in `try/except Exception`; no-op when disabled

- [x] T011 [US1] Add `log_outputs(self, evidence_count: int, gaps_count: int, letter_char_count: int, validation_passes: int, rewrite_count: int) -> None` and `end_run(self, status: str = "FINISHED") -> None` to `PipelineTracker` in `src/bewerbungs_agent/utils/tracker.py`; `log_outputs` calls `self._mlflow.log_metric` for each of the 5 params; `end_run` calls `self._mlflow.end_run(status=status)`; both wrapped in `try/except Exception`; both no-op when disabled

- [x] T012 [US1] Add `_compute_prompt_hash(prompt_name: str) -> str` module-level function to `src/bewerbungs_agent/utils/tracker.py` — imports `PROMPT_DIR` from `bewerbungs_agent.utils.prompts`, reads `(PROMPT_DIR / f"{prompt_name}.md").read_bytes()`, returns `hashlib.sha256(content).hexdigest()[:16]`, returns `"unknown"` on `FileNotFoundError`

- [x] T013 [US1] In `src/bewerbungs_agent/stages/extract_requirements.py`, after the `response = client.call(...)` line, add: `if state.tracker:` block calling `state.tracker.log_stage(stage_name="extract_requirements", model=AnthropicLLMClient.MODEL, thinking=state.config.thinking, prompt_name="system", prompt_hash=_compute_prompt_hash("system"))` — add `from bewerbungs_agent.utils.tracker import _compute_prompt_hash` and `from bewerbungs_agent.utils.llm_client import AnthropicLLMClient` imports

- [x] T014 [P] [US1] In `src/bewerbungs_agent/stages/build_evidence_map.py`, add `if state.tracker:` block after `response = client.call(...)` calling `state.tracker.log_stage(stage_name="build_evidence_map", model=AnthropicLLMClient.MODEL, thinking=state.config.thinking, prompt_name="evidence", prompt_hash=_compute_prompt_hash("evidence"))` — add required imports

- [x] T015 [P] [US1] In `src/bewerbungs_agent/stages/plan_content.py`, add `if state.tracker:` block after `response = client.call(...)` calling `state.tracker.log_stage(stage_name="plan_content", model=AnthropicLLMClient.MODEL, thinking=state.config.thinking, prompt_name="system", prompt_hash=_compute_prompt_hash("system"))` — add required imports

- [x] T016 [P] [US1] In `src/bewerbungs_agent/stages/write_letter.py`, add `if state.tracker:` block after `response = client.call(...)` calling `state.tracker.log_stage(stage_name="write_letter", model=AnthropicLLMClient.MODEL, thinking=state.config.thinking, prompt_name="writer", prompt_hash=_compute_prompt_hash("writer"))` — add required imports

- [x] T017 [P] [US1] In `src/bewerbungs_agent/stages/tailor_cv.py`, add `if state.tracker:` block after `response = client.call(...)` calling `state.tracker.log_stage(stage_name="tailor_cv", model=AnthropicLLMClient.MODEL, thinking=state.config.thinking, prompt_name="system", prompt_hash=_compute_prompt_hash("system"))` — add required imports

- [x] T018 [US1] In `src/bewerbungs_agent/cli.py`, in the `run()` command after `initial_state = WorkflowState(config=config, run_id=run_id)`: add `from bewerbungs_agent.utils.tracker import PipelineTracker`; if `config.tracking.enabled`, create `tracker = PipelineTracker(config.tracking, run_id)`, call `tracker.start_run(job_title=None)`, and update `initial_state = initial_state.model_copy(update={"tracker": tracker})`; after the streaming loop completes successfully, call `tracker.log_outputs(evidence_count=len(final_state.evidence_map.items) if final_state.evidence_map else 0, gaps_count=len(final_state.evidence_map.known_gaps) if final_state.evidence_map else 0, letter_char_count=final_state.letter_draft.char_count if final_state.letter_draft else 0, validation_passes=1 if (final_state.letter_validation and final_state.letter_validation.passed) else 0, rewrite_count=final_state.rewrite_count)` and `tracker.end_run()`; wrap in try/except so CLI never fails due to tracking errors

- [x] T019 [US1] Run `uv run pytest tests/unit/test_tracker.py` and confirm all tests pass

**Checkpoint**: `PipelineTracker` is implemented; 5 stages log metadata; CLI initializes and finalizes the tracker; tracking failures are silent.

---

## Phase 4: User Story 2 — Per-Stage Thinking Configuration (Priority: P2)

**Goal**: The LLM client accepts a `ThinkingConfig` parameter per call. Each stage resolves its effective thinking config (per-stage override or global default) and passes it to `client.call()`. Validation fails fast on invalid effort values.

**Independent Test**: `uv run pytest tests/unit/test_config_models.py tests/unit/test_llm_client_thinking.py` — all thinking config and LLM client tests pass; mock inspection confirms thinking params are present/absent in API call kwargs.

### Tests for User Story 2

> **Write these tests FIRST; confirm they FAIL before implementing T022–T028.**

- [x] T020 [US2] Create `tests/unit/test_config_models.py` with the following test class and methods:
  - `TestThinkingConfigResolution.test_stage_override_takes_precedence` — build `MergedConfig(... thinking=ThinkingConfig(enabled=False), stage_thinking={"plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high)})`, assert `resolve_stage_thinking(config, "plan_content").enabled is True` and `.effort == ThinkingEffort.high`
  - `TestThinkingConfigResolution.test_global_default_when_no_override` — same config, assert `resolve_stage_thinking(config, "write_letter").enabled is False` (global default applies)
  - `TestThinkingConfigResolution.test_invalid_effort_raises_validation_error` — assert `pytest.raises(ValidationError)` when constructing `ThinkingConfig(enabled=True, effort="extreme")`
  - `TestThinkingConfigResolution.test_backward_compat_no_thinking_fields` — construct `MergedConfig` with no `thinking`/`stage_thinking`/`tracking` kwargs, assert `config.thinking.enabled is False`, `config.stage_thinking == {}`, `config.tracking.enabled is False`

- [x] T021 [P] [US2] Create `tests/unit/test_llm_client_thinking.py` with:
  - `TestAnthropicLLMClientThinking.test_call_includes_thinking_when_enabled` — patch `anthropic.Anthropic`, construct `AnthropicLLMClient(api_key="test")`, call `client.call(messages=[{"role":"user","content":"x"}], tool_schema={"title":"t","type":"object","properties":{},"required":[]}, thinking=ThinkingConfig(enabled=True, effort=ThinkingEffort.medium))`, retrieve the `kwargs` passed to `messages.create`, assert `kwargs["thinking"] == {"type": "enabled", "budget_tokens": 8000}` and `kwargs["max_tokens"] >= 9024`
  - `TestAnthropicLLMClientThinking.test_call_no_thinking_when_disabled` — same setup with `thinking=ThinkingConfig(enabled=False)`, assert `"thinking"` not in kwargs passed to `messages.create`
  - `TestAnthropicLLMClientThinking.test_call_no_thinking_when_none` — call with no `thinking` kwarg, assert `"thinking"` not in kwargs

- [x] T022 [US2] Run `uv run pytest tests/unit/test_config_models.py tests/unit/test_llm_client_thinking.py` and confirm tests FAIL (`resolve_stage_thinking` not yet defined; `AnthropicLLMClient.call` does not yet accept `thinking` param)

### Implementation for User Story 2

- [x] T023 [US2] Add `resolve_stage_thinking(config: MergedConfig, stage_name: str) -> ThinkingConfig` module-level function to `src/bewerbungs_agent/config/models.py` — returns `config.stage_thinking.get(stage_name, config.thinking)`

- [x] T024 [US2] Update `LLMClient` Protocol in `src/bewerbungs_agent/utils/llm_client.py` to add `thinking: ThinkingConfig | None = None` as a keyword-only parameter to `call()` signature; add `from bewerbungs_agent.config.models import ThinkingConfig` import at top

- [x] T025 [US2] Update `AnthropicLLMClient.call()` in `src/bewerbungs_agent/utils/llm_client.py` to handle the `thinking` parameter: after building `kwargs`, add `if thinking and thinking.enabled:` block that computes `budget = {"low": 1024, "medium": 8000, "high": 16000}[thinking.effort.value]`, sets `kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}`, and sets `kwargs["max_tokens"] = max(kwargs["max_tokens"], budget + 1024)`

- [x] T026 [US2] In `src/bewerbungs_agent/stages/extract_requirements.py`, add `from bewerbungs_agent.config.models import resolve_stage_thinking` import; before `client.call(...)`, add `stage_th = resolve_stage_thinking(state.config, "extract_requirements")`; update `client.call(...)` to pass `thinking=stage_th`; update the `state.tracker.log_stage(...)` call (added in T013) to use `thinking=stage_th` instead of `thinking=state.config.thinking`

- [x] T027 [P] [US2] In `src/bewerbungs_agent/stages/build_evidence_map.py`, add `resolve_stage_thinking` import; resolve `stage_th = resolve_stage_thinking(state.config, "build_evidence_map")`; pass `thinking=stage_th` to `client.call(...)`; update the tracker.log_stage call to use `thinking=stage_th`

- [x] T028 [P] [US2] In `src/bewerbungs_agent/stages/plan_content.py`, add `resolve_stage_thinking` import; resolve `stage_th = resolve_stage_thinking(state.config, "plan_content")`; pass `thinking=stage_th` to `client.call(...)`; update the tracker.log_stage call to use `thinking=stage_th`

- [x] T029 [P] [US2] In `src/bewerbungs_agent/stages/write_letter.py`, add `resolve_stage_thinking` import; resolve `stage_th = resolve_stage_thinking(state.config, "write_letter")`; pass `thinking=stage_th` to `client.call(...)`; update the tracker.log_stage call to use `thinking=stage_th`

- [x] T030 [P] [US2] In `src/bewerbungs_agent/stages/tailor_cv.py`, add `resolve_stage_thinking` import; resolve `stage_th = resolve_stage_thinking(state.config, "tailor_cv")`; pass `thinking=stage_th` to `client.call(...)`; update the tracker.log_stage call to use `thinking=stage_th`

- [x] T031 [US2] Run `uv run pytest tests/unit/test_config_models.py tests/unit/test_llm_client_thinking.py` and confirm all tests pass

**Checkpoint**: `resolve_stage_thinking` resolves per-stage overrides; LLM client passes thinking params to API; all 5 stages use resolved config; existing calls without thinking param remain backward compatible.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Integration test covering the combined feature (thinking enabled for specific stages + tracking), full suite validation, and lint.

- [x] T032 Add integration test `test_full_run_with_stage_thinking` in `tests/integration/test_full_run.py` as a new method on `TestFullPipelineRun`: build a `MergedConfig` with `stage_thinking={"build_evidence_map": ThinkingConfig(enabled=True, effort=ThinkingEffort.medium), "plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high)}` and `thinking=ThinkingConfig(enabled=False)` (global off); patch `get_llm_client` to return a mock that captures `thinking` kwargs; run the full graph; assert that mock calls for `build_evidence_map` and `plan_content` received a `thinking` kwarg with `enabled=True`; assert calls for `extract_requirements`, `write_letter`, and `tailor_cv` received `thinking` with `enabled=False` or no thinking param

- [x] T033 Run full test suite `uv run pytest tests/` and confirm all tests pass (unit + integration)

- [x] T034 [P] Run `uv run ruff check src/ tests/ && uv run mypy src/ --strict` and fix any lint or type errors introduced by the new fields and imports

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS both user stories
- **US1 (Phase 3)**: Depends on Phase 2 (config models and WorkflowState.tracker must exist)
- **US2 (Phase 4)**: Depends on Phase 2 (ThinkingConfig must exist); US2 stages also update the tracker.log_stage calls added in US1 (T026–T030 depend on T013–T017 having been done)
- **Polish (Phase 5)**: Depends on Phase 4 complete

### User Story Dependencies

- **US1** is independently testable: tracker tests (T007–T008), implementation (T009–T018), validation (T019)
- **US2** is independently testable at the config/LLM layer, but T026–T030 (stage updates) extend US1's stage changes

### Within Each Phase

- Test tasks (T007, T020–T021) MUST be written and confirmed to FAIL before their implementation tasks
- T004 and T005 (Foundational) can run in parallel (different files)
- T014–T017 (US1 stage instrumentation) can run in parallel (different files)
- T027–T030 (US2 stage updates) can run in parallel (different files)
- T034 (lint) can run in parallel with T033 (test suite)

---

## Parallel Example: Phase 3 (US1 Stage Instrumentation)

```bash
# These four stage files can be instrumented simultaneously after T013:
Task T014: build_evidence_map.py — add tracker.log_stage call
Task T015: plan_content.py      — add tracker.log_stage call
Task T016: write_letter.py      — add tracker.log_stage call
Task T017: tailor_cv.py         — add tracker.log_stage call
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (baseline green)
2. Complete Phase 2: Foundational (config/state extensions, existing tests green)
3. Complete Phase 3: US1 (tracker utility + stage instrumentation + CLI integration)
4. **STOP and VALIDATE**: `uv run pytest tests/unit/test_tracker.py`
5. Optionally ship — MLflow tracking is live; thinking is globally disabled (default) but config schema is ready

### Incremental Delivery

1. Phase 1 + 2 → baseline safe, schema extended
2. Phase 3 (US1) → tracking works end-to-end → independently testable
3. Phase 4 (US2) → per-stage thinking config active → independently testable
4. Phase 5 (Polish) → full suite green, lint clean

---

## Notes

- All new Pydantic fields have safe defaults — no existing config files need changes (SC-004)
- `tracker: Any = Field(exclude=True)` — excluded from `model_dump()` and LangGraph state diffing; set via `model_copy(update={"tracker": ...})`
- `mlflow` is lazily imported inside `PipelineTracker.__init__` — when tracking disabled, mlflow is never loaded
- Every MLflow call is wrapped in `try/except Exception` with `warnings.warn` — disk errors, permission errors, and API failures are all swallowed
- `ThinkingConfig` defaults to `enabled=False` — existing runs produce identical outputs
- `resolve_stage_thinking(config, stage_name)` returns the global default when a stage is absent from `stage_thinking` — no per-stage config is required
- Stage instrumentation in T013–T017 uses `state.config.thinking` (global); T026–T030 updates these to use `resolve_stage_thinking(state.config, stage_name)` — this is the intended two-step approach: US1 logs metadata, US2 refines to per-stage resolution and passes thinking to the API call
- The LangGraph graph topology (`graph.py`) is NOT changed by any task in this list
