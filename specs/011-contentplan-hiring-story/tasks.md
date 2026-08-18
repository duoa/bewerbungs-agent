# Tasks: ContentPlan as a Hiring Story

**Input**: Design documents from `/specs/011-contentplan-hiring-story/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-024..FR-030 explicitly mandate seven automated tests and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task. All tests use mocked LLM responses (canned JSON dicts); no real Anthropic calls in unit tests.

**Organization**: Tasks grouped by user story. US1 (P1) ships the schema + planner integration as the MVP; US2 (P2) wires the per-paragraph density limits into the writer prompt; US3 (P3) is explicit backward-compat coverage (mostly automatic from the schema design).

**Scope discipline**: This feature touches exactly 3 source files (`models/state.py`, `stages/plan_content.py`, `stages/write_letter.py`) + 2 prompt files (`planner.md`, `writer.md`) + 2 test files (`test_plan_content.py`, `test_write_letter.py`). No new files. No new dependencies. No new fixtures. The `hiring_reviewer.md` prompt and `stages/hiring_review.py` are explicitly NOT edited.

---

## Phase 1: Setup

**Purpose**: No new dependencies. One verification step to capture the baseline test count for the Phase 6 sweep.

- [X] T001 Verify the 254-test baseline (post-feature-010) passes by running `.venv/bin/pytest tests/ --tb=short` and capture the count for the Phase 6 comparison

---

## Phase 2: Foundational

**Purpose**: NONE. US1 introduces the new schema + planner emission together; US2 (writer-side consumption) and US3 (backward-compat tests) build on US1's schema but US1 itself has no blocking prerequisite.

(No foundational tasks. Skip directly to Phase 3.)

---

## Phase 3: User Story 1 — Planner Emits a Story-Shaped Content Plan (Priority: P1) 🎯 MVP

**Goal**: A new `ParagraphPlan` Pydantic model lands; `ContentPlan` gains `letter_thesis: str | None` + `paragraphs: list[ParagraphPlan]` + three model validators (evidence_refs ≤ max_claims, opening max_claims ∈ {1,2}, evidence_refs trace to evidence_map). The planner stage's `build_prompt` updates its reminder text to instruct the LLM about the new fields; the planner node adds a stage-level cross-reference check for `requirement_ids` against `requirement_items` (feature 010). The `planner.md` prompt rewrites to describe the new hiring-story output.

**Independent Test**: Construct a canned LLM response containing `letter_thesis` + 3 `paragraphs` (each with required + optional fields populated); call `parse_response(data)`; assert parse succeeds and assert each paragraph's `main_message` is a single non-empty string ≤ 300 chars. Separately construct a canned response where `paragraphs[0].max_claims=3`; assert parse raises (opening rule). Construct another where `paragraphs[0].evidence_refs` has 4 entries but `max_claims=2`; assert parse raises.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T009

- [X] T002 [P] [US1] Write failing test `test_paragraph_plan_main_message_is_single_string` in `tests/unit/test_plan_content.py` — construct a `ParagraphPlan` with valid required fields; assert `main_message` is a `str` (not list); assert validation rejects a 301-char `main_message` (max_length); assert validation rejects empty string (min_length=1) (FR-004, FR-024)
- [X] T003 [US1] Write failing test `test_paragraph_plan_unknown_field_forbidden` in `tests/unit/test_plan_content.py` — construct a `ParagraphPlan` with all required fields plus a typo field `purpoze: "x"`; assert `ValidationError` raised (FR-023, FR-029)
- [X] T004 [US1] Write failing test `test_paragraph_plan_max_claims_max_tools_bounds` in `tests/unit/test_plan_content.py` — construct `ParagraphPlan` with `max_claims=0` and `max_claims=9`; assert both raise `ValidationError` (bounds ge=1, le=8). Same for `max_tools=-1` and `max_tools=13` (bounds ge=0, le=12) (FR-008, FR-009)
- [X] T005 [P] [US1] Write failing test `test_content_plan_evidence_refs_exceeding_max_claims_raises` in `tests/unit/test_plan_content.py` — construct a `ContentPlan` with one paragraph whose `evidence_refs` has 4 entries and `max_claims=2`; populate `evidence_map.items` with matching claims; assert `ValidationError` raised; assert error mentions paragraph index AND `max_claims` (FR-010, FR-027)
- [X] T006 [US1] Write failing test `test_content_plan_opening_paragraph_max_claims_must_be_one_or_two` in `tests/unit/test_plan_content.py` — construct a `ContentPlan` with `paragraphs[0].max_claims=3` (otherwise valid); assert `ValidationError` raised; assert error mentions "opening" and `max_claims=3`. Verify `max_claims=1` and `max_claims=2` both parse cleanly on the opening paragraph (FR-012)
- [X] T007 [US1] Write failing test `test_content_plan_paragraph_evidence_refs_not_in_evidence_map_raises` in `tests/unit/test_plan_content.py` — construct a `ContentPlan` with `evidence_map.items=[{claim: "Built scalable platforms", ...}]` and one paragraph whose `evidence_refs=["Built scalable platforms", "Some other claim"]`; assert `ValidationError` raised; assert error mentions paragraph index AND the offending claim text (data-model.md §3.3, FR-006)
- [X] T008 [US1] Write failing test `test_opening_paragraph_main_message_references_role_family` in `tests/unit/test_plan_content.py` — construct a canned `ContentPlan` JSON with `role_positioning.role_family="AI/ML platform engineering"` and `paragraphs[0].main_message="I build the AI/ML infrastructure ..."`; call `parse_response(data, soft_skill_max=3)`; assert parse succeeds; assert the opening `main_message.lower()` contains a substring from {"infrastructure", "platform", "AI/ML", "software"} AND does NOT contain {"biomedical", "data science"} — the deterministic GSK-style regression guard against opening drift on the new structure (FR-011, FR-025, SC-003)

### Implementation for User Story 1

- [X] T009 [US1] Add the `ParagraphPlan` Pydantic model to `src/bewerbungs_agent/models/state.py` per data-model.md §1 — with `model_config = ConfigDict(extra="forbid")`, eight fields (`purpose`, `main_message`, `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise`, `max_claims`, `max_tools`) with documented field constraints. Placement: directly above the `ContentPlan` class
- [X] T010 [US1] Extend `ContentPlan` in `src/bewerbungs_agent/models/state.py` per data-model.md §2 — append two new fields at the end of the existing model: `letter_thesis: str | None = Field(default=None, max_length=300)` and `paragraphs: list[ParagraphPlan] = Field(default_factory=list)`. Do NOT modify any existing fields. Confirm `model_config` is explicitly `ConfigDict(extra="forbid")` (add if not already explicit, to preserve the discipline)
- [X] T011 [US1] Add three `@model_validator(mode="after")` methods to `ContentPlan` per data-model.md §3 — `_validate_evidence_refs_within_max_claims` (raises on any paragraph where `len(evidence_refs) > max_claims`), `_validate_opening_paragraph_max_claims` (raises when `paragraphs` is non-empty AND `paragraphs[0].max_claims not in (1, 2)`), `_validate_paragraph_evidence_refs_in_evidence_map` (raises when any paragraph's `evidence_refs` entry is not in `evidence_map.items`). Each error message must name the paragraph index AND the offending field/value per data-model.md examples
- [X] T012 [US1] Update `stages/plan_content.py::build_prompt` per contracts §4 — extend ONLY the final reminder line in the user message to mention the new hiring-story fields: "Additionally produce `letter_thesis` (one sentence) and `paragraphs` (ordered list, each with purpose / main_message / max_claims / max_tools and the supporting fields). The opening paragraph MUST reflect role_positioning.role_family and opening_angle." Keep all existing prompt blocks unchanged
- [X] T013 [US1] Update `stages/plan_content.py::plan_content` (the LangGraph node function, NOT `parse_response`) per contracts §5 — AFTER the existing `parse_response` call succeeds, add a cross-reference loop: if `plan.paragraphs` is non-empty AND `state.requirements` is not None AND `state.requirements.requirement_items` is non-empty, build `valid_ids = {item.id for item in state.requirements.requirement_items}`; for each `paragraphs[i].requirement_ids` entry, if the id is not in `valid_ids`, raise `ValueError(f"Paragraph {i} ({p.purpose!r}) references requirement_id {rid!r} which is not in the run's requirement_items.")`. This satisfies FR-005 + FR-030
- [X] T014 [US1] Write failing test `test_paragraph_requirement_ids_unknown_id_raises_in_plan_content` in `tests/unit/test_plan_content.py` — construct a state with `requirements.requirement_items=[RequirementItem(id="R1", ...)]`; construct a canned planner response with `paragraphs[0].requirement_ids=["R1", "R99"]` (R99 doesn't exist); mock the LLM client; call `plan_content(state)`; assert `ValueError` raised with message mentioning paragraph index and "R99"; verify same scenario with only valid IDs (`["R1"]`) succeeds (FR-005, FR-030)
- [X] T015 [US1] Rewrite `prompts/planner.md` per contracts §2 — keep all existing sections (Source-of-truth ordering, Required output: role_positioning, Special cases, Section ordering, Previous letters note, Using weighted requirement items, Rules); add a new top-level section "Hiring-story structure (feature 011)" with the six sub-bullets per contracts §2: letter_thesis, paragraphs ordered, per-paragraph fields (purpose/main_message/requirement_ids/evidence_refs/emphasise/deemphasise/max_claims/max_tools with the calibration tables from quickstart.md §4), opening paragraph rule (paragraphs[0].max_claims ∈ {1,2}, main_message references role_family + opening_angle), high-priority requirements get dedicated paragraphs, reminder that sections MAY be empty
- [X] T016 [US1] Confirm all US1 tests (T002–T008, T014) pass — that's 9 new tests; confirm the existing 254-test baseline still passes (the new fields default safely; legacy paths use empty `paragraphs=[]` and skip the new validators' loops)

**Checkpoint**: The planner emits a story-shaped content plan with letter_thesis + structured paragraphs. The deterministic regression guard (T008) is in place. US2 below wires the writer to consume the new structure.

---

## Phase 4: User Story 2 — Per-Paragraph Density Limits Surface to the Writer (Priority: P2)

**Goal**: The writer's `build_prompt` formats a new `# Paragraph Plan` block listing each paragraph's `purpose`, `main_message`, `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise`, `max_claims`, `max_tools`. When `paragraphs` is empty (legacy plan), the block is omitted entirely — writer falls back to feature 010's behaviour. The `writer.md` prompt is extended to describe how to consume the block, including that per-paragraph `max_tools` OVERRIDES the global `writer_rules.tool_density_max` for that paragraph.

