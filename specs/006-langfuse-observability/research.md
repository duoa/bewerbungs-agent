# Phase 0 Research: Langfuse Observability

**Feature**: 006-langfuse-observability
**Date**: 2026-05-13

This phase resolves implementation-relevant unknowns the spec deliberately left out (technology and pattern choices). It does NOT re-litigate scope decisions made during `/speckit.clarify`.

---

## R1 — Langfuse Python SDK shape: which API surface?

**Decision**: Use the official `langfuse` Python package (v2.x), specifically the `Langfuse` client with **explicit trace and span objects** (`langfuse.trace(...)`, `trace.span(...)`, `span.end(...)`). Avoid the `@observe` decorator and the OpenTelemetry-compatible exporter.

**Rationale**:
- The decorator captures function arguments/return values automatically — directly contradicts FR-018 (default summary mode) and FR-017/FR-019a (redaction must run before transmission). Decorator-mode would ship raw payloads first and rely on after-the-fact masking, which is fragile.
- The OTel exporter ties trace lifetime to OTel's context propagation, which adds a dependency layer that our LangGraph pipeline does not already use, and complicates the bounded-flush requirement (FR-020).
- Explicit object APIs let us call `redact(...)` on every field before passing it to the SDK — single chokepoint, easy to audit.

**Alternatives considered**:
- `@observe` decorator: rejected as above.
- OTel exporter (`langfuse.otel.export`): rejected — extra moving parts, unclear lifecycle control.
- Roll our own HTTP client against the Langfuse ingest endpoint: rejected — reimplementing batching, retry, and auth is not the value-add of this feature; the SDK already handles these.

---

## R2 — Wrapper pattern: Protocol + two implementations, or one class with an `enabled` flag?

**Decision**: A `typing.Protocol` named `Observability` plus two concrete classes: `NoOpObservability` and `LangfuseObservability`. The factory function `build_observability(config)` returns whichever is appropriate.

**Rationale**:
- Mirrors the existing `LLMClient` Protocol pattern in `utils/llm_client.py` — operators and contributors learn one shape, not two.
- The no-op class is genuinely zero-cost: it doesn't import `langfuse`, doesn't allocate spans, doesn't run redaction. A single `enabled` flag in a unified class still pays for hot-path branches and risks accidental leakage when a future branch forgets to check the flag.
- Tests can substitute a `MockObservability` (recording dict) without monkey-patching, again matching the project's existing test conventions.

**Alternatives considered**:
- Single class with `if self.enabled: ...` guards: rejected on cost-of-omission grounds.
- ABC instead of Protocol: rejected — Protocol matches the rest of the codebase and avoids inheritance ceremony.

---

## R3 — Where does the trace start and end?

**Decision**: The trace starts in `cli.py` at the top of the `run` command, immediately after `run_id` is generated and immediately after the existing MLflow `start_run`. It ends in a `try/finally` so that normal termination, uncaught exception, and `KeyboardInterrupt` all reach the flush-and-close path. The flush is bounded to 3 s via the SDK's `flush(timeout=3)`.

**Rationale**:
- Matches FR-001 (one trace per CLI invocation) and FR-020 (must close on every termination path).
- Placing it after MLflow start ensures the Langfuse trace ID can be written as an MLflow tag (FR-021) inside the same `try` scope, while the MLflow run is still open.
- LangGraph itself does not manage the trace lifetime; it manages graph execution. Trace lifetime belongs at the CLI boundary, not in `workflow.py`.

**Alternatives considered**:
- Start the trace inside `workflow.py` `build_graph()`: rejected — the graph runs as a stateless invocation and may be called from contexts other than the CLI; trace lifecycle does not belong there.
- Start in a `langgraph` `pre_run` hook: rejected — LangGraph hook semantics are not stable across versions we may upgrade to; explicit code at the CLI is the durable choice.

---

## R4 — How do stage spans get attached without touching every stage module?

**Decision**: Wrap each LangGraph node at registration time in `workflow.py` using a `_wrap_stage(stage_fn, name)` helper that returns a node which (1) opens a span via `state.observability.stage_span(name, ...)`, (2) calls the original `stage_fn(state)`, (3) records output summary on the span, (4) sets status/error on exception, (5) closes the span. Stages themselves remain ignorant of observability.

**Rationale**:
- Preserves Principle V (typed interfaces unchanged). Stage signatures `(WorkflowState) -> dict[str, Any]` are not modified.
- Keeps the diff small: one wrapper function in `workflow.py`, no per-stage edits.
- The wrapper has access to the full `WorkflowState` and the partial-update dict the stage returns, so it can derive both input summary (from state pre-call) and output summary (from the partial update) without stages exposing internal state.

