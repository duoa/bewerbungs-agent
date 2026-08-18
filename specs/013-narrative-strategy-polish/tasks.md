# Tasks: Narrative Strategy & Story Polish

**Input**: Design documents from `/specs/013-narrative-strategy-polish/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-042–FR-045 explicitly mandate four tests; Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task. All tests use mocked LLM responses (canned JSON dicts); no real Anthropic calls in unit tests.

**Organization**: US1 (P1) ships NarrativeStrategy + planner/writer consumption — MVP. US2 (P2) ships story_polish with deterministic post-check. US3 (P3) ships hiring_review craft dimensions + German over-analogy scan.

**Scope discipline**: This feature touches 6 source files (`config/models.py`, `models/state.py`, `graph/workflow.py`, `stages/plan_content.py`, `stages/write_letter.py`, `stages/hiring_review.py`), adds 4 source files (`stages/role_position.py`, `stages/narrative_strategy.py`, `stages/story_polish.py`, `utils/extractors.py`), modifies 4 prompts (`planner.md`, `writer.md`, `hiring_reviewer.md`, `styles/aida.md`), adds 3 prompts (`role_positioner.md`, `narrative_strategist.md`, `story_polisher.md`), and adds 4 test files (`test_role_position.py`, `test_narrative_strategy.py`, `test_story_polish.py`, `test_extractors.py`) + extends 3 (`test_plan_content.py`, `test_write_letter.py`, `test_hiring_review.py`). No new dependencies. No new CLI flags.

---

## Phase 1: Setup

- [X] T001 Verify the 266-test baseline (post-feature-011) passes: `uv run pytest tests/ --tb=short` and capture the count for the Phase 6 comparison
- [X] T002 Verify `git status` is clean on `013-narrative-strategy-polish` aside from the expected `specs/013-narrative-strategy-polish/` planning artefacts; verify `uv run jobagent prompts sync` reports `0 created, 10 unchanged` so the registry baseline is clean before we start editing prompts

---

## Phase 2: Foundational

**Purpose**: Three blocking prerequisites. (a) `NarrativePolishConfig` plumbing so US1/US2/US3 can all read config. (b) Extract `role_position` into its own stage so US1 can insert `narrative_strategy` between it and `plan_content` per research.md R1. (c) Verify the extraction doesn't break the existing 266-test suite (legacy `plan_content` tests need state-side `role_positioning` injection).

- [X] T003 Add `NarrativePolishConfig` (4 fields: `narrative_strategy_enabled`, `story_polish_enabled`, `restrained_aida`, `tool_registry`) to `src/bewerbungs_agent/config/models.py` per data-model.md §4 with `ConfigDict(extra="forbid")` and field defaults; add `narrative_polish: NarrativePolishConfig = Field(default_factory=NarrativePolishConfig)` to `MergedConfig`; update `src/bewerbungs_agent/utils/merge.py` to list the new field in the explicit-merge list (mirror the existing `writer_rules` pattern); add a single test `test_narrative_polish_config_defaults` in `tests/unit/test_config_models.py` asserting all four defaults
- [X] T004 Write failing tests for the extracted `role_position` stage in NEW `tests/unit/test_role_position.py`:
  - `test_role_position_prompt_includes_job_description` — `build_prompt(state)` includes `state.job_context.raw_job_text` and the weighted-requirements block
  - `test_role_position_parse_response_validates_schema` — parses a canned dict containing all seven `RolePositioning` fields into a `RolePositioning` instance
  - `test_role_position_node_writes_role_positioning_to_state` — patches the LLM client to return a canned dict; calls `role_position(state)`; asserts the returned dict has key `"role_positioning"` and value is a `RolePositioning` instance
- [X] T005 Create `prompts/role_positioner.md` by MOVING the role-positioning instructions out of `prompts/planner.md` verbatim (sections: "Source-of-truth ordering for the positioning decision", "Required output: role_positioning", "Special cases", "Section ordering should reflect positioning"); add a 2-sentence preamble stating the prompt's purpose
- [X] T006 Implement `src/bewerbungs_agent/stages/role_position.py` — `build_prompt`, `parse_response`, `role_position` (LangGraph node) following the existing `plan_content.py` pattern; LLM tool schema = `RolePositioning.model_json_schema()`; load instructions via `load_prompt("role_positioner")`; record stage in tracker as `stage_name="role_position", prompt_name="role_positioner"`; T004 tests now PASS
- [X] T007 Modify `src/bewerbungs_agent/graph/workflow.py`: register `role_position_node` and add edge `build_evidence_map → role_position → plan_content` (replacing the existing `build_evidence_map → plan_content` edge); the `narrative_strategy` insertion happens in US1 (T017)
- [X] T008 Modify `src/bewerbungs_agent/stages/plan_content.py` to consume `state.role_positioning` instead of producing it: (a) strip the role-positioning ask from the IMPORTANT trailer in `build_prompt`; (b) after `parse_response` succeeds, attach `state.role_positioning` to the returned `ContentPlan` via `plan.model_copy(update={"role_positioning": state.role_positioning})`; (c) update `prompts/planner.md` — REMOVE the role-positioning sections (moved to `role_positioner.md` in T005); replace the existing "You MUST populate the `role_positioning` object" reminder with "You MUST NOT produce role_positioning — it is decided upstream and will be attached automatically". Run the existing 266-test suite — legacy tests in `test_plan_content.py` that expect role_positioning in the planner response will need `state.role_positioning` populated in the fixture instead; update those fixtures (mechanical change, ~10–15 test sites)

**Checkpoint**: 266 tests pass with role_positioning produced by a dedicated stage. The pipeline is `... → build_evidence_map → role_position → plan_content → ...`. US1 can now insert `narrative_strategy` in the middle.

---

## Phase 3: User Story 1 — NarrativeStrategy upstream of planning (Priority: P1) 🎯 MVP

**Goal**: A new `NarrativeStrategy` Pydantic model lands with nine bounded fields, `extra="forbid"`, and a stage-level cross-check ensuring `proof_points_to_use` / `proof_points_to_avoid` trace to `evidence_map.items[*].claim`. A new `narrative_strategy` stage runs between `role_position` and `plan_content`, with a deterministic minimal-strategy fallback when disabled or LLM-failed. The planner's `build_prompt` formats a new `# Narrative Strategy` block and the stage drops paragraphs whose `evidence_refs` overlap `proof_points_to_avoid`. The writer's `build_prompt` formats a parallel narrative-strategy block.

