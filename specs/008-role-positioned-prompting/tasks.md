# Tasks: Role-Positioned Prompting

**Input**: Design documents from `/specs/008-role-positioned-prompting/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-023..FR-027 enumerate the required automated tests and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task begins. Tests use mocked LLM responses (no real Anthropic calls in unit tests).

**Organization**: Tasks grouped by user story. US1 and US2 are both Priority P1 — they form the MVP pair (the planner records positioning AND the writer consumes it); US3 (P2) closes the verification loop via the hiring-review stage.

---

## Phase 1: Setup

**Purpose**: No new dependencies; this is a prompt-and-context feature reusing the existing toolchain. One verification task.

- [X] T001 Verify the existing tool suite is healthy by running `.venv/bin/pytest tests/ --tb=short` and confirming the 215-test baseline passes; capture the baseline count for the Phase 6 sweep

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: One Pydantic schema addition (`RolePositioning` + the optional `ContentPlan.role_positioning` field) and two test fixtures (the AI/ML infrastructure job + the biomedical-ML profile project) that ALL three user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Write failing tests for `RolePositioning` and the new optional `ContentPlan.role_positioning` field in `tests/unit/test_plan_content.py` (add 4 new tests in a new `TestRolePositioningModel` class: valid construction populates all 6 fields; missing-required fields raise `ValidationError`; extra-key strict mode forbids typos; `ContentPlan` accepts `role_positioning=None` for backward compatibility with previously-serialised plans)
- [X] T003 Add the `RolePositioning` Pydantic model (with `extra="forbid"` and the 6 fields per data-model.md §1) and the `role_positioning: RolePositioning | None = None` field on `ContentPlan` in `src/bewerbungs_agent/models/state.py`; placement: insert `RolePositioning` directly above `ContentPlan`; field added at the end of `ContentPlan` to preserve existing serialisation order
- [X] T004 [P] Create the AI/ML infrastructure fixture at `data/examples/jobs/sample_ml_infrastructure.md` — a job description emphasising scalable cloud infrastructure, efficient compute, robust Python software, AI/ML workloads, and agentic systems; biomedical-data context appears at most as a nice-to-have late in the ad; length ~400–800 words
- [X] T005 [P] Create the biomedical-ML project fixture at `data/examples/profile/projects/biomedical_ml_project.md` — a notable project describing the candidate doing biomedical-ML modelling, ~300–500 words, mentioning concrete pipeline / model / dataset detail so the planner would see it as legitimately relevant evidence; this is the bait that the planner MUST NOT promote to primary positioning
- [X] T006 Confirm Phase 2 tests in `tests/unit/test_plan_content.py::TestRolePositioningModel` pass and the existing 215-test suite still reports 219+ passed (215 existing + 4 new)

**Checkpoint**: The new Pydantic model exists, ContentPlan loads with or without positioning, fixture files are on disk and discoverable by the existing loader, all foundational tests pass.

---

## Phase 3: User Story 1 — Planner Produces Explicit Role-Positioning (Priority: P1) 🎯 MVP-part-1

**Goal**: The planner emits a `role_positioning` block alongside its existing output. The block reflects the job description's framing, not the candidate's strongest evidence. The planner's user-message prompt now includes the full raw job description text in a new `# Job Description (verbatim)` block.

**Independent Test**: Run `stages/plan_content.build_prompt(state)` with a state whose `job_context.raw_job_text` is the new AI/ML infrastructure fixture; assert the constructed prompt contains the raw job text verbatim and references positioning instructions. Separately, run `stages/plan_content.parse_response(...)` with a canned LLM JSON whose `role_positioning.primary_role_family` is "AI/ML platform engineering"; assert the resulting `ContentPlan` carries that value and that the biomedical-ML angle appears only in `secondary_selling_points`.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T010