**Independent Test**: Build a state with a `ContentPlan` whose `paragraphs` has 2 entries (each with explicit `max_claims` and `max_tools`); call `write_letter.build_prompt(state)`; assert the prompt contains a `# Paragraph Plan` heading, the `purpose` strings, the `main_message` strings, the `max_claims=` integers, and the `max_tools=` integers verbatim. Separately build a state with `paragraphs=[]`; assert the prompt does NOT contain `# Paragraph Plan`.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T019

- [X] T017 [P] [US2] Write failing test `test_writer_prompt_surfaces_paragraph_max_claims_and_max_tools` in `tests/unit/test_write_letter.py` — build a `ContentPlan` with `paragraphs=[ParagraphPlan(purpose="opening", main_message="Lead with infra identity.", max_claims=1, max_tools=0, ...), ParagraphPlan(purpose="platform_credibility", main_message="Owned EKS fleets running 1000 jobs/day.", max_claims=3, max_tools=4, ...)]`; build a state with that plan; call `build_prompt(state)`; assert the prompt contains substring `"# Paragraph Plan"`, substring `"opening"`, substring `"platform_credibility"`, substring `"max_claims: 1"`, substring `"max_claims: 3"`, substring `"max_tools: 0"`, substring `"max_tools: 4"`, and each paragraph's verbatim `main_message` text (FR-009, FR-016, FR-026, SC-006)
- [X] T018 [US2] Write failing test `test_writer_prompt_omits_paragraph_block_when_paragraphs_empty` in `tests/unit/test_write_letter.py` — build a `ContentPlan` whose `paragraphs=[]` (legacy shape); build a state with that plan; call `build_prompt(state)`; assert the prompt does NOT contain `"# Paragraph Plan"`; assert the prompt still contains the existing `"# Writer Rules"` block (feature 008) — verifies the new block is purely additive and the fallback path is intact (FR-022 backward compat)