**Independent Test**: Construct a canned LLM response containing a full `NarrativeStrategy` JSON. Call `narrative_strategy.parse_response(data, evidence_map)`. Assert it returns a `NarrativeStrategy` instance with all nine fields populated and that any `proof_points_to_use` claim not in `evidence_map.items` raises `ValueError`. Separately call `plan_content.plan_content(state)` with `state.narrative_strategy` set to a strategy whose `proof_points_to_avoid` contains one paragraph's `evidence_refs[0]`; assert that paragraph is filtered out of the returned plan.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T014

- [X] T009 [P] [US1] Write failing test `test_narrative_strategy_schema_required_fields` in NEW `tests/unit/test_narrative_strategy.py` — construct a `NarrativeStrategy` with the nine required fields; assert each field is the expected type; assert omitting any of `candidate_story`/`role_story`/`bridge`/`opening_angle`/`tone_guidance` raises `ValidationError` (FR-002 through FR-006, FR-010)
- [X] T010 [P] [US1] Write failing test `test_narrative_strategy_schema_bounds` in `tests/unit/test_narrative_strategy.py` — assert `candidate_story="x" * 801` raises (max_length=800), `opening_angle="x" * 401` raises (max_length=400), `tone_guidance="x" * 601` raises (max_length=600); assert empty `candidate_story` (`""`) raises (min_length=1); document the German-length rationale in a docstring (research.md R2)
- [X] T011 [US1] Write failing test `test_narrative_strategy_list_bounds` in `tests/unit/test_narrative_strategy.py` — assert `proof_points_to_use=["c"] * 13` raises (max_length=12 elements); same for `proof_points_to_avoid=["c"] * 13`; same for `anti_patterns=["p"] * 21`; assert one `anti_patterns` entry of length 241 raises via the field_validator
- [X] T012 [US1] Write failing test `test_narrative_strategy_unknown_field_forbidden` in `tests/unit/test_narrative_strategy.py` — construct payload with all nine valid fields plus a typo `candiate_story` (note misspelling); assert `ValidationError` raised and error mentions `candiate_story` (FR-002, extra="forbid")
- [X] T013 [P] [US1] Write failing test `test_proof_points_must_trace_to_evidence_map` in `tests/unit/test_narrative_strategy.py` — construct `evidence_map=EvidenceMap(items=[EvidenceItem(claim="X", source_type="cv_variant", source_file="cv.md", passage="X")])`; call `parse_response({...proof_points_to_use=["X", "Y"]...}, evidence_map)`; assert `ValueError` raised with message mentioning `proof_points_to_use[1]` and `"Y"`; verify same scenario with `proof_points_to_use=["X"]` succeeds (research.md R2 stage-level cross-check)
- [X] T014 [P] [US1] Write failing test `test_planner_prompt_includes_narrative_strategy_block` in `tests/unit/test_plan_content.py` — build a state with `state.narrative_strategy = NarrativeStrategy(...)`; call `build_prompt(state)`; assert the user message contains substring `"# Narrative Strategy"`, `"candidate_story:"`, `"bridge:"`, `"opening_angle:"`, `"proof_points_to_avoid:"`, `"anti_patterns:"` (contracts §4.2)
- [X] T015 [US1] Write failing test `test_planner_drops_paragraphs_in_proof_points_to_avoid` in `tests/unit/test_plan_content.py` — patch the LLM client to return a canned `ContentPlan` with three paragraphs (indices 0/1/2 with evidence_refs `["A"]`/`["B"]`/`["C"]` respectively); set `state.narrative_strategy.proof_points_to_avoid=["B"]`; call `plan_content(state)`; assert the returned plan has 2 paragraphs (indices 0 and 2 only); verify a tracker event `narrative_strategy.paragraph_dropped` was logged (contracts §4.3)
- [X] T016 [P] [US1] Write failing test `test_writer_prompt_includes_narrative_strategy_block` in `tests/unit/test_write_letter.py` — build a state with `state.narrative_strategy = NarrativeStrategy(...)`; call `build_prompt(state)`; assert the user message contains `"# Narrative Strategy"`, `"bridge:"`, `"opening_angle:"`, `"tone_guidance:"`, `"anti_patterns:"`; assert the block appears AFTER `# Writer Rules` and BEFORE `# Paragraph Plan` (contracts §5.2)

