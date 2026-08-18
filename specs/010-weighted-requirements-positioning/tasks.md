# Tasks: Weighted Requirements + Refined Role Positioning

**Input**: Design documents from `/specs/010-weighted-requirements-positioning/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-021..FR-027 enumerate seven required automated tests and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task. All tests use mocked LLM responses (canned JSON dicts); no real Anthropic calls in unit tests.

**Organization**: Tasks grouped by user story. US1 and US2 are both Priority P1 (the MVP pair: US1 enriches per-requirement structure; US2 enriches the per-plan positioning structure). US3 (P3) is backward-compat coverage — mostly satisfied by tests already in US1/US2, plus one explicit unknown-field test for the second model.

**Scope discipline**: This feature touches exactly 3 source files (`models/state.py`, `stages/extract_requirements.py`, `stages/plan_content.py`, `stages/hiring_review.py`) + 3 prompt files (`requirements.md`, `planner.md`, `hiring_reviewer.md`) + 3 test files (`test_extract_requirements.py`, `test_plan_content.py`, `test_hiring_review.py`). No new files. No new dependencies. No new fixtures.

---

## Phase 1: Setup

**Purpose**: No new dependencies. One verification step to capture the baseline test count for the Phase 6 sweep.

- [X] T001 Verify the 239-test baseline (post-feature-009) passes by running `.venv/bin/pytest tests/ --tb=short` and capture the count for the Phase 6 comparison

---

## Phase 2: Foundational

**Purpose**: NONE. US1 and US2 evolve independent models (`RequirementExtraction` vs `RolePositioning`); the three new enums are only used by `RequirementItem` (part of US1). No blocking prerequisite spans the two stories.

(No foundational tasks. Skip directly to Phase 3.)

---

## Phase 3: User Story 1 — Weighted Requirement Extraction (Priority: P1) 🎯 MVP-part-1

**Goal**: Every extracted requirement carries `id`, `text`, `priority`, `category`, `evidence_needed`, and an optional `source_excerpt`. The new `RequirementItem` Pydantic model is introduced; `RequirementExtraction` gains a `requirement_items: list[RequirementItem]` field plus two model validators (uniqueness + legacy back-fill). Legacy payloads continue to load with documented defaults.

**Independent Test**: Construct a canned LLM response dict with `requirement_items` filled (4 items spanning all enum values); call `parse_response(data)`; assert each item validates, IDs are unique, `priority`/`category`/`evidence_needed` are correctly typed as enums. Separately construct a legacy payload (no `requirement_items`); assert it loads cleanly with `requirement_items = []`.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T008

- [X] T002 [P] [US1] Write failing test `test_requirement_extraction_parses_mocked_llm_output_with_items` in `tests/unit/test_extract_requirements.py` — construct a canned response dict with `core_requirement="..."`, `requirement_items=[{"id":"R1","text":"Design and operate scalable cloud infrastructure","priority":"high","category":"core","evidence_needed":"required","source_excerpt":"Design and operate scalable cloud..."}, {"id":"R2",...,"priority":"medium","category":"technical","evidence_needed":"preferred"}, {"id":"R3",...,"priority":"low","category":"optional","evidence_needed":"optional"}]`; call `parse_response(data)`; assert each item parses, `priority`/`category`/`evidence_needed` are enum instances (not bare strings); assert `source_excerpt` is the verbatim text for items that have one and None for items that don't (FR-001, FR-004, FR-021)
- [X] T003 [US1] Write failing test `test_requirement_item_defaults_for_missing_optional_fields` in `tests/unit/test_extract_requirements.py` — construct a `RequirementItem` JSON with only the required fields (`id`, `text`, `priority`, `category`, `evidence_needed`); assert `source_excerpt` defaults to None (FR-004)
- [X] T004 [US1] Write failing test `test_requirement_item_invalid_priority_value_raises` in `tests/unit/test_extract_requirements.py` — construct a `RequirementItem` JSON with `priority="urgent"` (not in the enum); assert `pydantic.ValidationError` raised; assert error message mentions "priority" or "enum" (FR-002, FR-021)
- [X] T005 [P] [US1] Write failing test `test_requirement_extraction_legacy_payload_loads` in `tests/unit/test_extract_requirements.py` — construct a payload matching the pre-feature-010 shape (`core_requirement`, `technical_requirements`, etc., NO `requirement_items` key); call `RequirementExtraction.model_validate(payload)`; assert load succeeds; assert `requirement_items == []`; assert legacy fields populated correctly (FR-018, FR-023)
- [X] T006 [US1] Write failing test `test_requirement_item_duplicate_ids_raise` in `tests/unit/test_extract_requirements.py` — construct a payload with two `requirement_items` sharing `id="R1"`; assert `pydantic.ValidationError` (or `ValueError`) raised; assert error mentions "duplicate" or "id" (FR-005)
- [X] T007 [US1] Write failing test `test_requirement_extraction_backfills_all_requirements_from_items` in `tests/unit/test_extract_requirements.py` — construct a payload with `requirement_items=[...]` and NO `all_requirements` field; assert load succeeds; assert `extraction.all_requirements` is non-empty AND its length equals the items length; assert each back-filled `Requirement` has `label=<item.category.value>`, `text=<item.text>`, and `priority` mapped from the enum (high→1, medium→2, low→3) — verifies the `_backfill_all_requirements_from_items` validator (FR-018, research §R9)

### Implementation for User Story 1

- [X] T008 [US1] Add three new `str` enums to `src/bewerbungs_agent/models/state.py` per data-model.md §1: `Priority` (high/medium/low), `RequirementCategory` (core/technical/collaboration/domain/optional), `EvidenceNeeded` (required/preferred/optional). Placement: alongside the existing domain enums; import `from enum import Enum` if not already present
- [X] T009 [US1] Add the `RequirementItem` Pydantic model to `src/bewerbungs_agent/models/state.py` per data-model.md §2 (with `extra="forbid"`, `id: str = Field(..., min_length=1, max_length=16)`, `text: str`, the three enum-typed fields, and `source_excerpt: str | None = Field(default=None, max_length=200)`). Placement: directly above the existing `RequirementExtraction` class
- [X] T010 [US1] Extend `RequirementExtraction` in `src/bewerbungs_agent/models/state.py` per data-model.md §3 — (a) add `requirement_items: list[RequirementItem] = Field(default_factory=list)` as the last field; (b) add `_enforce_unique_item_ids` `@model_validator(mode="after")` raising `ValueError` on duplicate IDs; (c) add `_backfill_all_requirements_from_items` `@model_validator(mode="after")` that populates `all_requirements` from `requirement_items` when the legacy list is empty (priority map: high→1, medium→2, low→3); the priority comparison uses the enum, not strings
- [X] T011 [US1] Update `prompts/requirements.md` per contracts §2 — add a new section "Weighted requirement items" instructing the LLM to produce a `requirement_items` array with id/text/priority/category/evidence_needed (+ optional source_excerpt ≤200 chars); add priority calibration guidance (high/medium/low); add evidence-needed calibration (required/preferred/optional); include the reminder that legacy summary fields (`core_requirement`, `technical_requirements`, etc.) MUST also still be produced for backward compat
- [X] T012 [US1] Confirm all US1 tests (T002–T007) pass; confirm the existing 239-test baseline still passes (no regression — `requirement_items=[]` default keeps legacy paths untouched)

**Checkpoint**: Every extracted requirement is individually addressable, priority-weighted, category-tagged, and evidence-need-rated. The MVP foundation for downstream weighting is in place. US2 below makes the planner consume the new structure and refines `RolePositioning`.

---

## Phase 4: User Story 2 — Refined RolePositioning + Planner Consumption + Hiring-Review Surface (Priority: P1) 🎯 MVP-part-2

**Goal**: `RolePositioning` is normalised to the seven canonical field names (`role_family`, `primary_selling_point`, `secondary_selling_points`, `opening_angle`, `emphasise`, `deemphasise`, `risky_or_gap_areas`) with Pydantic aliases preserving backward-compat for feature-008-shape artifacts. The planner consumes `requirement_items` (priority-ordered) and emits the renamed positioning. The hiring-review prompt surfaces `risky_or_gap_areas` in the existing content-plan summary block (feature 009).

**Independent Test**: Construct a `RolePositioning` from a new-shape dict and from an old-shape (feature 008) dict; assert both load and produce identical field values. Render the planner's `build_prompt` for a state with `requirement_items`; assert the prompt contains the `[R1, priority=high, ...]` ordering. Render the hiring-review `build_prompt` for a state whose `role_positioning.risky_or_gap_areas` is non-empty; assert the prompt contains a `risky_or_gap_areas:` line in the content-plan summary; render with empty list; assert the line is omitted.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T019

- [X] T013 [P] [US2] Write failing test `test_role_positioning_accepts_new_field_names` in `tests/unit/test_plan_content.py` — construct a dict using ONLY the new canonical names (`role_family`, `emphasise`, `deemphasise`, `risky_or_gap_areas`, plus the three unchanged fields); call `RolePositioning.model_validate(data)`; assert each attribute equals the input value; assert `risky_or_gap_areas` is the populated list (FR-007, FR-022)
- [X] T014 [US2] Write failing test `test_role_positioning_accepts_legacy_field_names_via_alias` in `tests/unit/test_plan_content.py` — construct a dict using the feature-008 names (`primary_role_family`, `topics_to_emphasise`, `topics_to_deemphasise`, NO `risky_or_gap_areas`); call `RolePositioning.model_validate(data)`; assert `rp.role_family == data["primary_role_family"]`, `rp.emphasise == data["topics_to_emphasise"]`, `rp.deemphasise == data["topics_to_deemphasise"]`, `rp.risky_or_gap_areas == []` (FR-019, FR-024)
- [X] T015 [US2] Write failing test `test_role_positioning_risky_or_gap_areas_defaults_to_empty` in `tests/unit/test_plan_content.py` — construct a minimal `RolePositioning` with only the three required fields (`role_family`, `primary_selling_point`, `opening_angle`); assert `risky_or_gap_areas == []` (FR-008, FR-019)
- [X] T016 [US2] Write failing test `test_role_positioning_unknown_field_forbidden` in `tests/unit/test_plan_content.py` — construct a dict with all required new-shape fields PLUS a typo field `role_familly: "x"`; assert `pydantic.ValidationError` raised (FR-020, FR-027)
- [X] T017 [US2] Write failing test `test_planner_build_prompt_renders_requirement_items_in_priority_order` in `tests/unit/test_plan_content.py` — build a state with `requirements.requirement_items` containing items at all three priorities (intentionally out of order: low, high, medium); call `plan_content.build_prompt(state)`; assert the prompt contains substring `"# Weighted Requirements"`; assert the high-priority item appears BEFORE the medium-priority item in the prompt text (substring index check) which appears BEFORE the low-priority item; assert each item line includes `priority=`, `evidence=`, `category=` markers (contracts §6.1)
- [X] T018 [US2] Write failing regression test `test_planner_produces_infrastructure_first_role_family_on_fixture` in `tests/unit/test_plan_content.py` — construct a canned LLM response (the full ContentPlan JSON including a correctly-positioned `role_positioning` block with `role_family="AI/ML platform engineering"`, biomedical in `secondary_selling_points`, biomedical in `deemphasise`); call `parse_response(data, soft_skill_max=3)`; assert `plan.role_positioning.role_family.lower()` contains "platform" or "infrastructure" AND does NOT contain "biomedical" AND does NOT contain "data science"; assert "biomedical" appears only in `secondary_selling_points` (not in `primary_selling_point` or `role_family`); this is the deterministic GSK-style regression guard against the field-rename (FR-011, FR-026, SC-005)

### Implementation for User Story 2

- [X] T019 [US2] Update `RolePositioning` in `src/bewerbungs_agent/models/state.py` per data-model.md §4 — add `model_config = ConfigDict(populate_by_name=True, extra="forbid")`; rename fields with input aliases: `role_family: str = Field(..., alias="primary_role_family")`, `emphasise: list[str] = Field(default_factory=list, alias="topics_to_emphasise")`, `deemphasise: list[str] = Field(default_factory=list, alias="topics_to_deemphasise")`; add new field `risky_or_gap_areas: list[str] = Field(default_factory=list)`; preserve unchanged fields (`primary_selling_point`, `secondary_selling_points`, `opening_angle`); ensure `ConfigDict` is imported from `pydantic`
- [X] T020 [US2] Update `prompts/planner.md` per contracts §3 — (a) update field-name examples to use `role_family` / `emphasise` / `deemphasise` instead of the old names; (b) add a new bullet describing `risky_or_gap_areas` (topics the writer should treat carefully or avoid because the candidate has no strong evidence); (c) add the instruction "When `requirement_items` is provided, treat it as the priority-ordered source of truth — sections in your plan should cover `high`-priority items first and ensure each `required` evidence_needed item has at least one supporting claim"; (d) extend the honest-gap rule to also list the topic in `RolePositioning.risky_or_gap_areas`
- [X] T021 [US2] Update `stages/plan_content.py::build_prompt` per contracts §6.1 — when `state.requirements.requirement_items` is non-empty, render a new `# Weighted Requirements (priority-ordered)` block BEFORE the existing `# Extracted Requirements` block; format each item as `- [{id}, priority={priority}, evidence={evidence_needed}, category={category}] {text}` then `  source: "{source_excerpt}"` on a continuation line when `source_excerpt` is non-None; sort items by `priority` descending (high → medium → low) then by `id` ascending. When `requirement_items` is empty (legacy state), skip the new block entirely — guarantees zero regression for tests using legacy fixtures
- [X] T022 [US2] Update `prompts/hiring_reviewer.md` per contracts §4 — (a) update the example positioning field names in the prompt text to match new canonical names; (b) extend the `critical_requirements_underweighted` dimension bullet to note: "When a critical requirement appears in the plan's `risky_or_gap_areas`, evaluate whether the letter handles it appropriately (brief factual acknowledgement or omission) — do not flag it as underweighted just because it has thin coverage; that's intentional."
- [X] T023 [US2] Update `stages/hiring_review.py::build_prompt` per contracts §7 — within the existing content-plan summary block (feature 009), update the Role Positioning sub-block label strings from `primary_role_family`/`topics_to_emphasise`/`topics_to_deemphasise` to `role_family`/`emphasise`/`deemphasise`; the underlying attribute reads change correspondingly. Add ONE new conditional line `- risky_or_gap_areas: <list>` that emits ONLY when `rp.risky_or_gap_areas` is non-empty (graceful omission per feature 009 discipline)
- [X] T024 [P] [US2] Write failing tests for hiring-review propagation in `tests/unit/test_hiring_review.py` — add 2 tests: (1) `test_hiring_review_prompt_surfaces_risky_or_gap_areas_when_present` builds a state whose `content_plan.role_positioning.risky_or_gap_areas = ["claims of deep on-call experience"]`; calls `build_prompt(state)`; asserts prompt contains substring `"risky_or_gap_areas"` and the verbatim list entry; (2) `test_hiring_review_prompt_omits_risky_or_gap_areas_when_empty` builds a state whose `role_positioning.risky_or_gap_areas = []`; asserts prompt does NOT contain substring `"risky_or_gap_areas"` (FR-010, FR-025)
- [X] T025 [US2] Confirm all US2 tests (T013–T018, T024) pass; confirm US1 tests still pass; confirm the existing 239-test baseline still passes