- [X] T007 [P] [US1] Write failing test `test_planner_prompt_includes_raw_job_text_and_positioning_instructions` in `tests/unit/test_plan_content.py` — build a `WorkflowState` with `job_context.raw_job_text` set to a sentinel string containing the unique marker `"SCALABLE_CLOUD_INFRA_SENTINEL"`; call `plan_content.build_prompt(state)`; assert (a) the constructed user message contains the sentinel string verbatim, (b) the message references `role_positioning`, (c) the message references `primary_role_family` (FR-001, FR-002, contracts §4)
- [X] T008 [US1] Write failing test `test_planner_parse_accepts_role_positioning_subobject` in `tests/unit/test_plan_content.py` — construct a canned response dict carrying a valid `role_positioning` block with all 6 fields; call `parse_response(data, soft_skill_max=3)`; assert the returned `ContentPlan.role_positioning` is a non-None `RolePositioning` whose `primary_role_family` matches the canned value
- [X] T009 [US1] Write failing test `test_planner_positions_infrastructure_first_on_ml_infra_fixture` in `tests/unit/test_plan_content.py` — canned LLM response models a CORRECT positioning decision: `primary_role_family="AI/ML platform engineering"`, `primary_selling_point` referencing infrastructure work, `secondary_selling_points` includes biomedical-ML, `topics_to_deemphasise` includes "biomedical domain depth"; call `parse_response(...)`; assert `role_positioning.primary_role_family` contains "platform" or "infrastructure" (NOT "biomedical"), assert any biomedical reference appears only inside `secondary_selling_points` (NOT in `primary_selling_point`) (FR-004, FR-024, SC-002)

### Implementation for User Story 1

- [X] T010 [US1] Rewrite `prompts/planner.md` per contracts §1 — keep existing no-prose / claim-traceability rules; add: a `## Source-of-truth ordering` section explaining the job description text comes first / extracted requirements second / candidate's evidence third; a `## Required output: role_positioning` section listing all 6 fields with one-line semantics each; a `## Previous letters are evidence, not exemplars` line addressing the contamination edge case from research.md §R9; the explicit instruction that if no evidence supports the primary role family, the gap goes in `known_gaps` rather than downgrading the primary_role_family
- [X] T011 [US1] Update `stages/plan_content.py::build_prompt` to insert a `# Job Description (verbatim)\n<raw_job_text>` block between the existing config line and the existing `# Extracted Requirements` block per contracts §4; when `state.job_context` is None or `raw_job_text` is empty, emit `(unavailable)` so the LLM still gets a coherent prompt structure
- [X] T012 [US1] Confirm all US1 tests (T007–T009) pass; confirm the existing planner tests (`tests/unit/test_plan_content.py::TestBuildPrompt`, `TestParseResponse`) still pass (the change is additive — old assertions should not regress)

**Checkpoint**: The planner records explicit positioning. The new `artifacts/content_plan.json` files in any subsequent run carry a `role_positioning` block. The runtime stage span for `plan_content` (feature 006) automatically picks up the new prompt hash for `planner.md`.

---

## Phase 4: User Story 2 — Writer Opens with the Hiring Thesis (Priority: P1) 🎯 MVP-part-2

**Goal**: The writer reads `role_positioning` from the content plan and `writer_rules` from config, and produces prose that (a) opens with the primary role family in the first 400 chars, (b) prefers system-level outcomes over tool lists, (c) caps distinct tool names per paragraph at the configured maximum, (d) emits no banned self-rating phrases, (e) introduces no claim absent from the plan.

**Independent Test**: Run `stages/write_letter.build_prompt(state)` with a state whose `content_plan.role_positioning` is the canned infrastructure positioning and whose `config.writer_rules` has `tool_density_max=4` and the default ban list; assert the constructed prompt contains a `# Role Positioning` block listing all 6 positioning fields and a `# Writer Rules` block listing `tool_density_max=4` and all 7 banned phrases. (Behavioural enforcement is via prompt instruction; the hiring-review stage in US3 catches violations.)

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T017