### Implementation for User Story 1

- [X] T017 [US1] Add `NarrativeStrategy` Pydantic model to `src/bewerbungs_agent/models/state.py` per data-model.md §1 — nine fields with the documented bounds, `ConfigDict(extra="forbid")`, the `@field_validator("anti_patterns")` enforcing per-entry 240-char cap; add `narrative_strategy: NarrativeStrategy | None = None` to `WorkflowState`; T009–T012 now PASS
- [X] T018 [US1] Create `prompts/narrative_strategist.md` with the system prompt content per the spec's nine-field structure and the AIDA-restraint constraint when mode=aida (see contracts §3.2 IMPORTANT block for the cross-check rules to surface to the LLM)
- [X] T019 [US1] Implement `src/bewerbungs_agent/stages/narrative_strategy.py` — `build_prompt`, `parse_response(data, evidence_map)` with the stage-level cross-check from data-model.md §1, `_fallback_strategy(state)` per contracts §3.3 (deterministic minimal strategy), `narrative_strategy(state)` LangGraph node that respects `state.config.narrative_polish.narrative_strategy_enabled` (uses fallback when False or on LLM exception); LLM tool schema = `NarrativeStrategy.model_json_schema()`; T013 now PASSES
- [X] T020 [US1] Modify `src/bewerbungs_agent/graph/workflow.py` to register `narrative_strategy_node` and insert it between `role_position` and `plan_content` (replace edge `role_position → plan_content` with `role_position → narrative_strategy → plan_content`); the graph topology now matches contracts §1
- [X] T021 [US1] Modify `src/bewerbungs_agent/stages/plan_content.py` to add the `narrative_block` to `build_prompt` between the existing `# Weighted Requirements` block and `# Available Evidence Claims` block (contracts §4.2); add the proof_points_to_avoid filter loop (contracts §4.3) after `parse_response` succeeds, BEFORE the existing requirement_ids cross-check; T014 and T015 now PASS
- [X] T022 [US1] Modify `prompts/planner.md` per contracts §4.1 — add a "Narrative Strategy consumption" section explaining how to use the `# Narrative Strategy` block (paragraphs MUST support its bridge and opening_angle; paragraphs overlapping `proof_points_to_avoid` MUST be omitted)
- [X] T023 [US1] Add `_format_narrative_strategy_block(state)` helper to `src/bewerbungs_agent/stages/write_letter.py` per contracts §5.1; wire into `build_prompt` between the existing `# Writer Rules` block and `# Paragraph Plan` block per contracts §5.2; T016 now PASSES
- [X] T024 [US1] Modify `prompts/writer.md` per contracts §5.3 — add new section "### 11. Narrative strategy consumption (feature 013)" with the four bullets on opening_angle / proof_points_to_avoid / anti_patterns / tone_guidance + restrained AIDA explanation
- [X] T025 [US1] Confirm all US1 tests (T009–T016) pass; confirm the existing 266-test suite still passes (baseline preserved); confirm `narrative_strategy.json` artefact is written to `outputs/<run_id>/artifacts/` (verify by adding artefact persistence to `narrative_strategy` node — mirror the existing `content_plan.json` persistence pattern)