### Implementation for User Story 2

- [X] T019 [US2] Add the helper `_format_paragraphs_block(plan: ContentPlan) -> str` to `src/bewerbungs_agent/stages/write_letter.py` per contracts §6 — returns empty string when `plan.paragraphs` is empty; otherwise renders the documented block with one `## Paragraph N: purpose` section per paragraph, listing `main_message`, `requirement_ids` / `evidence_refs` / `emphasise` / `deemphasise` (only when non-empty), `max_claims`, `max_tools`. Also prepends a `Letter thesis: <text>` line when `plan.letter_thesis` is set
- [X] T020 [US2] Wire `_format_paragraphs_block` into `stages/write_letter.py::build_prompt` per contracts §6 — insert the block's output between the existing `# Writer Rules` block and the `# Writing Mode Instructions` block; do NOT modify any other section of the prompt construction
- [X] T021 [US2] Update `prompts/writer.md` per contracts §3 — keep all existing rules (role-first opening, system-level outcomes, tool-density cap, banned phrases, no-claim-outside-plan, de-emphasis discipline, language/tone, salutation/closing); add a new section "Paragraph plan consumption (feature 011)" with the four sub-bullets per contracts §3: (1) When `# Paragraph Plan` is present, write one prose paragraph per planner entry in order; (2) For each paragraph respect `main_message` as the topic intent, `max_claims` and `max_tools` as hard upper bounds, treat `max_tools` as OVERRIDING the global `writer_rules.tool_density_max` for THIS paragraph; develop `emphasise` topics, brief or omit `deemphasise`; anchor to `evidence_refs`; (3) `letter_thesis` keeps paragraphs cohesive; (4) When `# Paragraph Plan` is ABSENT (legacy), fall back to existing `sections`-based behaviour
- [X] T022 [US2] Confirm all US2 tests (T017, T018) pass; confirm US1 tests still pass; confirm the existing 254-test baseline still passes