**Checkpoint**: `RolePositioning` is normalised with backward-compat aliases. The planner consumes weighted requirements; the hiring review surfaces risky-or-gap topics. The MVP pair (US1+US2) delivers the user-visible value: an AI/ML infrastructure role is positioned as infrastructure (not biomedical-data-science), reviewers see structured weighting, and downstream rewrite routing inherits the structure from features 008/009.

---

## Phase 5: User Story 3 — Backward Compatibility (Priority: P3)

**Goal**: Validate the backward-compat invariants explicitly. Most of US3's surface is already covered by tests in US1 (T005, T007) and US2 (T014, T015). One remaining test ensures `RequirementExtraction` also forbids unknown fields (parallel to T016 for `RolePositioning`).

**Independent Test**: Construct a `RequirementExtraction` payload containing a deliberate typo field; assert `pydantic.ValidationError` raised.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE no implementation (US3 is test-only verification)

- [X] T026 [P] [US3] Write test `test_requirement_extraction_unknown_field_forbidden` in `tests/unit/test_extract_requirements.py` — construct a valid payload PLUS a typo field `corre_requirement: "x"` (misspelled `core_`); assert `pydantic.ValidationError` raised on `RequirementExtraction.model_validate(data)`; assert error mentions the typo field name (FR-020, FR-027 second case)