**Checkpoint**: NarrativeStrategy is produced upstream of planning; the planner and writer both consume it; the planner drops paragraphs the strategy vetoes. The MVP delivers letters with an explicit story spine. US2 below adds the polish pass.

---

## Phase 4: User Story 2 — Story polish with deterministic post-check (Priority: P2)

**Goal**: A new `story_polish` stage runs between `write_letter` and `hiring_review`. It polishes prose for flow without adding new tool names, employer names, or numeric tokens — enforced by a deterministic post-check on three extractors. Failure modes (LLM error, post-check fails, disabled) all fall back to the unpolished draft and the pipeline continues. `StoryPolishOutput` records the audit trail.

**Independent Test**: Build a draft text `"I worked with Python and Kafka at Acme Corp."`. Call `post_check(draft, polished="I leveraged Python and Kafka at Acme Corp.", registry={"Python", "Kafka", "Spark"})`; assert `passed=True`. Call `post_check(draft, polished="I leveraged Python, Kafka, and Spark at Acme Corp.", registry={...})`; assert `passed=False` and `added_tools=["Spark"]`.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T030

- [X] T026 [P] [US2] Write failing tests for the deterministic extractors in NEW `tests/unit/test_extractors.py`:
  - `test_tool_extractor_whole_word_match` — "AWS" inside "AWS-managed" matches; "AWS" inside "AWSome" does NOT match; "Kafka" inside "kafkaesque" does NOT match
  - `test_tool_extractor_case_insensitive` — "python" in text matches `"Python"` in registry; "PYTHON" matches; result contains the registry casing
  - `test_employer_extractor_after_at_bei` — "worked at Acme Corp" extracts `"Acme Corp"`; "bei Bayer AG" extracts `"Bayer AG"`; "Acme Corp" without prefix does NOT extract; multi-word "JP Morgan Chase" extracts as one entry
  - `test_numeric_extractor_normalises_punctuation` — "1000", "1,000", "~1000", "1000+", "1000%" all normalise to `"1000"`; "1.5" stays `"1.5"`; "1000" and "1500" are different tokens
  - `test_post_check_passes_on_subset` — draft contains {Python, Kafka, "Acme Corp", "1000"}; polished is a rephrasing with the same set; `passed=True`
  - `test_post_check_fails_on_added_tool` — polished introduces "Spark" not in draft; `passed=False`, `added_tools=["Spark"]`
  - `test_post_check_fails_on_added_employer` — polished introduces "Bayer AG" not in draft; `passed=False`, `added_employers=["Bayer AG"]`
  - `test_post_check_fails_on_added_numeric` — polished introduces "2000" not in draft; `passed=False`, `added_numerics=["2000"]`
- [X] T027 [P] [US2] Write failing test `test_story_polish_output_schema_consistency` in NEW `tests/unit/test_story_polish.py` — assert `StoryPolishOutput(post_check_passed=True, added_tools=["X"], ...)` raises `ValidationError` (consistency invariant in data-model.md §2); assert `StoryPolishOutput(used_fallback=True, fallback_reason=None, ...)` raises (fallback_reason required when used_fallback=True)
- [X] T028 [P] [US2] Write failing test `test_story_polish_falls_back_on_llm_failure` in `tests/unit/test_story_polish.py` — patch the LLM client to raise `RuntimeError("boom")`; call `story_polish(state)`; assert returned `letter_draft.text` equals the original draft; assert `story_polish_output.used_fallback is True` and `fallback_reason` starts with `"llm_failure: boom"`
- [X] T029 [US2] Write failing test `test_story_polish_falls_back_on_post_check_failure` in `tests/unit/test_story_polish.py` — patch the LLM client to return a polished text introducing a new tool name (e.g., draft contains "Python", polished contains "Python and Spark"); call `story_polish(state)`; assert returned `letter_draft.text` equals the original draft; assert `story_polish_output.used_fallback is True` and `fallback_reason` starts with `"post_check_failed:"` and lists `Spark` in `added_tools`
- [X] T030 [US2] Write failing test `test_story_polish_skipped_when_disabled` in `tests/unit/test_story_polish.py` — set `state.config.narrative_polish.story_polish_enabled = False`; call `story_polish(state)`; assert returned dict is `{"letter_draft": state.letter_draft, "story_polish_output": None}`; assert the LLM client is NOT called (use a mock that raises if called)