- [X] T013 [P] [US2] Write failing tests for `WriterRules` config in `tests/unit/test_config_models.py` (add a new `TestWriterRules` class with 4 tests: defaults are tool_density_max=4 and the 7-entry ban list; tool_density_max bounds rejected outside [1,20]; extra keys forbidden; writer_rules from `StarterTemplate` survives `merge_config()` round-trip)
- [X] T014 [US2] Add the `WriterRules` Pydantic model per data-model.md §3 to `src/bewerbungs_agent/config/models.py` (with `extra="forbid"`, `tool_density_max: int = Field(default=4, ge=1, le=20)`, and the 7-entry default `banned_phrases` list); add `writer_rules: WriterRules = Field(default_factory=WriterRules)` to both `StarterTemplate` and `MergedConfig`; placement: append after `observability` in both models so existing YAML continues to parse unchanged
- [X] T015 [US2] Add `"writer_rules": template.writer_rules` to the explicit `base` dict in `src/bewerbungs_agent/utils/merge.py` (the documented `extra="forbid"` propagation gotcha from ENGINEERING.md §15); confirm T013 tests pass after this and T014
- [X] T016 [P] [US2] Write failing test `test_writer_prompt_includes_positioning_block_and_writer_rules` in `tests/unit/test_write_letter.py` — build a state whose `content_plan.role_positioning` is the canned infrastructure positioning (primary_role_family="AI/ML platform engineering", secondary biomedical-ML, opening_angle="lead with infrastructure-builder identity") and whose `config.writer_rules` carries the defaults; call `write_letter.build_prompt(state)`; assert the constructed user message contains: substring "Role Positioning", substring "primary_role_family", substring "AI/ML platform engineering", substring "tool_density_max", substring "4", substring "expert-level", substring "deep expertise" (FR-006, FR-007, FR-008, contracts §5)

### Implementation for User Story 2

- [X] T017 [US2] Rewrite `prompts/writer.md` per contracts §2 — keep existing factuality / language / structure rules; add: a `## Role Positioning consumption` section telling the LLM that the input has a `role_positioning` field and explaining how each of the 6 entries shapes the writing; a `## Opening rule` requiring the first paragraph to reference `primary_role_family` and `opening_angle` within the first 400 characters and forbidding it from leading with `secondary_selling_points` or `topics_to_deemphasise`; a `## Tool density` section using the placeholder `{tool_density_max}` (Python `str.format` placeholder, resolved by build_prompt); a `## Banned self-rating phrases` section using the placeholder `{banned_phrases}` resolved by build_prompt; a `## No claim outside the plan` section restating the factuality rule; a `## De-emphasis discipline` section forbidding `topics_to_deemphasise` topics from headings, openings, or repetitions
- [X] T018 [US2] Update `stages/write_letter.py::build_prompt` per contracts §5 — insert a `# Role Positioning` block formatted from `state.content_plan.role_positioning` (when present; emit `(none)` when None) AND a `# Writer Rules` block formatted from `state.config.writer_rules`, both inserted BEFORE the existing content-plan JSON block; load the writer prompt via `load_prompt("writer")` then call `.format(tool_density_max=..., banned_phrases=", ".join(...))` on it before appending to the user message (the `{tool_density_max}` and `{banned_phrases}` placeholders in the prompt file are resolved here)
- [X] T019 [US2] Confirm all US2 tests (T013, T016) pass; confirm the existing writer tests (`tests/unit/test_write_letter.py`) still pass

**Checkpoint**: Writer is wired. Runtime stage span for `write_letter` (feature 006) picks up the new prompt hash. With US1 + US2 merged, the MVP is shippable: positioning is decided AND consumed; better letters land. US3 below adds the verification safety net.

---

## Phase 5: User Story 3 — Hiring Review with Full Job Context (Priority: P2)

**Goal**: The hiring-review stage receives the full original job description text in addition to the existing structured requirements and draft letter, and explicitly evaluates the five new positioning dimensions (role match, opening alignment, secondary-topic dominance, tool density, overclaiming). Mispositioned letters trigger the existing targeted-rewrite path.