### Verification for User Story 3

- [X] T027 [US3] Confirm US3 test (T026) passes; confirm the cumulative backward-compat surface (T005 legacy RequirementExtraction loads + T007 back-fill + T014 legacy RolePositioning loads via alias + T015 risky_or_gap_areas defaults + T016 + T026 unknown-fields forbidden) covers FR-018 / FR-019 / FR-020 / FR-023 / FR-024 / FR-027 end-to-end

**Checkpoint**: Backward-compat tested across both new and old payload shapes for both evolved models. Operators can re-load any artefact from any earlier feature without breakage; typos still raise.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 [P] Update `ENGINEERING.md` — add a brief subsection to Section 16 (Hiring-Manager Review) and/or the appropriate existing data-model section noting feature 010's additions: `RequirementItem` with three new enums, the `requirement_items` field on `RequirementExtraction` with back-fill validator, the `RolePositioning` field-rename with Pydantic aliases preserving feature-008-shape JSON, the new `risky_or_gap_areas` field, the per-requirement weighted block in the planner prompt, and the surfaced `risky_or_gap_areas` line in the hiring-review prompt. Keep it short (one paragraph + a small table)
- [X] T029 Run the full test suite `.venv/bin/pytest tests/ --tb=short`; expected count = previous baseline (239) + 6 US1 + 6 US2 + 1 US3 = 252 passed; halt and fix if any regression
- [X] T030 Run static checks on the files this feature touches: `.venv/bin/ruff check src/bewerbungs_agent/models/state.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/hiring_review.py src/bewerbungs_agent/stages/extract_requirements.py tests/unit/test_extract_requirements.py tests/unit/test_plan_content.py tests/unit/test_hiring_review.py` and `.venv/bin/mypy src/bewerbungs_agent/models/state.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/hiring_review.py src/bewerbungs_agent/stages/extract_requirements.py`; fix any errors introduced by this feature (do NOT fix pre-existing errors)
- [X] T031 Run quickstart §7 manual smoke test (or document explicit deferral) — `jobagent run --job data/examples/jobs/sample_ml_infrastructure.md --template default_de_neutral`; jq inspect `outputs/<run_id>/artifacts/requirements.json` for `requirement_items` array with `priority`/`category`/`evidence_needed` populated; jq inspect `outputs/<run_id>/artifacts/content_plan.json` for `role_positioning` with new field names AND `risky_or_gap_areas`; grep `role_family` for "platform" / "infrastructure" and confirm absence of "biomedical" / "data science"
- [X] T032 [P] Push the three updated prompt versions to Langfuse: `uv run jobagent prompts sync --label staging`; expected output: `"Summary: 3 created, 7 unchanged, 0 relabeled, 0 failed."` — the three created are `bewerbungs-agent/requirements`, `bewerbungs-agent/planner`, `bewerbungs-agent/hiring_reviewer` (FR-015 expected hash-flip signal). If the output reports more or fewer than 3 created, an unintended prompt was modified; investigate with `git diff prompts/` before continuing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial verification — start immediately.
- **Foundational (Phase 2)**: NONE. Skip directly to Phase 3.
- **US1 (Phase 3)**: independent. Adds new enums + `RequirementItem` + extends `RequirementExtraction`. Doesn't touch `RolePositioning`. Independently testable.
- **US2 (Phase 4)**: depends on US1 ONLY for one task — T017 (planner build_prompt renders `requirement_items`) needs `RequirementItem` to exist. All other US2 tasks (RolePositioning field-rename, planner-prompt field-name updates, hiring-review surfacing of `risky_or_gap_areas`) are independent of US1.
- **US3 (Phase 5)**: independent — one explicit test that complements US1 and US2's existing backward-compat tests.
- **Polish (Phase 6)**: depends on US1+US2+US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI).
- US1: T008 (enums) → T009 (RequirementItem model) → T010 (extend RequirementExtraction with field + validators) → T011 (requirements.md prompt) → T012 verification.
- US2: T019 (RolePositioning model rename + alias + new field) → T020 (planner.md) → T021 (plan_content.py build_prompt) → T022 (hiring_reviewer.md) → T023 (hiring_review.py build_prompt) → T025 verification. T024 (hiring-review tests) can be written before T023 (TDD).
- US3: T026 (test) → T027 (verify); T026 will already pass because `extra="forbid"` is pre-existing on `RequirementExtraction`. T026's purpose is explicit coverage of FR-027's second case.

