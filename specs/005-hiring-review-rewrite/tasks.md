# Tasks: Hiring-Manager Review and Targeted Rewrite Stage

**Input**: Design documents from `/specs/005-hiring-review-rewrite/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**TDD**: Tests are written FIRST and must FAIL before the corresponding implementation task begins. This is enforced by the constitution (Principle VI).

**Organization**: Tasks grouped by user story. Each story is independently testable via unit tests with mocked LLM.

---

## Phase 1: Setup

No new project structure or dependencies required. This feature extends an existing Python package; all required libraries (anthropic SDK, pydantic, langgraph) are already installed. No setup tasks needed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config models, state models, and merge wiring that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T001 Write failing tests for `ReviewConfig` parsing, default values, and propagation through `merge_config()` in `tests/unit/test_config_models.py` (add to existing file: 4 new test methods covering ReviewDimension enum, WeaknessSeverity enum, ReviewConfig defaults, and review_config field surviving merge_config round-trip)
- [X] T002 Add `ReviewDimension`, `WeaknessSeverity`, `ReviewConfig` enums/model and `review_config: ReviewConfig` field to `StarterTemplate` and `MergedConfig` in `src/bewerbungs_agent/config/models.py` — confirm T001 tests now pass
- [X] T003 Add `"review_config": template.review_config` to the explicit `base` dict in `src/bewerbungs_agent/utils/merge.py` (critical: MergedConfig uses `extra="forbid"` and does not auto-propagate fields)
- [X] T004 Add `WeaknessEntry`, `SectionReview`, `LetterReviewReport` Pydantic models and `letter_review: LetterReviewReport | None = None` field to `WorkflowState` in `src/bewerbungs_agent/models/state.py` — import `WeaknessSeverity` from config.models

**Checkpoint**: Config models validate; merge_config propagates review_config; WorkflowState carries letter_review field; T001 tests pass.

---

## Phase 3: User Story 1 — Automated Section-Level Review (Priority: P1) 🎯 MVP

**Goal**: After write_letter, a hiring_review stage produces a structured LetterReviewReport with per-section strengths, weaknesses (severity + fix), and a pre-computed list of sections to rewrite.

**Independent Test**: Run `hiring_review(state)` with a mocked LLM returning a review payload; assert LetterReviewReport is populated in the returned dict with correct sections_to_rewrite derived from the threshold.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T007

- [X] T005 Write failing unit tests for `hiring_review` stage in `tests/unit/test_hiring_review.py`:
  - `test_hiring_review_produces_review_report`: mock LLM returns a valid review payload; assert `letter_review` key in result; assert `letter_review.sections` is non-empty; assert `sections_to_rewrite` contains only sections with weaknesses ≥ medium severity
  - `test_hiring_review_computes_sections_to_rewrite_from_threshold`: mock returns two sections (one high-severity, one low-severity weakness); default threshold=medium; assert only the high-severity section is in `sections_to_rewrite`
  - `test_hiring_review_returns_empty_when_disabled`: `config.review_config.enabled=False`; assert no LLM call made; assert result is `{}`
  - `test_hiring_review_returns_empty_when_no_letter`: `state.letter_draft=None`; assert result is `{}`
  - `test_hiring_review_swallows_llm_exception`: LLM raises `RuntimeError`; assert result is `{}`; assert no exception propagates
  - `test_hiring_review_logs_stage_when_tracker_present`: mock tracker; assert `tracker.log_stage` called with `stage_name="hiring_review"`

### Implementation for User Story 1

- [X] T006 [P] Create system prompt file `prompts/hiring_reviewer.md`:
  - Role: experienced hiring manager for the target role
  - Task: evaluate each section across ONLY the specified dimensions
  - Strict schema requirement: must return structured JSON matching the review schema
  - Forbidden: using any information outside the provided letter text and role requirements
  - Instruction: identify section boundaries dynamically from the letter text; name sections descriptively
- [X] T007 Implement `src/bewerbungs_agent/stages/hiring_review.py`:
  - `_REVIEW_SCHEMA`: JSON Schema dict matching `LetterReviewReport` structure (sections array with section_name, strengths, weaknesses[text/severity/priority_fix], assessment; overall_assessment)
  - `build_prompt(state)`: constructs user message from `letter_draft.text`, all fields of `requirements`, and `config.review_config.dimensions` list (only active dimensions passed)
  - `parse_response(data, threshold)`: parses LLM tool-use response into `LetterReviewReport`; pre-computes `sections_to_rewrite` as section names whose max weakness severity ≥ threshold (using severity ordering low < medium < high)
  - `hiring_review(state)`: enabled guard → input guards → `resolve_stage_thinking` → `client.call(messages, _REVIEW_SCHEMA, system=load_prompt("hiring_reviewer"), thinking=stage_th)` → `parse_response(response, config.review_config.rewrite_threshold)` → tracker logging → return `{"letter_review": report}`; entire call in `try/except Exception: warnings.warn(); return {}`
- [X] T008 Confirm all tests in `tests/unit/test_hiring_review.py` pass

**Checkpoint**: `hiring_review` stage fully implemented and tested in isolation. LetterReviewReport produced correctly; sections_to_rewrite reflects threshold; all failure modes return `{}`.

---

## Phase 4: User Story 2 — Targeted Rewrite of Weak Sections Only (Priority: P2)

**Goal**: The `targeted_rewrite` stage reads the LetterReviewReport and rewrites only sections in `sections_to_rewrite` while preserving all other sections verbatim. Output overwrites `letter_draft` in WorkflowState.

**Independent Test**: Inject a pre-built LetterReviewReport with one section flagged and one strong into a state with a known letter; assert flagged section text changes and strong section text is preserved in the output `letter_draft`.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T011

- [X] T009 Write failing unit tests for `targeted_rewrite` stage in `tests/unit/test_targeted_rewrite.py`:
  - `test_targeted_rewrite_returns_empty_when_no_review`: `state.letter_review=None`; assert result is `{}`
  - `test_targeted_rewrite_returns_empty_when_no_sections_to_rewrite`: `letter_review.sections_to_rewrite=[]`; assert no LLM call; assert result is `{}`
  - `test_targeted_rewrite_returns_new_letter_draft`: mock LLM returns revised text; assert `letter_draft` key in result; assert `letter_draft.text` equals mock response text; assert `letter_draft.mode` preserved from original
  - `test_targeted_rewrite_swallows_llm_exception`: LLM raises `RuntimeError`; assert result is `{}`; assert no exception propagates
  - `test_targeted_rewrite_prompt_contains_only_letter_and_requirements`: inspect `build_prompt()` output; assert it contains `letter_draft.text` and requirements fields; assert it does NOT contain InternalKnowledge or ContentPlan references
  - `test_targeted_rewrite_logs_stage_when_tracker_present`: mock tracker; assert `tracker.log_stage` called with `stage_name="targeted_rewrite"`

### Implementation for User Story 2

- [X] T010 [P] Create system prompt file `prompts/targeted_rewriter.md`:
  - Task: targeted rewrite of specified weak sections only
  - Strong sections: reproduce verbatim, character-for-character
  - Forbidden: introducing any fact, skill, employer, tool, project, or result not present in the provided letter text or role requirements
  - Output: complete cover letter text (not a diff), Markdown format
  - Instruction: use the structured review feedback for each flagged section as the sole guide for improvement
- [X] T011 Implement `src/bewerbungs_agent/stages/targeted_rewrite.py`:
  - `_REWRITE_SCHEMA`: JSON Schema with `text: string` (complete rewritten letter)
  - `build_prompt(state)`: constructs user message from `letter_draft.text` (full letter), `letter_review` model JSON, `letter_review.sections_to_rewrite` list (explicit instruction on which to rewrite), and all `requirements` fields; does NOT include knowledge, content_plan, or profile docs
  - `parse_response(data, original_draft)`: parse text from response; build new `LetterDraft` preserving `mode` and `content_plan_hash` from original
  - `targeted_rewrite(state)`: guard `state.letter_review is None` → guard `sections_to_rewrite` empty → `resolve_stage_thinking` → `client.call(messages, _REWRITE_SCHEMA, system=load_prompt("targeted_rewriter"), thinking=stage_th)` → `parse_response(response, state.letter_draft)` → tracker logging → return `{"letter_draft": new_draft}`; entire call in `try/except Exception: warnings.warn(); return {}`
- [X] T012 Update `src/bewerbungs_agent/graph/workflow.py`:
  - Import `hiring_review` from `bewerbungs_agent.stages.hiring_review` and `targeted_rewrite` from `bewerbungs_agent.stages.targeted_rewrite` via `_import_stage()` (lazy import pattern consistent with existing workflow)
  - Register nodes: `graph.add_node("hiring_review", hiring_review_fn)` and `graph.add_node("targeted_rewrite", targeted_rewrite_fn)`
  - Remove edge: `graph.add_edge("write_letter", "validate_outputs")` → DELETED
  - Add edges: `write_letter → hiring_review → targeted_rewrite → validate_outputs`
  - Verify `tailor_cv → validate_outputs` edge is preserved (fan-in unchanged)
- [X] T013 Confirm all tests in `tests/unit/test_targeted_rewrite.py` pass

**Checkpoint**: Both new stages implemented and tested. Graph topology updated. Full review+rewrite chain wired: `write_letter → hiring_review → targeted_rewrite → validate_outputs`.

---

## Phase 5: User Story 3 — Configurable Dimensions and Rewrite Threshold (Priority: P3)

**Goal**: Operators can restrict active review dimensions and raise the rewrite threshold via starter template YAML or run-level overrides. The stages respect these settings without code changes.

**Independent Test**: Pass `ReviewConfig(dimensions=[clarity, credibility], rewrite_threshold=high)` via config; run hiring_review with mocked LLM; assert prompt contains only "clarity" and "credibility" in dimensions list; assert a medium-severity section is absent from `sections_to_rewrite`.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE VERIFICATION

- [X] T014 Write failing tests for config-driven behaviour in `tests/unit/test_config_models.py` (extend existing file):
  - `test_review_config_dimension_subset`: create `ReviewConfig(dimensions=[ReviewDimension.clarity, ReviewDimension.credibility])`; assert `len(config.dimensions) == 2`
  - `test_review_config_high_threshold_filters_medium_sections`: build a `LetterReviewReport` from `parse_response` with a medium-severity section and a high-severity section; threshold=`WeaknessSeverity.high`; assert only the high-severity section is in `sections_to_rewrite`
  - `test_review_config_flows_through_merge_config`: create a `StarterTemplate` with `review_config=ReviewConfig(rewrite_threshold=WeaknessSeverity.high)`; call `merge_config()`; assert resulting `MergedConfig.review_config.rewrite_threshold == WeaknessSeverity.high`
  - `test_hiring_review_prompt_contains_only_active_dimensions`: mock config with `dimensions=[ReviewDimension.clarity]`; call `build_prompt()`; assert only "clarity" appears in dimension list in the prompt content

### Verification for User Story 3

- [X] T015 [P] Verify `hiring_review.build_prompt()` passes `config.review_config.dimensions` as the active dimensions list in the constructed user message in `src/bewerbungs_agent/stages/hiring_review.py` — update if needed to ensure only active dimensions are listed
- [X] T016 [P] Verify `hiring_review.parse_response()` applies `config.review_config.rewrite_threshold` correctly when computing `sections_to_rewrite` in `src/bewerbungs_agent/stages/hiring_review.py` — update threshold comparison if needed
- [X] T017 Confirm all T014 tests pass

**Checkpoint**: Config-driven dimension restriction and threshold control verified end-to-end through config → stage.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration test, CLI output, observability, and documentation.

- [X] T018 Extend `tests/integration/test_full_run.py` with `test_full_pipeline_with_hiring_review`: mock all LLM calls (including the two new review/rewrite calls); run `graph.stream(initial_state)`; assert `final_state.letter_review` is populated; assert `final_state.letter_draft` reflects the mock rewrite output
- [X] T019 Update `src/bewerbungs_agent/cli.py` run command output: after writing artifacts, if `final_state.letter_review` is present, print summary line `  letter_review.md  ({n} sections reviewed, {k} rewritten)` — consistent with existing output style
- [X] T020 Update `ENGINEERING.md`: add section covering the hiring-review + targeted-rewrite stages: what they do, how to configure dimensions and threshold in a template YAML, how to disable via `review_config.enabled: false`, and how to inspect `letter_review` in run outputs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: No dependencies — start immediately. BLOCKS all story phases.
- **US1 (Phase 3)**: Depends on Phase 2 completion. Independently testable via mocked LLM.
- **US2 (Phase 4)**: Depends on Phase 2 completion. US1 must be complete before T012 (graph wiring includes both nodes). US2 unit tests (T009) can be written in parallel with US1 implementation.
- **US3 (Phase 5)**: Depends on Phase 2 (config) and US1 (parse_response threshold logic). Most of US3 is already implemented by T002 + T007.
- **Polish (Phase 6)**: Depends on US1 + US2 completion (graph wired, both stages implemented).

### Within Each Story

- Tests MUST be written and FAIL before implementation.
- `parse_response` depends on schema being defined → implement together in one task.
- Prompt file [P] can be created in parallel with stage implementation.
- Graph wiring (T012) must come after both stage modules exist.

---

## Parallel Opportunities

```bash
# Foundational: T004 blocks nothing in parallel with T002/T003
Task T002: Add config models to config/models.py
Task T004: Add state models to state/state.py  # [P] different file