**Independent Test**: Run `stages/hiring_review.build_prompt(state)` with `state.job_context.raw_job_text` set to the infrastructure fixture and assert the constructed prompt contains the verbatim job text AND the 5 new dimension names. Then run `parse_response(canned_data, threshold=WeaknessSeverity.medium)` with canned LLM JSON that flags the opening section with a medium "role_match" weakness and a medium "opening_alignment" weakness; assert the resulting `LetterReviewReport.sections_to_rewrite` contains "opening".

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T023

- [X] T020 [P] [US3] Write failing test `test_hiring_review_prompt_includes_raw_job_text` in `tests/unit/test_hiring_review.py` — build a state whose `job_context.raw_job_text` contains the sentinel `"SCALABLE_CLOUD_INFRA_SENTINEL"`; call `hiring_review.build_prompt(state)`; assert the constructed user message contains the sentinel verbatim AND a heading like "Original Job Description" (FR-011, FR-020, contracts §6)
- [X] T021 [US3] Write failing test `test_hiring_review_prompt_lists_positioning_dimensions` in `tests/unit/test_hiring_review.py` — same state; assert the constructed prompt contains substrings for all 5 new dimensions: "role_match", "opening_alignment", "secondary_topic_dominance", "tool_density", "overclaiming" (FR-012)
- [X] T022 [US3] Write failing test `test_hiring_review_flags_role_match_and_opening_when_mispositioned` in `tests/unit/test_hiring_review.py` — build a canned response dict with two sections ("opening" and "experience"); the opening section has weaknesses with `text="letter leads with biomedical-ML, but job is infrastructure"`, `severity="medium"`, `priority_fix="re-anchor opening to AI/ML platform engineering"`, plus a second weakness `text="tool density too high in paragraph 2"`, `severity="medium"`; call `parse_response(data, WeaknessSeverity.medium)`; assert `sections_to_rewrite` contains "opening" (FR-013, FR-014, FR-025, SC-007)

### Implementation for User Story 3

- [X] T023 [US3] Rewrite `prompts/hiring_reviewer.md` per contracts §3 — keep existing severity rubric and strict-constraints section; add: a `## Inputs` section explaining the prompt now includes the original job description text; a `## Five positioning-specific dimensions` section enumerating role_match, opening_alignment, secondary_topic_dominance, tool_density, overclaiming with one-line failure criteria each; a `## Severity calibration for positioning failures` paragraph instructing the LLM to flag positioning failures at severity ≥ medium when they would meaningfully damage the application; a `## Quote, don't paraphrase` line telling the LLM to quote offending phrases verbatim in `priority_fix` when flagging overclaiming
- [X] T024 [US3] Update `stages/hiring_review.py::build_prompt` per contracts §6 — insert a `## Original Job Description (verbatim)\n<state.job_context.raw_job_text>` block between the existing "## Role Requirements" block and the "## Evaluation Dimensions" block; when `state.job_context` is None emit `(job description unavailable — base evaluation on requirements only)`; extend the `active_dims` list to always include the 5 new positioning dimensions in addition to whatever `config.review_config.dimensions` already specifies (the new dimensions are first-class, not opt-in)
- [X] T025 [US3] Confirm all US3 tests (T020–T022) pass; confirm the existing hiring-review tests (`tests/unit/test_hiring_review.py`) still pass