---

## Parallel Opportunities

```bash
# Phase 1: single task.

# Phase 3 US1 — failing tests can be drafted in parallel (different test methods,
# but same file — sequential drafting recommended for clean line ordering):
Task T002: test_requirement_extraction_parses_mocked_llm_output_with_items
Task T005: test_requirement_extraction_legacy_payload_loads  # [P] — semantically independent

# Phase 4 US2 — RolePositioning tests are in test_plan_content.py;
# hiring-review tests are in test_hiring_review.py (different file → parallel):
Task T013: test_role_positioning_accepts_new_field_names                       # [P]
Task T024: test_hiring_review_prompt_surfaces_risky_or_gap_areas_when_present  # [P] — different file

# US1 and US2 themselves can run in parallel after Phase 1 lands (different
# model targets in state.py, different prompts) — except T017 (planner consumes
# requirement_items) which strictly needs US1's RequirementItem to exist.

# Phase 5 US3 — single test in a US1 test file:
Task T026: test_requirement_extraction_unknown_field_forbidden  # [P]

# Phase 6 polish:
Task T028: Update ENGINEERING.md          # [P]
Task T032: jobagent prompts sync          # [P] — independent operation
```

---

## Implementation Strategy

### MVP: User Story 1 + User Story 2 (both Priority P1)