### Implementation for User Story 2

- [X] T031 [P] [US2] Implement `src/bewerbungs_agent/utils/extractors.py` per contracts §6.5 — `TOOL_REGISTRY_DEFAULT` (frozenset), `EMPLOYER_CONTEXT_PREFIXES`, `tool_names_in_text`, `employer_names_in_text`, `numeric_tokens_in_text`, `StoryPolishPostCheck` dataclass, `post_check(draft, polished, registry)`; T026 PASSES
- [X] T032 [US2] Add `StoryPolishOutput` Pydantic model to `src/bewerbungs_agent/models/state.py` per data-model.md §2 — eight fields, `ConfigDict(extra="forbid")`, `@model_validator(mode="after")` enforcing the two consistency invariants; add `story_polish_output: StoryPolishOutput | None = None` to `WorkflowState`; T027 PASSES
- [X] T033 [US2] Create `prompts/story_polisher.md` per contracts §6.6 — full prompt content with hard prohibitions, what to do, German over-analogy avoid list, AIDA restraint note
- [X] T034 [US2] Implement `src/bewerbungs_agent/stages/story_polish.py` per contracts §6.1–§6.4 — `build_prompt(state)`, `_resolve_tool_registry(state)` (returns `state.config.narrative_polish.tool_registry or TOOL_REGISTRY_DEFAULT`), `_fallback(state, reason, check=None)` helper, `story_polish(state)` LangGraph node with disabled-path short-circuit, LLM call wrapped in try/except, post-check, accept-or-fallback logic; persist `story_polish_output.json` to artefacts directory; T028 T029 T030 PASS
- [X] T035 [US2] Modify `src/bewerbungs_agent/graph/workflow.py` to register `story_polish_node` and insert between `write_letter` and `hiring_review` (REPLACE edge `write_letter → hiring_review` with `write_letter → story_polish → hiring_review`); the `tailor_cv → hiring_review` edge is preserved unchanged
- [X] T036 [US2] Confirm all US2 tests pass; confirm US1 tests still pass; confirm the existing 266-test baseline still passes; verify `story_polish_output.json` is written on a smoke run

**Checkpoint**: story_polish polishes drafts and the deterministic post-check guarantees no new facts. The pipeline now reads `... → write_letter → story_polish → hiring_review → ...`. US3 below extends the reviewer.

---

## Phase 5: User Story 3 — Hiring review craft dimensions + German over-analogy scan (Priority: P3)

**Goal**: The `hiring_review` stage's structured output gains a `craft_dimensions` block with six dimensions (`story_coherence`, `transition_smoothness`, `over_constructed_language`, `claim_relevance`, `aida_restraint`, `human_readability`) and a `deterministic_findings` list populated by a substring scan over four German over-analogy phrases. When `aida_restraint` or `transition_smoothness` reports severity ≥ `warn`, the aggregate verdict cannot remain `pass`.

**Independent Test**: Construct a canned hiring-review LLM response with all six craft dimensions populated. Call `hiring_review.parse_response(data)`. Assert all six dimensions are present and typed correctly. Construct a letter text containing `"direkt übertragbar"`. Call `_scan_over_analogy_phrases(text)`. Assert returns one `DeterministicFinding` with `phrase="direkt übertragbar"` and `char_start` at the correct offset.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T040