**Checkpoint**: Hiring review uses the full job description. Positioning failures route through the existing targeted-rewrite path. End-to-end positioning loop is closed.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Extend `summarise_content_plan` in `src/bewerbungs_agent/utils/summaries.py` to add a one-bit `role_positioning_present: bool` field (computed as `value.role_positioning is not None`); this preserves the summary-mode privacy default (no positioning prose in spans) while letting operators see at a glance in Langfuse whether positioning was recorded for a given run
- [X] T027 [P] Update `ENGINEERING.md` with a new Section 19 "Role-Positioned Prompting" describing: the `RolePositioning` sub-object on `ContentPlan`, the `writer_rules` config block (with default values), the three-prompt edits, the new job-text data flow into hiring_review, the non-interference invariants (FR-015..FR-019), the AI/ML infrastructure fixture, and the manual smoke-test recipe from `quickstart.md` §7; renumber the existing "Environment variables" section to 20
- [X] T028 Run the full test suite `.venv/bin/pytest tests/ --tb=short`; expected count = previous baseline (215) + 4 foundational + 3 US1 + 5 US2 + 3 US3 = 230 passed; halt and fix if any regression
- [X] T029 Run static checks on every file touched by this feature: `.venv/bin/ruff check src/bewerbungs_agent/models/state.py src/bewerbungs_agent/config/models.py src/bewerbungs_agent/utils/merge.py src/bewerbungs_agent/utils/summaries.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/write_letter.py src/bewerbungs_agent/stages/hiring_review.py tests/unit/test_plan_content.py tests/unit/test_write_letter.py tests/unit/test_hiring_review.py tests/unit/test_config_models.py` and `.venv/bin/mypy <same source files>`; fix any errors introduced by this feature
- [X] T030 Run the quickstart §7 manual smoke test against the new fixture (or document explicit deferral) — `jobagent run --job data/examples/jobs/sample_ml_infrastructure.md --template default_de_neutral`, then inspect `outputs/<run_id>/artifacts/content_plan.json` for `role_positioning.primary_role_family` containing "platform" or "infrastructure" (not "biomedical"), and `outputs/<run_id>/letter.md` for an infrastructure-flavoured opening + zero banned phrases
- [X] T031 [P] Push the three edited prompts to Langfuse: `uv run jobagent prompts sync --label staging`; expected output mentions exactly 3 created (planner / writer / hiring_reviewer) and 7 unchanged (system / requirements / evidence / tailor_cv / targeted_rewriter / validator / styles); this verifies feature 007's hash-change → new-version pipeline picks up feature 008's prompt edits correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial verification — start immediately.
- **Foundational (Phase 2)**: depends on Phase 1. **BLOCKS all user stories** — both the new Pydantic model and the fixture files are needed by US1, US2, and US3 tests.
- **User Story 1 (Phase 3)**: depends on Phase 2. Independently testable via mocked LLM and canned response JSON. T007 (build_prompt test) can be written in parallel with T008 (parse test) and T009 (positioning correctness test) — all three target different test methods in the same file.
- **User Story 2 (Phase 4)**: depends on Phase 2 + uses the same `role_positioning` model as US1 (it reads what US1 writes). US2 tests can be written in parallel with US1 implementation as long as T013 (config tests) lands before T017/T018 (which read `writer_rules`).
- **User Story 3 (Phase 5)**: depends on Phase 2. Independent of US1 and US2 implementations — US3 only needs `state.job_context.raw_job_text` (already populated by `load_job`) and the `LetterReviewReport` parser. The integration value comes from US3 catching what US1+US2 might miss, but the stage itself doesn't depend on positioning being present in the plan.
- **Polish (Phase 6)**: depends on US1+US2+US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI).
- US1: T010 (planner prompt) and T011 (planner build_prompt) can be done in either order; both must land before T012 verification.
- US2: T014 (WriterRules model) → T015 (merge propagation) → T013 verification → T017 (writer prompt) → T018 (writer build_prompt) → T019 verification.
- US3: T023 (review prompt) and T024 (review build_prompt) can be done in either order; both must land before T025 verification.

---

## Parallel Opportunities