1. Complete Phase 1 (verify baseline)
2. Skip Phase 2 (none)
3. Complete Phase 3 (US1) — weighted requirement structure shipped
4. Complete Phase 4 (US2) — refined positioning + planner consumption + hiring-review surface
5. **STOP**: at this point the artifacts under `outputs/<run_id>/artifacts/` carry the new weighted structure AND the refined positioning. The planner uses priority-ordered weighted requirements; the hiring review sees risky-or-gap topics. US3 below is test-only.

### Incremental Delivery

1. Phase 1 → verification ✓
2. Phase 3 (US1) → weighted requirement extraction available ✓ (planner may not yet consume it — but the data is in artifacts)
3. Phase 4 (US2) → planner consumes weighted items; positioning normalised; hiring review sees risky topics ✓
4. Phase 5 (US3) → backward-compat coverage explicit ✓
5. Phase 6 → docs, full sweep, prompt-registry push ✓

### Parallel Team Strategy

With two contributors after Phase 1 lands:

- Contributor A: US1 (enums + RequirementItem + extract_requirements + requirements.md)
- Contributor B: US2 (RolePositioning + planner.md + plan_content.py + hiring_reviewer.md + hiring_review.py + the hiring-review tests)
- T017 in US2 depends on US1's `RequirementItem` existing — schedule it after US1 ships the model (T009) OR mock the model in the test pending US1
- Contributor C or either of A/B picks up US3 (T026, T027) — tiny scope, can land last