- [X] T037 [P] [US3] Write failing test `test_hiring_review_prompt_includes_six_craft_dimensions` in `tests/unit/test_hiring_review.py` — call `build_prompt(state)`; assert the user message contains each of the six dimension names verbatim: `"story_coherence"`, `"transition_smoothness"`, `"over_constructed_language"`, `"claim_relevance"`, `"aida_restraint"`, `"human_readability"` (contracts §7.1)
- [X] T038 [P] [US3] Write failing test `test_hiring_review_parses_craft_dimensions` in `tests/unit/test_hiring_review.py` — construct a canned LLM response containing `craft_dimensions` with all six entries (each with severity, rationale, evidence_quote); call `parse_response(data)`; assert returned `HiringReviewOutput.craft_dimensions` is a `CraftDimensions` instance and each of the six attributes is a `CraftDimension`; assert a `CraftDimension(severity="warn", evidence_quote=None)` raises (evidence required when severity ≥ warn — data-model.md §3)
- [X] T039 [US3] Write failing test `test_hiring_review_scans_over_analogy_phrases_de` in `tests/unit/test_hiring_review.py` — construct a letter text with the substring `"Mein Hintergrund ist direkt übertragbar auf diese Rolle."`; call `_scan_over_analogy_phrases(text)`; assert returns one `DeterministicFinding` with `check_id="over_analogy_phrase_de"`, `phrase="direkt übertragbar"`, `severity="warn"`, correct `char_start`/`char_end`, and a context_snippet containing the phrase; verify a clean letter returns `[]`; verify two occurrences return two findings
- [X] T040 [US3] Write failing test `test_hiring_review_verdict_escalates_when_aida_restraint_warn` in `tests/unit/test_hiring_review.py` — construct a canned response with `craft_dimensions.aida_restraint.severity="warn"` and `verdict="pass"`; call `parse_response(data)`; assert returned `verdict == "needs_minor_revision"`; verify the same scenario with `aida_restraint.severity="pass"` keeps `verdict="pass"`; verify the same escalation happens for `transition_smoothness.severity="warn"` (contracts §7.3)

### Implementation for User Story 3

- [X] T041 [P] [US3] Add `CraftDimension`, `CraftDimensions`, `DeterministicFinding` Pydantic models to `src/bewerbungs_agent/models/state.py` per data-model.md §3; extend `HiringReviewOutput` with `craft_dimensions: CraftDimensions | None = None` (nullable for legacy artefact replay; stage-level check raises if LLM returns None) and `deterministic_findings: list[DeterministicFinding] = Field(default_factory=list)`; T037 prep PASSES
- [X] T042 [US3] Modify `prompts/hiring_reviewer.md` per contracts §7.1 — add the new section "Craft dimensions (always-on)" listing the six dimensions with severity/rationale/evidence_quote format and the verdict-escalation rule; T037 PASSES
- [X] T043 [US3] Modify `src/bewerbungs_agent/stages/hiring_review.py`: (a) extend `parse_response` to validate `craft_dimensions` is present and apply the verdict-escalation logic per contracts §7.3; (b) add `OVER_ANALOGY_PHRASES_DE` tuple at module level; (c) add `_scan_over_analogy_phrases(letter_text)` per contracts §7.2; (d) in the `hiring_review` LangGraph node, after `parse_response`, call the scan and attach `deterministic_findings` to the review via `model_copy(update={"deterministic_findings": findings})`; T038 T039 T040 PASS
- [X] T044 [US3] Confirm all US3 tests pass; confirm US1+US2 tests still pass; confirm the 266-test baseline still passes; verify the `hiring_review.json` artefact now contains both `craft_dimensions` and `deterministic_findings` keys on a smoke run