**Checkpoint**: Writer consumes the per-paragraph plan and respects per-paragraph density caps. The MVP pair (US1+US2) delivers the end-to-end value: the planner emits a story; the writer renders it with paragraph-aware density control.

---

## Phase 5: User Story 3 — Backward Compatibility for Legacy ContentPlan Artifacts (Priority: P3)

**Goal**: Legacy `ContentPlan` JSON (no `letter_thesis`, no `paragraphs`) loads cleanly with documented defaults; existing tests using minimal plans continue to pass without modification. Unknown top-level keys still raise (preserved `extra="forbid"` discipline).

**Independent Test**: Construct a JSON document matching the pre-feature-011 `ContentPlan` shape (no `letter_thesis`, no `paragraphs`, only the existing `sections` etc.); load via `ContentPlan.model_validate(data)`; assert load succeeds and `letter_thesis is None`, `paragraphs == []`, and all legacy fields populated correctly. Construct another JSON with an unknown top-level key (e.g., `lettre_thesis` typo); assert `ValidationError` raised.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T025

- [X] T023 [P] [US3] Write failing test `test_legacy_content_plan_without_paragraphs_loads_with_defaults` in `tests/unit/test_plan_content.py` — construct a pre-feature-011 JSON with `template_id`, `selected_cv_variant`, `mode`, `sections=[...]`, `evidence_map=...`, `role_positioning=...` (using feature-010 field names) but NO `letter_thesis` and NO `paragraphs`; call `ContentPlan.model_validate(data)`; assert `plan.letter_thesis is None`, `plan.paragraphs == []`, `plan.sections` is the populated legacy list, `plan.role_positioning` is the populated RolePositioning; no exception raised (FR-022, FR-028)
- [X] T024 [US3] Write failing test `test_content_plan_unknown_field_forbidden` in `tests/unit/test_plan_content.py` — construct a valid `ContentPlan` JSON plus a typo top-level field `lettre_thesis: "typo"`; call `ContentPlan.model_validate(data)`; assert `ValidationError` raised; assert error message contains `lettre_thesis` (FR-023, FR-029)

### Verification for User Story 3

- [X] T025 [US3] Confirm US3 tests (T023, T024) pass; confirm the cumulative backward-compat surface — T023 (legacy load with defaults) + T024 (typo rejected) + the implicit non-regression test (254-test baseline continues to pass without modification of any existing test using minimal `ContentPlan`) — collectively cover FR-022, FR-023, FR-028, FR-029