---

## Notes

- `[P]` = different files (or semantically independent within the same file), safe to draft in parallel.
- `[USN]` = maps to user story N in spec.md.
- **No new schema files, no new pipeline stage, no new artefact file, no new CLI command** — the entire feature ships behind unchanged operator-visible contracts (FR-012..FR-017). Improvement is visible inside `requirements.json` and `content_plan.json` artifacts and (when observability is enabled) on Langfuse spans for the three updated prompts.
- **Feature 007 prompt registry**: T011 + T020 + T022 edit three prompts. The next `jobagent prompts sync` (T032) MUST report `3 created, 7 unchanged`. The three created are `bewerbungs-agent/requirements`, `bewerbungs-agent/planner`, `bewerbungs-agent/hiring_reviewer`. Any other count signals an unintended prompt edit — investigate before merging.
- **Backward-compat without migration**: T010's `_backfill_all_requirements_from_items` validator + T019's Pydantic aliases mean legacy artifacts (pre-feature-010 and feature-008-shape) load cleanly with no migration step. The first feature-010 run RE-SAVES artifacts in the canonical shape, gradually rolling forward.
- **`extra="forbid"` discipline preserved**: T016 + T026 explicitly test that typo fields raise. The discipline already holds on both `RequirementExtraction` and `RolePositioning` from earlier features; these tests pin the invariant after the feature-010 changes.
- **Writer is intentionally NOT touched** (FR-013): the writer continues to consume positioning via `ContentPlan.role_positioning`. The new `risky_or_gap_areas` field rides on that object; the writer's existing prompt rules don't reference it. Surfacing it to the writer is OUT of scope.
- **Test count math**: T002–T007 add 6 tests (US1); T013–T018 add 6 tests (US2); T024 adds 2 tests; T026 adds 1 test (US3) = 15 new tests. Expected final: 239 + 15 = 254.