**Checkpoint**: All three user stories shipped. The pipeline now produces letters with an explicit narrative strategy, a polish pass that cannot add facts, and a reviewer that catches the six craft-level failure modes plus four German over-analogy phrases deterministically.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T045 [P] Modify `prompts/styles/aida.md` to add a restrained-tone reinforcement section that applies when `narrative_polish.restrained_aida=True` (default); spell out the four banned hallmarks (ALL-CAPS opening, opening exclamation, second-person imperatives, hyperbolic adjectives); explicitly note "AIDA is a subtle narrative arc, NOT marketing copy"
- [X] T046 [P] Update `ENGINEERING.md` — add a feature 013 sub-section near the existing feature 011 sub-section: extracted `role_position` stage; new `narrative_strategy` and `story_polish` stages; new `NarrativeStrategy`, `StoryPolishOutput`, `CraftDimensions`, `DeterministicFinding` Pydantic models; deterministic post-check guarantees no new tool/employer/numeric facts in polished output; six hiring-review craft dimensions; German over-analogy phrase blocklist; new `NarrativePolishConfig` (4 booleans + optional tool_registry override); new pipeline graph topology
- [X] T047 Run full test suite `uv run pytest tests/ --tb=short`; expected count = previous baseline (266) + 8 US1 (T009–T016) + 5 US2 (T026 contains multiple sub-tests + T027 + T028 + T029 + T030) + 4 US3 (T037–T040) + 3 from T004 = ~286 passed; halt and fix any regression. Run `uv run ruff check` and `uv run mypy src/bewerbungs_agent/stages/role_position.py src/bewerbungs_agent/stages/narrative_strategy.py src/bewerbungs_agent/stages/story_polish.py src/bewerbungs_agent/utils/extractors.py src/bewerbungs_agent/models/state.py src/bewerbungs_agent/config/models.py src/bewerbungs_agent/stages/plan_content.py src/bewerbungs_agent/stages/write_letter.py src/bewerbungs_agent/stages/hiring_review.py src/bewerbungs_agent/graph/workflow.py`; fix any errors introduced by this feature
- [X] T048 [P] Push the seven updated/new prompt versions to Langfuse: `uv run jobagent prompts sync --label staging`; expected: `"7 created, 3 unchanged"` (created: `role_positioner`, `narrative_strategist`, `planner`, `writer`, `story_polisher`, `hiring_reviewer`, `styles/aida`). If the count is different, investigate with `git diff prompts/` before continuing
- [X] T049 Optional manual smoke test per `quickstart.md §7` — `jobagent run --job data/aduo/jobs/ds_nb.md --template default_de_neutral --profile-dir data/aduo`; inspect `outputs/<run_id>/artifacts/narrative_strategy.json` for non-empty `bridge` and `opening_angle`; inspect `story_polish_output.json` for `post_check_passed=true`; inspect `hiring_review.json` for `craft_dimensions` with six entries and `deterministic_findings` (likely empty on a clean letter). If too costly to run, document the deferral here

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial verification — start immediately
- **Foundational (Phase 2)**: BLOCKING for US1; extracts role_position into its own stage so US1 can insert narrative_strategy between it and plan_content. T003 (config) is independent and can run in parallel with T004–T008 once the parallel writer understands the merge.py contract
- **US1 (Phase 3)**: depends on Foundational. T009–T016 are tests (TDD red); T017–T024 are implementation (TDD green); T025 verifies
- **US2 (Phase 4)**: depends on US1 ONLY for the workflow.py edit (T035 inserts story_polish after write_letter, which now contains the narrative-strategy block from T023). The story_polish stage itself does NOT consume narrative_strategy in its prompt — only the writer does. So US2 tests can be drafted in parallel with US1 tests; implementation must wait for US1's T020 (workflow.py edit) to land first
- **US3 (Phase 5)**: depends on US1+US2 ONLY for the graph being wired correctly. The hiring_review extension is otherwise independent; tests can be drafted in parallel with US1/US2 tests
- **Polish (Phase 6)**: depends on US1+US2+US3 completion

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI)
- US1: T009–T013 (schema tests) → T017 (model) → T018 (prompt file) → T019 (stage) → T020 (graph) → T014 (planner test) → T015 (planner filter test) → T021 (planner mods) → T016 (writer test) → T023 (writer helper + wire) → T022+T024 (prompt mds) → T025 verification
- US2: T026 (extractor tests) → T031 (extractors) → T027 (schema test) → T032 (model) → T028+T029+T030 (stage tests) → T033 (prompt md) → T034 (stage) → T035 (graph) → T036 verification
- US3: T037+T038+T039+T040 (tests) → T041 (models) → T042 (prompt md) → T043 (stage mods) → T044 verification

### Parallel Opportunities Within US

- **US1 tests T009–T013, T014, T016**: different test methods in different test files (test_narrative_strategy.py vs test_plan_content.py vs test_write_letter.py) — parallelisable
- **US2 tests T026, T027, T028**: different test files and concerns — parallelisable
- **US3 tests T037, T038**: different test methods, same file (test_hiring_review.py) — sequential write for clean line ordering, but semantically independent

---

## Parallel Opportunities (cross-phase)

```bash
# Phase 2: T003 (config plumbing) is independent of T004–T008 (role_position extraction)
Task T003: NarrativePolishConfig + MergedConfig wiring   # [P]

# Phase 3 US1 — schema tests in test_narrative_strategy.py can be drafted in parallel:
Task T009: test_narrative_strategy_schema_required_fields    # [P]
Task T010: test_narrative_strategy_schema_bounds             # [P]
Task T013: test_proof_points_must_trace_to_evidence_map      # [P]
Task T014: test_planner_prompt_includes_narrative_strategy_block  # [P] — different file
Task T016: test_writer_prompt_includes_narrative_strategy_block   # [P] — different file

# Phase 4 US2 — extractors and StoryPolishOutput schema can be drafted in parallel:
Task T026: test_extractors                                   # [P] — new file
Task T027: test_story_polish_output_schema_consistency       # [P] — new file
Task T028: test_story_polish_falls_back_on_llm_failure       # [P] — same file as T027 (sequential write OK)

# Phase 4 US2 — extractor implementation can land before story_polish stage:
Task T031: implement utils/extractors.py                     # [P] — independent of T032+

# Phase 5 US3 — all four tests in test_hiring_review.py — sequential write but semantically independent
Task T037: test_hiring_review_prompt_includes_six_craft_dimensions  # [P]
Task T038: test_hiring_review_parses_craft_dimensions               # [P]

# Phase 6 — polish tasks are independent operations:
Task T045: prompts/styles/aida.md restrained tone           # [P]
Task T046: ENGINEERING.md update                            # [P]
Task T048: jobagent prompts sync                            # [P]
```

