# Tasks: Langfuse Observability for the Application Pipeline

**Input**: Design documents from `/specs/006-langfuse-observability/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. FR-022 through FR-025 in spec.md explicitly mandate four automated test scenarios, and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task begins.

**Organization**: Tasks grouped by user story. Each story is independently testable via mocked Langfuse client.

---

## Phase 1: Setup

**Purpose**: Add the one new dependency. No project-structure changes (existing single-project layout reused per plan.md).

- [X] T001 Add `langfuse>=2.0` to `dependencies` array in `pyproject.toml` (alphabetical placement after `langgraph>=0.2`); run `uv sync` to install

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config models, state-carrier field, and merge-propagation that ALL three user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Write failing tests for `LangfuseConfig` and `ObservabilityConfig` parsing, defaults, and `merge_config()` propagation in `tests/unit/test_config_models.py` (add 4 test methods: defaults, full-payload-flag combinations, mask_pii default, observability field surviving merge_config round-trip with `extra="forbid"`)
- [X] T003 Add `LangfuseConfig` and `ObservabilityConfig` Pydantic models to `src/bewerbungs_agent/config/models.py` and add `observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)` field to both `StarterTemplate` and `MergedConfig` — confirm T002 tests now pass
- [X] T004 Add `"observability": template.observability` to the explicit `base` dict in `src/bewerbungs_agent/utils/merge.py` (critical: `MergedConfig` uses `extra="forbid"` and does not auto-propagate; this is the same gotcha documented in ENGINEERING.md §15)
- [X] T005 Add `observability: Any | None = Field(default=None, exclude=True)` field to `WorkflowState` in `src/bewerbungs_agent/models/state.py` (placement: directly after the existing `tracker: Any | None` field; `Any` avoids circular import; `exclude=True` keeps SDK object out of JSON serialisation)

**Checkpoint**: Config models validate; `merge_config` propagates `observability`; `WorkflowState` carries the observability field; T002 tests pass.

---

## Phase 3: User Story 1 — One CLI Run, One Traceable Story (Priority: P1) 🎯 MVP

**Goal**: A single CLI run produces one Langfuse trace with one nested span per pipeline stage. When credentials or config disable observability, the run completes normally with byte-identical outputs and no error noise.

**Independent Test**: Run `jobagent run` with a fixture job and a mocked Langfuse client; assert one trace recorded with the expected stage span names. Separately, run with no credentials; assert exit code 0, no exception raised, no Langfuse network call attempted.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T013

- [X] T006 [P] [US1] Write failing test `test_build_observability_returns_noop_when_creds_missing` in `tests/unit/test_observability.py` — pass empty env mapping, assert returned object is `NoOpObservability`
- [X] T007 [US1] Write failing test `test_build_observability_returns_noop_when_config_disabled` in `tests/unit/test_observability.py` — pass `LangfuseConfig(enabled=False)` with valid env vars, assert returned object is `NoOpObservability`
- [X] T008 [US1] Write failing test `test_build_observability_returns_langfuse_when_enabled` in `tests/unit/test_observability.py` — pass `LangfuseConfig(enabled=True)` and full env vars, assert returned object is `LangfuseObservability`; mock the `langfuse.Langfuse` constructor so no real network call happens
- [X] T009 [US1] Write failing test `test_noop_observability_methods_are_zero_cost` in `tests/unit/test_observability.py` — call `start_trace`, `stage_span(...).__enter__().__exit__(None,None,None)`, `flush`, `close` and assert all return immediately, no allocations beyond the span context object
- [X] T010 [US1] Write failing test `test_wrap_stage_invokes_underlying_stage_with_unchanged_state_and_returns_unchanged_dict` in `tests/unit/test_observability.py` — wrap a fixture stage_fn that returns a known dict; assert returned dict equals fixture dict and state was not mutated
- [X] T011 [US1] Write failing test `test_wrap_stage_opens_and_closes_span` in `tests/unit/test_observability.py` — use a `MockObservability` recording `stage_span` calls; assert one span opened with the expected stage_name and closed before the wrapped fn returns
- [X] T012 [US1] Write failing test `test_wrap_stage_captures_exception_and_reraises` in `tests/unit/test_observability.py` — wrap a stage that raises `RuntimeError`; assert `pytest.raises(RuntimeError)`, assert `set_error` was called on the mock span with the exception
- [X] T013 [P] [US1] Write failing test `test_full_pipeline_succeeds_with_no_langfuse_creds` in `tests/integration/test_full_run.py` — run full pipeline with empty Langfuse env vars (creds missing); assert no exception, all expected output files written, no warning about credentials logged at WARN level (FR-022)
- [X] T014 [US1] Write failing test `test_full_pipeline_outputs_byte_identical_enabled_vs_disabled` in `tests/integration/test_full_run.py` — run pipeline twice with the same deterministic mock LLM client: once with `observability.langfuse.enabled=False`, once with `enabled=True` and mocked Langfuse client; use `filecmp.cmp(..., shallow=False)` on `letter.md` and every `artifacts/*.json` (FR-013, FR-025, SC-004)

### Implementation for User Story 1

- [X] T015 [US1] Create `src/bewerbungs_agent/utils/observability.py` with: `SpanStatus` enum, `TokenUsage` Pydantic model, `StageSpanRecord` Pydantic model, `Observability` Protocol, `StageSpan` Protocol — types per data-model.md §2 and contracts/observability_protocol.md §1
- [X] T016 [US1] Implement `NoOpObservability` and `NoOpStageSpan` classes in `src/bewerbungs_agent/utils/observability.py` — every method an immediate return; `stage_span` returns a context manager whose mutators are pass; do NOT import `langfuse`
- [X] T017 [US1] Implement `LangfuseObservability` skeleton in `src/bewerbungs_agent/utils/observability.py` — `start_trace` calls `client.trace(...)`, `stage_span` opens nested `client.trace.span(...)`, `flush(timeout)` calls `client.flush(timeout=timeout)` with thread-bounded fallback if SDK does not accept `timeout=`, `close` calls `client.shutdown()`; implement `_healthy` flag flip on any SDK exception with single warning per process (contracts §4)
- [X] T018 [US1] Implement `build_observability(config, env=None)` factory in `src/bewerbungs_agent/utils/observability.py` — decision matrix per contracts §2; default `env=os.environ`; emit single debug log line on no-op fallback; never raise
- [X] T019 [US1] Implement `_wrap_stage(stage_fn, stage_name, *, prompt_name=None)` helper in `src/bewerbungs_agent/utils/observability.py` — reads `state.observability` (handles None for tests not exercising the wrapper), opens span, calls stage_fn inside the span context, sets `status="success"` or calls `span.set_error(exc)` on exception and re-raises (must not swallow; LangGraph control flow depends on it)
- [X] T020 [US1] Wire `_wrap_stage` into every `graph.add_node(...)` call in `src/bewerbungs_agent/graph/workflow.py` — wrap all 11 nodes: `load_job`, `extract_requirements`, `load_profile`, `select_cv_variant`, `build_evidence_map`, `plan_content`, `write_letter`, `tailor_cv`, `hiring_review`, `targeted_rewrite`, `validate_outputs`, `rewrite_if_needed`; pass `prompt_name` for the eight LLM stages, leave `prompt_name=None` for the three I/O-only stages; do NOT add a synthetic parent span around `write_letter`/`tailor_cv` (FR-016a)
- [X] T021 [US1] Wire observability lifecycle into `src/bewerbungs_agent/cli.py` `run` command — after existing `tracker.start_run(...)` call: `observability = build_observability(merged_config.observability)`, `observability.start_trace(run_id, tags={"template_id": ..., "cv_variant": ...})`, attach to `WorkflowState` via constructor; wrap the existing `graph.invoke(...)` + `_write_artifacts(...)` in a `try / finally` that calls `observability.flush(timeout_seconds=3.0)` then `observability.close()` then closes the MLflow run; verify the `finally` covers `KeyboardInterrupt` (Python guarantee)
- [X] T022 [US1] Confirm all tests in `tests/unit/test_observability.py` (T006–T012) and `tests/integration/test_full_run.py` (T013, T014) pass

**Checkpoint**: One trace per CLI run with one span per stage; safe no-op when credentials missing or config disabled; pipeline outputs byte-identical between enabled and disabled modes; CLI never hangs more than 3 s on flush.

---

## Phase 4: User Story 2 — Rich Stage Metadata for Debugging (Priority: P2)

**Goal**: Each stage span carries the metadata an operator needs to debug: stage_name, prompt_name + prompt_hash, model name, input/output summary, latency, status, error type/message/trace, token usage, artifact paths.

**Independent Test**: Run a single LLM stage end-to-end with a `MockObservability` that records `set_*` calls; assert every required setter was called with non-null values for fields the stage can produce.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T028

- [X] T023 [P] [US2] Write failing tests for summary functions in `tests/unit/test_summaries.py` — one test per state field documented in research.md §R6 (10 functions: `summarise_job_context`, `summarise_requirements`, `summarise_knowledge`, `summarise_selected_cv`, `summarise_evidence_map`, `summarise_content_plan`, `summarise_letter_draft`, `summarise_cv_tailoring_plan`, `summarise_letter_review`, `summarise_validation_report`); each test asserts the output dict contains the documented fields and contains no free-text body content
- [X] T024 [US2] Write failing test `test_wrap_stage_attaches_prompt_name_and_hash` in `tests/unit/test_observability.py` — wrap a stage with `prompt_name="planner"`; assert `span.set_prompt("planner", <16-char-hex>)` called; hash MUST come from existing `_compute_prompt_hash` in `utils/tracker.py`
- [X] T025 [US2] Write failing test `test_wrap_stage_attaches_model_name_for_llm_stages` in `tests/unit/test_observability.py` — assert `span.set_model("claude-sonnet-4-6")` called for LLM stages, NOT called for I/O stages
- [X] T026 [US2] Write failing test `test_llm_span_records_token_usage_when_response_includes_usage` in `tests/unit/test_observability.py` — install a mocked LLM client whose response carries usage; run one stage wrapped via `_wrap_stage`; assert `span.set_token_usage(TokenUsage(input_tokens=..., output_tokens=..., total_tokens=...))` called
- [X] T027 [US2] Write failing test `test_non_llm_span_omits_llm_only_fields` in `tests/unit/test_observability.py` — wrap a non-LLM stage (e.g., `load_job`); assert `set_model`, `set_token_usage`, `set_prompt` are NOT called; assert span still closed with `status=success`

### Implementation for User Story 2

- [X] T028 [US2] Create `src/bewerbungs_agent/utils/summaries.py` with the 10 summary functions from research.md §R6, plus a top-level dispatcher `summarise_partial_update(stage_name: str, update: dict) -> dict` that maps each stage's known output-key to the right summary function
- [X] T029 [US2] Extend `_wrap_stage` in `src/bewerbungs_agent/utils/observability.py` — accept and propagate `prompt_name`; on span enter call `span.set_prompt(prompt_name, _compute_prompt_hash(prompt_name))`; compute input summary via `summarise_*` on pre-call state; on success exit compute output summary via `summarise_partial_update(stage_name, update)` and call `span.set_output(summary)`
- [X] T030 [US2] Implement `StageSpan` mutator methods (`set_prompt`, `set_model`, `set_input`, `set_output`, `set_token_usage`, `set_artifact_path`, `set_error`) on `LangfuseStageSpan` in `src/bewerbungs_agent/utils/observability.py` — each method wraps SDK call in try/except, single warning per span on failure
- [X] T031 [US2] Surface LLM token usage to the active span via a module-level `contextvars.ContextVar` named `_active_span` in `src/bewerbungs_agent/utils/observability.py` — `_wrap_stage` sets/resets it around the wrapped call; modify `AnthropicLLMClient.call` in `src/bewerbungs_agent/utils/llm_client.py` to read `_active_span.get(None)` after the API call and, if non-None, write `TokenUsage` extracted from `response.usage`; the LLM client gains a dependency on `_active_span` only — not on the full `Observability` Protocol — keeping coupling minimal
- [X] T032 [US2] Wire artifact-path recording in `src/bewerbungs_agent/cli.py` `_write_artifacts(...)` — each per-stage artifact writer returns the relative path written; collect these and call `observability.attach_artifact_paths_to_last_stage(stage_name, paths)` (add a small helper to `Observability` Protocol and both implementations: NoOp no-ops, Langfuse looks up the recorded span by `stage_name` and sets the field)
- [X] T033 [US2] Confirm all tests in `tests/unit/test_observability.py` (T024–T027) and `tests/unit/test_summaries.py` (T023) pass

**Checkpoint**: Every span shows operator-actionable metadata: prompt diff detection via hash, model identification, token spend, artifact navigation.

---

## Phase 5: User Story 3 — Privacy-Safe Defaults, Opt-In Raw Payloads (Priority: P3)

**Goal**: By default spans carry summaries only — no profile/CV/job/letter body. Opt-in raw mode includes prose but still strips API keys (always) and PII patterns (when `mask_pii=True`, default).

**Independent Test**: Run pipeline with a fixture profile containing distinctive strings (unique email, project name, fake API key in env var); inspect every recorded span payload; assert distinctive strings absent in default mode; assert API-key value absent in raw mode regardless of `mask_pii`.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T039

- [X] T034 [P] [US3] Write failing test `test_redact_strips_env_var_secrets` in `tests/unit/test_redaction.py` — set env vars `FAKE_API_KEY=secret123`, `FAKE_TOKEN=tok456`, `FAKE_SECRET=sec789`, `FAKE_PASSWORD=pw000`; call `redact("user said secret123 then tok456 then sec789 then pw000", mode="summary", mask_pii=False)`; assert none of the four values appear, each replaced with `<REDACTED:FAKE_*>`
- [X] T035 [P] [US3] Write failing test `test_redact_strips_pii_patterns_in_full_mode` in `tests/unit/test_redaction.py` — feed string containing email `alice@example.com`, phone `+49 30 12345678`, IBAN `DE89370400440532013000`, postal `10115 Berlin`; call `redact(value, mode="full", mask_pii=True)`; assert all four patterns absent, replaced with `<EMAIL>`, `<PHONE>`, `<IBAN>`, `<POSTAL>`
- [X] T036 [P] [US3] Write failing test `test_redact_summary_mode_does_not_apply_pii_pass` in `tests/unit/test_redaction.py` — summary mode passes only env-var pass; assert pure prose containing email is unchanged (summary fields don't contain prose by construction; this test pins the contract that pii pass is full-mode only)
- [X] T037 [P] [US3] Write failing test `test_redact_full_mode_with_mask_pii_false_still_strips_secrets` in `tests/unit/test_redaction.py` — set `FAKE_API_KEY=secret999`; call `redact("contains secret999 and alice@example.com", mode="full", mask_pii=False)`; assert `secret999` absent, `alice@example.com` present (FR-017 always-on; PII opt-out only)
- [X] T038 [US3] Write failing test `test_wrap_stage_uses_summary_payload_by_default` in `tests/unit/test_observability.py` — with `log_full_inputs=False` and `log_full_outputs=False`, assert `span.set_input` and `span.set_output` receive summary dicts only (no raw state objects)
- [X] T039 [US3] Write failing test `test_wrap_stage_uses_full_payload_when_flag_set` in `tests/unit/test_observability.py` — with `log_full_inputs=True`, assert `span.set_input(payload, full=True)` called with the full pre-call state; with `log_full_outputs=True`, assert `span.set_output(payload, full=True)` called with the full update dict; redaction MUST still apply

### Implementation for User Story 3

- [X] T040 [US3] Create `src/bewerbungs_agent/utils/redaction.py` with `redact(value: Any, *, mode: Literal["summary","full"], mask_pii: bool) -> Any` plus internal helpers `_redact_env_vars(s)`, `_redact_pii(s)`, `_snapshot_secret_env_values()`; snapshot is taken once at module import for env vars whose names end in `_API_KEY`/`_TOKEN`/`_SECRET`/`_PASSWORD`; structural pass replaces literal value matches first, regex pass second
- [X] T041 [US3] Wire redaction into `LangfuseStageSpan` setters in `src/bewerbungs_agent/utils/observability.py` — every payload field flows through `redact(...)` before being passed to the SDK; mode and mask_pii come from the captured `LangfuseConfig`
- [X] T042 [US3] Extend `_wrap_stage` in `src/bewerbungs_agent/utils/observability.py` to consult `config.observability.langfuse.log_full_inputs` and `log_full_outputs` — when False (default) call `summarise_*` on state pre-call and `summarise_partial_update` on the post-call dict; when True pass the full state slice / full dict and let the redaction pass in `set_input`/`set_output` strip secrets and PII
- [X] T043 [US3] Confirm all tests in `tests/unit/test_redaction.py` (T034–T037) and the two new tests in `tests/unit/test_observability.py` (T038, T039) pass

**Checkpoint**: Privacy-safe defaults verified; opt-in raw mode works; credential redaction unconditional; PII regex opt-out via `mask_pii=False` does not bypass secret redaction.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: MLflow cross-link, CLI output line, exception-capture integration test, docs, and final test-suite sweep.

- [X] T044 [P] Implement `log_langfuse_link(trace_id: str | None, trace_url: str | None) -> None` method in `src/bewerbungs_agent/utils/tracker.py` — no-op when `self._mlflow is None` or either arg is None; otherwise `mlflow.set_tag("langfuse_trace_id", trace_id)` and `mlflow.set_tag("langfuse_trace_url", trace_url)`; wrap in the existing try/except pattern (FR-021)
- [X] T045 Wire `tracker.log_langfuse_link(observability.trace_id(), observability.trace_url())` call into `src/bewerbungs_agent/cli.py` immediately after `observability.start_trace(...)` succeeds — placement inside the `try` block, before `graph.invoke(...)`
- [X] T046 Add CLI output line in `src/bewerbungs_agent/cli.py` after a successful run start — when `observability.trace_url()` returns a non-None URL, `typer.echo(f"  langfuse trace: {url}")` (consistent with the existing `letter_review` status-line style from feature 005)
- [X] T047 Write failing integration test `test_full_pipeline_captures_stage_exception_on_span` in `tests/integration/test_full_run.py` — inject a deliberate `RuntimeError` in one mock stage; run pipeline with mocked Langfuse client; assert pipeline exits non-zero, assert the recorded span for the offending stage has `status="error"` and contains the exception type and message (FR-008, FR-024)
- [X] T048 [P] Update `ENGINEERING.md` with a new Section 17 "Langfuse Observability" — cover: what the wrapper does, env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`), config block (`observability.langfuse.*`), summary-vs-full payload modes, MLflow cross-link tags, the 3-second flush bound, troubleshooting; mirror the structure of Section 15 (MLflow) and Section 16 (Hiring Review)
- [X] T049 Confirm full test suite passes: `.venv/bin/pytest tests/ -v`
- [X] T050 Confirm static checks pass: `.venv/bin/ruff check src/ tests/` and `.venv/bin/mypy src/`
- [X] T051 Run quickstart.md §10 smoke test manually (or document why it's deferred) — confirm enabled-vs-disabled runs produce byte-identical artifacts on a real fixture job

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Phase 1. **BLOCKS all user stories.**
- **User Story 1 (Phase 3)**: Depends on Phase 2 completion. Independently testable via mocked Langfuse client and no-creds fallback.
- **User Story 2 (Phase 4)**: Depends on Phase 2 + US1 (US1 builds the wrapper skeleton US2 extends). US2 tests can be written in parallel with US1 implementation but cannot pass until US1 lands.
- **User Story 3 (Phase 5)**: Depends on Phase 2 + US1 (US3 hooks into the wrapper's setters). US3 redaction-module tests (T034–T037) are independent of US1 and can be written in parallel with Phase 2.
- **Polish (Phase 6)**: Depends on US1 + US2 + US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation begins (Constitution Principle VI; reinforced in spec FR-022..FR-025).
- Within US1: T015 (types) → T016 (NoOp) → T017 (Langfuse skeleton) → T018 (factory) → T019 (`_wrap_stage`) → T020 (graph wiring) → T021 (CLI wiring) → T022 (verify).
- Within US2: T028 (summaries) → T029 (wrapper extension) → T030 (StageSpan mutators) → T031 (LLM client integration) → T032 (artifact paths) → T033 (verify).
- Within US3: T040 (redaction module) → T041 (wrapper wiring) → T042 (full-payload flag wiring) → T043 (verify).

---

## Parallel Opportunities

```bash
# Phase 1 setup is a single task; nothing to parallelise.

# Phase 2 foundational — tests can be written in parallel with reading the spec, but
# implementation tasks (T003, T004, T005) touch different files in dependency order:
Task T002: Write config-model tests in tests/unit/test_config_models.py
# (then T003, T004, T005 sequentially — each depends on the previous)

# Phase 3 US1 — independent failing tests can be written in parallel:
Task T006: test_build_observability_returns_noop_when_creds_missing
Task T013: test_full_pipeline_succeeds_with_no_langfuse_creds  # [P] — different file

# Phase 4 US2 summary-function tests can be written in parallel with US1 implementation
# (different file: tests/unit/test_summaries.py):
Task T023: Write summary-function tests in tests/unit/test_summaries.py  # [P]

# Phase 5 US3 redaction-module tests are independent of US1/US2 implementation:
Task T034: test_redact_strips_env_var_secrets       # [P] — different file
Task T035: test_redact_strips_pii_patterns_in_full_mode  # [P] — same file as T034, write sequentially
Task T036: test_redact_summary_mode_does_not_apply_pii_pass  # [P] — same file, sequential
Task T037: test_redact_full_mode_with_mask_pii_false_still_strips_secrets  # same file

# Phase 6 polish — log_langfuse_link and ENGINEERING.md update are in different files:
Task T044: Implement log_langfuse_link in src/bewerbungs_agent/utils/tracker.py  # [P]
Task T048: Update ENGINEERING.md  # [P] — different file
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 1 (Setup) — `langfuse` dependency
2. Complete Phase 2 (Foundational) — config models + `WorkflowState.observability` carrier
3. Complete Phase 3 (US1) — trace + per-stage spans + safe no-op + bounded flush
4. **STOP**: An operator can already debug a run end-to-end (trace structure + status). Span metadata (prompt hash, model, tokens) and rich privacy controls come in US2/US3.

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ✓
2. Phase 3 (US1) → Operator gets trace structure ✓ (can inspect per-stage durations + status without prompt/model metadata)
3. Phase 4 (US2) → Operator gets actionable per-span metadata ✓
4. Phase 5 (US3) → Operator can safely turn on raw-payload mode for deep debugging ✓
5. Phase 6 → MLflow cross-link, docs, polish ✓

### Parallel Team Strategy

With two contributors:

- After Phase 2 lands, both stories US1 and US3 can proceed in parallel — US3's redaction module is independent of US1's wrapper skeleton.
- US2 should wait for US1's wrapper skeleton to merge so its extension tasks (T029, T030) have a target to extend.

---

## Notes

- `[P]` = different files, safe to run in parallel with other [P] tasks in the same phase.
- `[USN]` = maps to user story N in spec.md.
- The existing MLflow `PipelineTracker` is UNCHANGED in behaviour — feature 006 only adds one new method (`log_langfuse_link`). No existing MLflow tags, params, or metrics are altered (FR-014).
- The 12 existing stage modules under `src/bewerbungs_agent/stages/` are NEVER edited. All observability integration happens at the graph-wiring layer (`workflow.py`) and inside `utils/`. This preserves Constitution Principle V (typed deterministic interfaces unchanged).
- Per FR-013/SC-004: the integration test T014 is the durable guarantee that observability does not affect generation. Treat any future regression of that test as a P0 bug.
- Per FR-015: every SDK exception path inside `LangfuseObservability` must be swallowed with a single warning per process. Run T022 with `-W error` once to confirm no warnings escape.
- Per FR-017: env-var-secret redaction is unconditional. The `mask_pii: false` opt-out only disables the PII regex pass, never the env-var-value pass.
- Token usage integration (T031) uses a `contextvars.ContextVar` to keep stages observability-unaware. This is the only place outside `utils/observability.py` where another module (`utils/llm_client.py`) imports an observability symbol; the import is for the ContextVar object only, not for the Protocol.