**Checkpoint**: Backward-compat invariants tested explicitly. Existing artifacts and tests continue to work.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Update `ENGINEERING.md` — add a short paragraph or sub-section noting feature 011's additions: `ParagraphPlan` Pydantic model with eight fields; `ContentPlan.letter_thesis` + `ContentPlan.paragraphs` fields; three model validators (evidence_refs ≤ max_claims, opening max_claims ∈ {1,2}, evidence_refs in evidence_map); stage-level `requirement_ids` cross-reference check in `plan_content()`; writer's `_format_paragraphs_block` helper; new prompt sections in `planner.md` and `writer.md`; per-paragraph `max_tools` OVERRIDES the global `writer_rules.tool_density_max`. Place near the existing feature 010 sub-section to keep the narrative chronological
- [X] T027 Run the full test suite `.venv/bin/pytest tests/ --tb=short`; expected count = previous baseline (254) + 9 US1 + 2 US2 + 2 US3 = 267 passed; halt and fix if any regression
- [X] T028 Run static checks on the files this feature touches: `.venv/bin/ruff check src/bewerbungs_agent/models/state.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/write_letter.py tests/unit/test_plan_content.py tests/unit/test_write_letter.py` and `.venv/bin/mypy src/bewerbungs_agent/models/state.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/write_letter.py`; fix any errors introduced by this feature (do NOT fix pre-existing errors out of scope)
- [X] T029 Run quickstart §7 manual smoke test (or document explicit deferral) — `jobagent run --job data/examples/jobs/sample_ml_infrastructure.md --template default_de_neutral`; jq inspect `outputs/<run_id>/artifacts/content_plan.json` for `letter_thesis` (non-null) AND `paragraphs` (non-empty, each with `purpose`/`main_message`/`max_claims`/`max_tools`); grep opening `main_message` for "infrastructure"/"platform"; confirm opening `max_claims` is 1 or 2
- [X] T030 [P] Push the two updated prompt versions to Langfuse: `uv run jobagent prompts sync --label staging`; expected output: `"Summary: 2 created, 8 unchanged, 0 relabeled, 0 failed."` — the two created are `bewerbungs-agent/planner` and `bewerbungs-agent/writer` (FR-019/FR-020 expected hash-flip signal). If the output reports more or fewer than 2 created, an unintended prompt was modified; investigate with `git diff prompts/` before continuing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial verification — start immediately.
- **Foundational (Phase 2)**: NONE. Skip directly to Phase 3.
- **US1 (Phase 3)**: independent. Adds `ParagraphPlan` model + `ContentPlan` field additions + validators + planner prompt + stage-level cross-reference check.
- **US2 (Phase 4)**: depends on US1 (writer prompt assumes the new schema fields exist). Run after US1.
- **US3 (Phase 5)**: independent of US1/US2 implementation (tests legacy paths that don't exercise the new behaviour). Can run in parallel with US1/US2 once the schema additions land — but the test asserts on the new model's load behaviour, so requires US1's T009/T010 at minimum.
- **Polish (Phase 6)**: depends on US1+US2+US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI).
- US1: T009 (ParagraphPlan model) → T010 (ContentPlan fields) → T011 (validators) → T012 (build_prompt reminder) → T013 (stage cross-reference) → T014 (cross-reference test) → T015 (planner.md prompt rewrite) → T016 verification. T002–T008 are all draftable in parallel (different test methods).
- US2: T019 (helper) → T020 (wire into build_prompt) → T021 (writer.md prompt update) → T022 verification. T017 + T018 draftable in parallel.
- US3: T023 + T024 draftable in parallel; T025 verifies.

---

## Parallel Opportunities