**Alternatives considered**:
- Decorate every stage function manually with `@observe_stage`: rejected — touches 12 files for what should be one wiring change.
- LangGraph node middleware: rejected — LangGraph does not currently expose a stable middleware API; `add_node()` taking a callable lets us wrap freely.
- Side-channel via `WorkflowState.observability` calls from within stages: rejected — couples stages to observability and violates separation of concerns.

---

## R5 — Where does `Observability` live on the WorkflowState?

**Decision**: Add `observability: Any | None = Field(default=None, exclude=True)` to `WorkflowState` (same pattern as the existing `tracker` field). The `_wrap_stage` helper retrieves it from state; stages never read it directly.

**Rationale**:
- LangGraph threads `WorkflowState` through every node, so this is the natural carrier.
- `exclude=True` keeps the object out of any JSON serialisation of state (avoids the SDK accidentally being dumped into an artifact).
- Matches the precedent set by feature 004 (`tracker` field).

**Alternatives considered**:
- Module-level global `_OBSERVABILITY: Observability | None`: rejected — globals are hostile to tests and parallel runs.
- A `contextvars.ContextVar`: rejected — `WorkflowState` already provides the carrier; ContextVar adds a parallel mechanism.

---

## R6 — Summary mode payload shapes

**Decision**: Define one small function per state field in `utils/summaries.py` that maps a typed Pydantic state object to a plain dict containing only counts, lengths, IDs, hashes, and enum labels — never free text. Each `_wrap_stage` call composes the input summary from the pre-call state and the output summary from the partial-update dict the stage returned.

**Rationale**:
- Concentrates summary logic in one file makes it auditable (security review reads one file, not 12).
- Pure-function summaries are trivial to unit-test.
- Keeps stage modules clean.

**Summary contract per state field** (initial set, additive as needed):

| State field | Summary fields |
|---|---|
| `job_context` | `has_company_file: bool`, `has_storyboard_file: bool`, `job_title: str \| None`, `company_name: str \| None`, `raw_job_text_len: int` |
| `requirements` | `core_present: bool`, `technical_count: int`, `has_collaboration: bool`, `has_domain: bool`, `has_optional: bool`, `tone_signals_count: int`, `must_include_count: int`, `must_avoid_count: int` |
| `knowledge` | `cv_variants_count: int`, `project_docs_count: int`, `previous_letters_count: int`, `personal_skills_len: int`, `master_profile_keys: list[str]` |
| `selected_cv` | `variant_id: str`, `full_text_len: int` |
| `evidence_map` | `items_count: int`, `known_gaps_count: int`, `assumptions_count: int`, `passage_total_len: int` |
| `content_plan` | `sections_count: int`, `selected_soft_skills_count: int`, `template_id: str`, `mode: str`, `selected_cv_variant: str` |
| `letter_draft` | `char_count: int`, `mode: str`, `content_plan_hash: str` |
| `cv_tailoring_plan` | `base_variant_id: str`, `changes_count: int`, `tailored_text_len: int` |
| `letter_review` | `sections_count: int`, `sections_to_rewrite_count: int`, `weakness_high_count: int`, `weakness_medium_count: int`, `weakness_low_count: int` |
| `letter_validation` / `cv_validation` | `target: str`, `passed: bool`, `violations: list[str]`, `results_count: int` |

**Alternatives considered**:
- Inline lambdas in `workflow.py`: rejected — clutters wiring and resists testing.
- Generic `model.model_dump(include={...})`: rejected — every state model would need an explicit allowlist anyway; explicit summary functions are clearer.

---

## R7 — Redaction strategy: regex vs. structural