---

## Implementation Strategy

### MVP: Foundational + US1 Only

1. Complete Phase 1 (verify baseline)
2. Complete Phase 2 (extract role_position into its own stage; baseline still passes)
3. Complete Phase 3 (US1) — NarrativeStrategy + planner + writer consumption
4. **STOP**: the pipeline now produces letters with an explicit story spine. The artefacts under `outputs/<run_id>/artifacts/narrative_strategy.json` carry the strategy. US2 adds the polish pass; US3 adds the reviewer extension. Either is shippable independently after US1

### Incremental Delivery

1. Phase 1 → verification ✓
2. Phase 2 → role_position extracted; pipeline unchanged in behaviour ✓
3. Phase 3 (US1) → narrative_strategy upstream; story-spine emission ✓
4. Phase 4 (US2) → polish pass with deterministic post-check ✓
5. Phase 5 (US3) → reviewer craft dimensions + German over-analogy scan ✓
6. Phase 6 → docs, full sweep, Langfuse prompt-version push ✓

### Parallel Team Strategy

With two contributors after Phase 2 lands:

- Contributor A: US1 (schema + planner + writer + prompts)
- Contributor B: US2 (extractors + story_polish stage) — can start once T020 (workflow.py edit in US1) lands; otherwise T035 will conflict
- Either picks up US3 once US1's writer changes (T023+T024) are in (the reviewer prompt change in T042 references the narrative_strategy fields documented for the writer)

---

## Notes

- `[P]` = different files (or sufficiently independent test methods within the same file), safe to draft in parallel
- `[USN]` = maps to user story N in spec.md
- **Three new pipeline stages** (`role_position`, `narrative_strategy`, `story_polish`), **three modified stages** (`plan_content`, `write_letter`, `hiring_review`), **four prompt edits** (`planner.md`, `writer.md`, `hiring_reviewer.md`, `styles/aida.md`), **three new prompts** (`role_positioner.md`, `narrative_strategist.md`, `story_polisher.md`), **two new artefact JSON files** (`narrative_strategy.json`, `story_polish_output.json`)
- **Feature 007 prompt registry**: T005 + T018 + T022 + T024 + T033 + T042 + T045 edit/create seven prompt files. The next `jobagent prompts sync` (T048) MUST report `7 created, 3 unchanged`. Any other count signals an unintended prompt edit — investigate with `git diff prompts/` before merging
- **Retrieval / requirement extraction / evidence mapping intentionally NOT edited** — feature spec FR-035–FR-038 enforce these out-of-scope guarantees
- **Writer isolation invariant preserved** — `narrative_strategy` rides on the existing `WorkflowState` typed object; the writer's typed input surface gains one new field but still receives no raw `InternalKnowledge` (FR-035 isolation invariant maintained)
- **Constitution Principle I (factual integrity)** is mechanised by the `story_polish` deterministic post-check (T031, T034). The post-check is the load-bearing correctness contract — its tests (T026 sub-tests) are the highest-priority TDD red phase in this feature
- **Backward compat = automatic** — the schema design (`Optional` `narrative_strategy`, `default_factory=list` `paragraphs`-like list fields, `Optional` `story_polish_output`, `Optional` `craft_dimensions`) makes legacy `WorkflowState` load without explicit migration; T025 + T036 + T044 verify cumulatively
- **Test count math**: ~26 new tests (8 US1 + 5 US2 + 4 US3 + ~3 from T004 role_position + 6 sub-tests rolled into T026 extractors). Expected suite: 266 + ~26 = ~292 passed
- **Cost**: +2 LLM calls per run when both new stages are enabled (`narrative_strategy` + `story_polish`); +1 when only `narrative_strategy` runs (story_polish disabled); 0 extra calls beyond baseline if both disabled (the extracted `role_position` call replaces a portion of the planner's prior call). Net cost-controllable via `NarrativePolishConfig`