```bash
# Phase 1: single task.

# Phase 3 US1 — multiple failing tests can be drafted in parallel
# (different test methods in the same file — sequential write for clean line
# ordering, but [P] reflects semantic independence):
Task T002: test_paragraph_plan_main_message_is_single_string                            # [P]
Task T005: test_content_plan_evidence_refs_exceeding_max_claims_raises                  # [P]
Task T008: test_opening_paragraph_main_message_references_role_family (regression guard) # [P]

# US1 and US3 tests both target test_plan_content.py (sequential write);
# US2 tests are in test_write_letter.py — can be drafted in parallel:
Task T017: test_writer_prompt_surfaces_paragraph_max_claims_and_max_tools  # [P] — different file

# Phase 5 US3 — both tests in test_plan_content.py (sequential), but T023 is
# in a different test class from T024:
Task T023: test_legacy_content_plan_without_paragraphs_loads_with_defaults  # [P]

# Phase 6: docs update + Langfuse sync are independent:
Task T026: Update ENGINEERING.md          # [P]
Task T030: jobagent prompts sync          # [P] — independent operation
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 1 (verify baseline).
2. Skip Phase 2 (none).
3. Complete Phase 3 (US1) — `ParagraphPlan` model + `ContentPlan` field additions + validators + planner prompt + stage cross-reference check.
4. **STOP**: at this point the planner emits the new structure and the artifacts under `outputs/<run_id>/artifacts/content_plan.json` carry `letter_thesis` + `paragraphs`. The writer doesn't yet consume the new structure (still uses the existing serialised JSON path), but the regression guard (T008) is in place and the deterministic AI/ML-infra fixture test confirms the planner doesn't misclassify. US2 adds the writer-side surfacing; US3 adds explicit backward-compat tests.

### Incremental Delivery

1. Phase 1 → verification ✓
2. Phase 3 (US1) → planner emits hiring story ✓ (writer doesn't yet read the new structure)
3. Phase 4 (US2) → writer surfaces per-paragraph density limits and consumes the structure ✓ (MVP pair shippable)
4. Phase 5 (US3) → backward-compat coverage explicit ✓
5. Phase 6 → docs, full sweep, Langfuse prompt-version push ✓

### Parallel Team Strategy

With two contributors after Phase 1 lands:

- Contributor A: US1 (schema + planner prompt + planner stage cross-reference)
- Contributor B: US3 (backward-compat tests — only needs US1's T009/T010 to compile; can land its tests in parallel with US1's other tasks)
- Either contributor picks up US2 (writer-side wiring) after US1's T009–T011 schema changes land

---

## Notes

- `[P]` = different files (or sufficiently independent test methods within the same file), safe to draft in parallel.
- `[USN]` = maps to user story N in spec.md.
- **No new schema files, no new pipeline stage, no new artefact file, no new CLI command** — the entire feature ships behind unchanged operator-visible contracts (FR-017–FR-021). Improvement is visible inside `outputs/<run_id>/artifacts/content_plan.json` and (with observability enabled) on the `plan_content` and `write_letter` Langfuse spans.
- **Feature 007 prompt registry**: T015 + T021 edit exactly two prompts (`planner.md` + `writer.md`). The next `jobagent prompts sync` (T030) MUST report `2 created, 8 unchanged`. The two created are `bewerbungs-agent/planner` and `bewerbungs-agent/writer`. Any other count signals an unintended prompt edit — investigate with `git diff prompts/` before merging.
- **Hiring review is intentionally NOT edited** — feature 009's content-plan summary block automatically surfaces the new `letter_thesis` and per-paragraph `main_message` values because it serialises the entire `ContentPlan` typed object. No `hiring_reviewer.md` edit; no `hiring_review.py` edit; no new always-on dimension. The reviewer benefits from the richer plan visibility for FREE.
- **Writer isolation invariant preserved** — the new fields ride on the existing `ContentPlan` typed object the writer already consumes (FR-015). No new constructor argument; no raw profile / CV / evidence-passage flows to the writer.
- **Backward compat = automatic + tested** — the schema design (`Optional` `letter_thesis`, `default_factory=list` `paragraphs`) makes legacy load work without any explicit migration; T023 + T024 pin the invariant as explicit regression tests.
- **`extra="forbid"` discipline**: T003 (ParagraphPlan) + T024 (ContentPlan) explicitly test that typo top-level fields raise. Pre-existing on `ContentPlan` from features 008–010; reaffirmed for the new model.
- **Test count math**: T002–T008, T014 = 8 tests in US1 (T002, T003, T004, T005, T006, T007, T008 = 7 + T014 = 8); T017, T018 = 2 tests in US2; T023, T024 = 2 tests in US3. Total: 12 new tests. Expected suite: 254 + 12 = 266 passed (the `let's-call-it-13` slot in the spec covers an extra defensive test pattern that may or may not materialise depending on implementation discovery).