```bash
# Phase 2: fixture files can be created in parallel with the test+model work.
Task T002: Write RolePositioning tests in tests/unit/test_plan_content.py
Task T004: Create AI/ML infrastructure fixture       # [P] — different file
Task T005: Create biomedical-ML project fixture      # [P] — different file

# Phase 3 US1 — three test methods in the same file (write sequentially),
# but T007 (build_prompt test) is independent of T008/T009 (parse tests):
Task T007: test_planner_prompt_includes_raw_job_text_and_positioning_instructions  # [P]
Task T008: test_planner_parse_accepts_role_positioning_subobject
Task T009: test_planner_positions_infrastructure_first_on_ml_infra_fixture

# Phase 4 US2 — config tests and writer-prompt tests are in different files:
Task T013: TestWriterRules in tests/unit/test_config_models.py   # [P]
Task T016: test_writer_prompt_includes_positioning_block_and_writer_rules in tests/unit/test_write_letter.py  # [P]

# Phase 5 US3 — three test methods in the same file (write sequentially):
Task T020: test_hiring_review_prompt_includes_raw_job_text  # [P] — different file from US1/US2 tests
Task T021: test_hiring_review_prompt_lists_positioning_dimensions
Task T022: test_hiring_review_flags_role_match_and_opening_when_mispositioned

# Phase 6: summaries extension, ENGINEERING.md update, and Langfuse sync are all in different files / are independent operations:
Task T026: Extend utils/summaries.py                 # [P]
Task T027: Update ENGINEERING.md                     # [P] — different file
Task T031: jobagent prompts sync --label staging     # [P] — independent of code
```

---

## Implementation Strategy

### MVP: User Story 1 + User Story 2 (both Priority P1)

1. Complete Phase 1 (trivial verification)
2. Complete Phase 2 (Foundational) — new model + fixtures
3. Complete Phase 3 (US1) — planner positioning emitted
4. Complete Phase 4 (US2) — writer consumes positioning
5. **STOP**: at this point letters generated for the AI/ML infrastructure fixture lead with infrastructure framing and avoid banned phrases. The improvement is observable from `letter.md` and from `artifacts/content_plan.json::role_positioning`. US3 below adds the safety net.

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ✓ (new schema + fixtures)
2. Phase 3 (US1) → Planner records explicit positioning ✓
3. Phase 4 (US2) → Writer consumes positioning ✓ — MVP shippable
4. Phase 5 (US3) → Hiring review catches and rewrites positioning failures ✓
5. Phase 6 → Docs, summaries extension, full sweep, Langfuse sync ✓

### Parallel Team Strategy

With two contributors after Phase 2 lands:

- Contributor A: US1 (planner positioning) — owns `prompts/planner.md` and `stages/plan_content.py`.
- Contributor B: US3 (hiring review) — owns `prompts/hiring_reviewer.md` and `stages/hiring_review.py`; US3 has zero dependency on US1/US2 implementations (only needs the already-loaded `job_context.raw_job_text`).
- Either contributor picks up US2 (writer) after US1's `role_positioning` field exists; US2's writer changes are mechanical given the new field.

---

## Notes

- `[P]` = different files, safe to run in parallel with other [P] tasks in the same phase.
- `[USN]` = maps to user story N in spec.md.
- **No new pipeline stage, no new artefact file, no new CLI command** — the entire feature ships behind unchanged operator-visible contracts (FR-015..FR-019). Improvement is visible in `letter.md` content, `artifacts/content_plan.json::role_positioning`, and the hiring-review weaknesses list.
- **Feature 007 prompt registry hashes flip automatically**: T010, T017, T023 edit `planner.md` / `writer.md` / `hiring_reviewer.md`. The runtime stage spans (feature 006) carry the new hashes immediately; `jobagent prompts sync` (T031) pushes them to Langfuse as new versions.
- **Schema discipline (FR-021)**: exactly two schema additions (`RolePositioning`, `WriterRules`), each justified because the existing structures cannot represent the new information. Every other behaviour change lives in prompt content or in `build_prompt` formatters.
- **Privacy invariant preserved**: T026 adds only a `role_positioning_present: bool` to the content-plan summary — the prose contents of `primary_selling_point`, `opening_angle`, etc. never appear on spans in default summary mode (feature 006 FR-018 invariant carried forward).
- **Banned-phrase list lives in config, not in prompts** (FR-022): `prompts/writer.md` uses `{banned_phrases}` and `{tool_density_max}` placeholders; `build_prompt` resolves them from `state.config.writer_rules`. Operators can customise per template.