# US1 + US2 prompt files can be created in parallel:
Task T006: Create prompts/hiring_reviewer.md
Task T010: Create prompts/targeted_rewriter.md  # [P] different file

# US3 verification tasks can run in parallel:
Task T015: Verify dimension restriction in hiring_review.py
Task T016: Verify threshold computation in hiring_review.py  # same file — sequential
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 2 (Foundational) — all config + state models
2. Complete Phase 3 (US1) — hiring_review stage alone, unit tested
3. **STOP**: The review report is visible in logs and outputs even without the rewrite stage. Inspect `letter_review` to validate review quality.

### Incremental Delivery

1. Phase 2 → Foundation ✓
2. Phase 3 → Review stage working ✓ (can inspect structured feedback without rewriting)
3. Phase 4 → Rewrite stage + graph wired ✓ (full review+rewrite chain live)
4. Phase 5 → Config-driven control ✓ (operators can tune dimensions and threshold)
5. Phase 6 → Integration test + docs ✓

---

## Notes

- `[P]` = different files, safe to run in parallel with other [P] tasks in the same phase
- `[USN]` = maps to user story N in spec.md
- The existing `rewrite.py` / `rewrite_if_needed` stage is UNCHANGED — it handles validation-failure rewrites (post-validate). The new `targeted_rewrite.py` handles pre-validate quality rewrites (different concern, different location in graph).
- `sections_to_rewrite` is pre-computed by `hiring_review` using the threshold from config, NOT by `targeted_rewrite`. This keeps `targeted_rewrite` free of business logic.
- `targeted_rewrite` overwrites `letter_draft` in place — `validate_outputs` needs zero changes.
- Tracker integration pattern: `state.tracker.log_stage(stage_name=..., model=AnthropicLLMClient.MODEL, thinking=stage_th, prompt_name=..., prompt_hash=_compute_prompt_hash(...))` — consistent with Feature 004 pattern in all other stages.