**Decision**: Structural redaction first (drop known credential env-var values by name), then regex pass over remaining string fields for PII patterns. Apply in `utils/redaction.py.redact(value, mode)` where `mode ∈ {"summary", "full"}`. Summary mode applies only the env-var-value pass (PII can't appear in summaries by construction). Full mode applies both.

**Rationale**:
- Structural redaction is exact: we know which env-var values are secrets at process start; we replace literal matches with `<REDACTED:NAME>`. No false positives.
- Regex redaction is approximate but cheap; needed in full mode where prose may contain operator email/phone/IBAN/addresses.
- Two passes are cheaper than one combined regex because the structural pass needs no scanning of values it doesn't match.

**Redaction patterns** (initial set; documented as configurable additions, not user-configurable in v1):

| Pattern | Regex sketch | Replacement |
|---|---|---|
| Email | `[\w.+-]+@[\w-]+\.[\w.-]+` | `<EMAIL>` |
| Phone (E.164 + national) | `\+?\d[\d\s().-]{7,}\d` | `<PHONE>` |
| IBAN | `[A-Z]{2}\d{2}[A-Z0-9]{10,30}` | `<IBAN>` |
| Postal block (DE common) | `\b\d{5}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+\b` | `<POSTAL>` |
| Env-var values (`*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`) | literal value match at process start | `<REDACTED:NAME>` |

**Alternatives considered**:
- Use a library (e.g., `scrubadub`): rejected — added dependency for a small, well-bounded surface; constitution prefers minimal dependency footprint.
- Hashing the content (irreversible): rejected — destroys debugging value.

---

## R8 — Output byte-equivalence guarantee (FR-013, SC-004)

**Decision**: The wrapper introduces no work that touches `letter.md` or `artifacts/*.json` content paths. Verified by an integration test that runs the pipeline twice (enabled-vs-disabled, mocked LLM with deterministic responses) and asserts `filecmp.cmp(..., shallow=False)` on every output file.

**Rationale**:
- The only thing FR-013 actually requires is that we don't add randomness, ordering effects, or side effects into the generation path. Since the wrapper runs around stages and reads state via summary functions (no mutation), this is structurally satisfied.
- The test is the durable safeguard: it would catch any future regression where someone reaches into the wrapper to "enrich" outputs.

**Alternatives considered**:
- Property-based test with random fixtures: rejected — overkill for a structural property; one deterministic compare is enough.

---

## R9 — MLflow ↔ Langfuse cross-link timing

**Decision**: Inside `cli.py.run`, after `tracker.start_run(...)` returns and after `LangfuseObservability.start_trace(run_id)` returns, the CLI calls `tracker.log_langfuse_link(trace_id, trace_url)` — a thin new method on `PipelineTracker` that wraps `mlflow.set_tag` in the existing try/except. Per spec FR-021 the link is one-way only.

**Rationale**:
- Both backends are guaranteed open at this point.
- One-way (MLflow ← Langfuse trace ID) keeps the failure surface minimal (FR-014).
- Existing `PipelineTracker` already swallows exceptions; reusing it inherits that posture.

**Alternatives considered**:
- Write the link inside `LangfuseObservability.start_trace`: rejected — couples observability to MLflow knowledge.
- Skip the link entirely: rejected — spec FR-021 is MUST (post-clarification).

---

## R10 — Configuration shape under `observability.langfuse.*`

**Decision**: Add `ObservabilityConfig` (Pydantic, `extra="forbid"`) with a nested `LangfuseConfig`:

```python
class LangfuseConfig(BaseModel):
    enabled: bool = False
    log_full_inputs: bool = False
    log_full_outputs: bool = False
    mask_pii: bool = True       # in full mode; summary mode ignores this (always masks)

class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
```

Mounted on both `StarterTemplate` and `MergedConfig` as `observability: ObservabilityConfig`. Propagated via the `base` dict in `utils/merge.py` (the §15 gotcha from `ENGINEERING.md`).

**Rationale**:
- User's command request named these exact flag keys; preserved verbatim.
- `mask_pii: True` default keeps the conservative posture from the spec (operators must explicitly opt out — but only out of the regex PII masking; env-var redaction is always on per FR-017).
- Nested `langfuse.*` namespace leaves room for future backends without restructuring config.

**Alternatives considered**:
- Flat `observability_*` keys: rejected — namespace pollution; tracker already taught operators the nested-config pattern.

---

## R11 — Tests inventory mapped to spec FRs

**Decision**: Five test categories, each pinned to one or more functional requirements:

| Test | FRs covered | Location |
|---|---|---|
| `test_observability_noop_when_disabled` | FR-011, FR-012, FR-015 | `tests/unit/test_observability.py` |
| `test_observability_creates_one_span_per_stage` | FR-001, FR-002, FR-016, FR-016a | `tests/unit/test_observability.py` |
| `test_observability_records_metadata_fields` | FR-003..FR-010 | `tests/unit/test_observability.py` |
| `test_observability_captures_stage_exception` | FR-008, FR-024 | `tests/unit/test_observability.py` |
| `test_redaction_env_vars_and_pii` | FR-017, FR-019a | `tests/unit/test_redaction.py` |
| `test_full_run_outputs_byte_identical_enabled_vs_disabled` | FR-013, FR-025, SC-004 | `tests/integration/test_full_run.py` |

This mapping is the source of truth for `/speckit.tasks` — every FR has at least one test.

---

## Open questions resolved during research

- "Does `langfuse` SDK respect `flush(timeout=)`?" — Yes, since langfuse 2.0; documented in their SDK README. Decision R3 relies on this.
- "Does `mlflow.set_tag` accept arbitrary string values?" — Yes; URL strings are fine.
- "Does WorkflowState's `tracker: Any | None = Field(default=None, exclude=True)` survive Pydantic v2 round-trips through LangGraph?" — Yes; verified by the existing feature-004 integration test.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
