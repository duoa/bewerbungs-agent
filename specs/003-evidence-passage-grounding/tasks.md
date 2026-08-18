# Tasks: Evidence Passage Grounding

**Input**: Design documents from `/specs/003-evidence-passage-grounding/`  
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, quickstart.md ✓

**Scope**: 4 source files change; 4 test files updated. No new stages, no topology changes.  
**Tests**: Included — constitution mandates TDD (write test → confirm fail → implement → confirm pass).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to user story (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Confirm baseline before any changes.

- [x] T001 Run full test suite (`uv run pytest tests/`) and confirm all tests pass as a baseline in tests/

---

## Phase 2: Foundational — Data Model Extensions

**Purpose**: Extend `EvidenceItem` and `SectionPlan` with new optional fields. Both are safe-default additions; no migration needed. This phase blocks US1, US2, and US3.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T002 Add `relevance_note: str = ""` field to `EvidenceItem` in `src/bewerbungs_agent/models/state.py` (after the existing `passage` field)
- [x] T003 Add `anchor_passages: list[str] = Field(default_factory=list)` field to `SectionPlan` in `src/bewerbungs_agent/models/state.py` (after `evidence_refs`)
- [x] T004 [P] Update `EvidenceItem` fixture dicts in `tests/unit/test_build_evidence_map.py` to include `"passage": "some text"` (if not already present) so existing tests remain valid
- [x] T005 [P] Update `ContentPlan` / `SectionPlan` fixture dicts in `tests/unit/test_plan_content.py` to include `"anchor_passages": []` where needed so existing tests remain valid
- [x] T006 Run `uv run pytest tests/unit/` and confirm all unit tests still pass after model changes

**Checkpoint**: `EvidenceItem` and `SectionPlan` have new fields; existing tests still green.

---

## Phase 3: User Story 1 — Passage-Level Evidence Extraction (Priority: P1) 🎯 MVP

**Goal**: `build_evidence_map` passes full document text to the LLM and extracts verbatim passages per claim, not truncated document heads.

**Independent Test**: `uv run pytest tests/unit/test_build_evidence_map.py` — all new tests pass; full CV text appears in prompt; empty-passage items are dropped.

### Tests for User Story 1

> **Write these tests FIRST; confirm they FAIL before implementing T010–T012.**

- [x] T007 [US1] Add test `TestBuildPrompt.test_passes_full_cv_text` in `tests/unit/test_build_evidence_map.py` — assert the prompt contains the full `selected_cv.full_text` without truncation (use a CV text longer than 3000 chars in the fixture; assert a substring beyond char 3000 is present in the prompt)
- [x] T008 [US1] Add test `TestBuildPrompt.test_passes_full_skills_text` in `tests/unit/test_build_evidence_map.py` — assert the prompt contains the full `personal_skills` text (use text longer than 1500 chars; assert substring beyond char 1500 is present)
- [x] T009 [US1] Add test `TestBuildPrompt.test_passes_full_project_docs` in `tests/unit/test_build_evidence_map.py` — assert the prompt includes all project doc text beyond the 500-char-per-doc truncation
- [x] T010 [US1] Add test `TestBuildPrompt.test_prompt_requests_verbatim_passage` in `tests/unit/test_build_evidence_map.py` — assert the prompt text contains the word "verbatim" or "quote" (verify the extraction instruction is present)
- [x] T011 [US1] Add test `TestParseResponse.test_empty_passage_goes_to_known_gaps` in `tests/unit/test_build_evidence_map.py` — assert that an EvidenceItem with `"passage": ""` is NOT in `evidence_map.items` and its claim IS in `evidence_map.known_gaps`
- [x] T012 [US1] Add test `TestParseResponse.test_whitespace_passage_goes_to_known_gaps` in `tests/unit/test_build_evidence_map.py` — assert that `"passage": "   "` (whitespace only) triggers the same gap behaviour as empty
- [x] T013 [US1] Add test `TestParseResponse.test_valid_passage_accepted` in `tests/unit/test_build_evidence_map.py` — assert that an item with a non-empty passage AND a `relevance_note` deserialises into an `EvidenceItem` with both fields populated

### Implementation for User Story 1

- [x] T014 [US1] In `build_evidence_map.build_prompt` (`src/bewerbungs_agent/stages/build_evidence_map.py`), remove the `[:3000]` truncation on `cv_text`, the `[:1500]` truncation on `skills_text`, and the `[:500]` truncation on each project doc summary — pass full text for all three
- [x] T015 [US1] In `build_evidence_map.build_prompt`, update the content string to instruct the LLM to quote verbatim text and populate `relevance_note`: add the sentence "For each claim, quote the exact verbatim text from the source document in the `passage` field. In `relevance_note`, write one sentence explaining why this passage supports the claim."
- [x] T016 [US1] In `build_evidence_map.parse_response` (`src/bewerbungs_agent/stages/build_evidence_map.py`), after `EvidenceItem.model_validate(raw_item)`, check `if not item.passage.strip()`: if true, append `item.claim` to the local `known_gaps` list and skip adding the item to `items`
- [x] T017 [US1] Run `uv run pytest tests/unit/test_build_evidence_map.py` and confirm all tests (old + new) pass

**Checkpoint**: `build_evidence_map` extracts verbatim passages from full documents; empty-passage items are routed to `known_gaps`.

---

## Phase 4: User Story 2 — Passage Propagation Through Content Plan (Priority: P2)

**Goal**: `plan_content.build_prompt` includes verbatim passages from the evidence map, and `SectionPlan.anchor_passages` is populated by the planner LLM.

**Independent Test**: `uv run pytest tests/unit/test_plan_content.py` — new tests pass; `anchor_passages` field is present in sections and carries passage text.

**Depends on**: Phase 3 complete (EvidenceItems now have populated passages).

### Tests for User Story 2

> **Write these tests FIRST; confirm they FAIL before implementing T021–T022.**

- [ ] T018 [US2] Add test `TestBuildPrompt.test_prompt_includes_verbatim_passages` in `tests/unit/test_plan_content.py` — build a state with an `evidence_map` whose items have non-empty `passage` fields; assert the built prompt contains those passage strings
- [ ] T019 [US2] Add test `TestBuildPrompt.test_prompt_includes_relevance_note_when_present` in `tests/unit/test_plan_content.py` — assert that a non-empty `relevance_note` from an EvidenceItem appears in the prompt
- [ ] T020 [US2] Add test `TestParseResponse.test_anchor_passages_accepted` in `tests/unit/test_plan_content.py` — supply a plan response dict with `"anchor_passages": ["verbatim text"]` in a section; assert the resulting `ContentPlan.sections[0].anchor_passages` equals `["verbatim text"]`

### Implementation for User Story 2

- [ ] T021 [US2] In `plan_content.build_prompt` (`src/bewerbungs_agent/stages/plan_content.py`), update the `claims_list` construction to include the passage and relevance_note for each EvidenceItem, formatted as:
  ```
  - {item.claim} [source: {item.source_file}]
    Passage: "{item.passage}"
    Note: {item.relevance_note or 'n/a'}
  ```
- [ ] T022 [US2] In `plan_content.build_prompt`, add an instruction line telling the LLM to copy the relevant passage text into the `anchor_passages` list of each section it creates: "For each section, copy the verbatim passage text from the evidence items you reference into `anchor_passages`."
- [ ] T023 [US2] Run `uv run pytest tests/unit/test_plan_content.py` and confirm all tests (old + new) pass

**Checkpoint**: ContentPlan sections now carry `anchor_passages` lists populated from EvidenceItem passages.

---

## Phase 5: User Story 3 — Letter Writer Isolation via Anchor Passages (Priority: P3)

**Goal**: `write_letter.build_prompt` instructs the LLM to anchor prose to the `anchor_passages` in each section. The prompt remains isolated — no raw profile text.

**Independent Test**: `uv run pytest tests/unit/test_write_letter.py` — new test passes; prompt contains anchor instruction but no raw profile document text.

**Depends on**: Phase 4 complete (ContentPlan sections now have anchor_passages).

### Tests for User Story 3

> **Write this test FIRST; confirm it FAILS before implementing T026.**

- [ ] T024 [US3] Add test `TestBuildPrompt.test_prompt_contains_anchor_instruction` in `tests/unit/test_write_letter.py` — assert the built prompt contains the word "anchor" or "anchor_passages" (verifying the new instruction line is present)
- [ ] T025 [US3] Add test `TestBuildPrompt.test_prompt_does_not_contain_raw_profile_text` in `tests/unit/test_write_letter.py` — build a state where `knowledge.personal_skills` contains a sentinel string not present in the ContentPlan; assert that sentinel does NOT appear in the built prompt

### Implementation for User Story 3

- [ ] T026 [US3] In `write_letter.build_prompt` (`src/bewerbungs_agent/stages/write_letter.py`), add one instruction line after the existing writer instructions: "For each section, anchor your prose to the `anchor_passages` listed in that section. Use their phrasing as a starting point; do not invent wording not present in the plan."
- [ ] T027 [US3] Run `uv run pytest tests/unit/test_write_letter.py` and confirm all tests (old + new) pass

**Checkpoint**: Letter writer is directed to anchor_passages; raw profile isolation is verified by test.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Update integration tests to reflect the richer data model and run the full suite.

- [ ] T028 [P] In `tests/integration/test_pipeline.py`, update all `EvidenceItem` fixture dicts / mock LLM responses to include `"passage": "<some non-empty text>"` and `"relevance_note": ""` so the integration test works with the updated parse_response validation
- [ ] T029 [P] In `tests/integration/test_pipeline.py`, update `SectionPlan` fixture / mock responses to include `"anchor_passages": []` or a non-empty list, whichever matches the mock planner output
- [ ] T030 Add integration test `test_deep_cv_achievement_surfaces_in_letter` in `tests/integration/test_pipeline.py` — use a fixture CV where a sentinel achievement phrase (e.g. "SENTINEL_DEEP_ACHIEVEMENT") appears only beyond character 3000; run the full pipeline with mocked LLM that echoes the evidence passage back into the letter; assert the sentinel phrase appears in `letter_draft.text` (covers SC-003)
- [ ] T031 Run full test suite `uv run pytest tests/` and confirm all tests pass (unit + integration)
- [ ] T032 Run `uv run ruff check src/ tests/ && uv run mypy src/ --strict` and fix any lint or type errors introduced by the new fields

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 (model fields must exist)
- **US2 (Phase 4)**: Depends on Phase 3 (EvidenceItems need populated passages to propagate)
- **US3 (Phase 5)**: Depends on Phase 4 (ContentPlan needs anchor_passages to instruct writer)
- **Polish (Phase 6)**: Depends on Phase 5

### User Story Dependencies

- **US1** → **US2** → **US3** (strict chain — each story's output is the next story's input)

### Within Each Phase

- Test tasks (T007–T013, T018–T020, T024–T025) MUST be written and confirmed to FAIL before their corresponding implementation tasks
- Implementation tasks within a story are sequential (same file)

### Parallel Opportunities

- T004 and T005 (fixture updates) can run in parallel (different test files)
- T028 and T029 (integration fixture updates) can run in parallel (same file sections, but logically independent)

---

## Parallel Example: Phase 2 (Foundational)

```bash
# These two fixture updates can run at the same time:
Task T004: "Update EvidenceItem fixtures in tests/unit/test_build_evidence_map.py"
Task T005: "Update SectionPlan fixtures in tests/unit/test_plan_content.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (baseline green)
2. Complete Phase 2: Foundational (model changes, existing tests green)
3. Complete Phase 3: US1 (full-doc passage extraction working)
4. **STOP and VALIDATE**: `uv run pytest tests/unit/test_build_evidence_map.py`
5. Optionally ship — EvidenceItems now carry verbatim passages even if plan and writer haven't been updated yet

### Incremental Delivery

1. Phase 1 + 2 → baseline safe
2. Phase 3 (US1) → passages extracted → independently testable
3. Phase 4 (US2) → passages in ContentPlan → independently testable
4. Phase 5 (US3) → writer anchored → full feature complete
5. Phase 6 (Polish) → full suite green, lint clean

---

## Notes

- All new Pydantic fields have safe defaults — no serialised state migration needed
- `relevance_note` and `anchor_passages` are populated by the LLM via tool-use; they are not validated for content (only `passage` is validated for non-emptiness)
- The `content_plan_hash` in `write_letter` covers the full ContentPlan JSON, which now includes anchor passages — hash integrity is preserved automatically
- The LangGraph graph topology (`graph.py`) is NOT changed by any task in this list
