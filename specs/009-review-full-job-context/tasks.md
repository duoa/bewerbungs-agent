# Tasks: Hiring Review with Full Job Context

**Input**: Design documents from `/specs/009-review-full-job-context/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-020..FR-025 enumerate the required automated tests and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task begins. All tests use mocked LLM responses — no real Anthropic calls in unit tests.

**Organization**: Tasks grouped by user story. US1 (P1) is the MVP — parsed structured job-context fields make role-match judgements more grounded by themselves. US2 (P2) adds content-plan visibility for plan-vs-letter drift detection. US3 (P3) adds the new always-on `critical_requirements_underweighted` dimension.

**Scope discipline**: This feature touches exactly two source files (`stages/hiring_review.py`, `prompts/hiring_reviewer.md`) and one test file (`tests/unit/test_hiring_review.py`). No new schema, no new pipeline stage, no edits to any other prompt or stage.

---

## Phase 1: Setup

**Purpose**: No new dependencies; this is a context-passing feature reusing existing toolchain. One verification step.

- [X] T001 Verify the 230-test baseline (post-feature-008) passes by running `.venv/bin/pytest tests/ --tb=short` and capture the count for the Phase 6 sweep

---

## Phase 2: Foundational

**Purpose**: NONE. The feature has no foundational blocker — each user story edits a different part of the same prompt + `build_prompt` function. Tests for each story are written in their own phase; the existing 230-test suite continues to pass throughout.

(No foundational tasks. Skip directly to Phase 3.)

---

## Phase 3: User Story 1 — Reviewer Sees the Complete Job Context (Priority: P1) 🎯 MVP

**Goal**: `stages/hiring_review.py::build_prompt` additionally inserts a `## Parsed Job Context` block from `state.job_context` fields (job_title, company_name, optional raw_company_text, optional raw_storyboard_text). Optional fields are silently omitted when None. Legacy paths where `state.job_context is None` continue to build cleanly.

**Independent Test**: Build a `WorkflowState` whose `job_context` carries a recognisable job_title + company_name + optional company info + optional storyboard text; call `build_prompt(state)`; assert the constructed user message contains every populated field verbatim under a `## Parsed Job Context` heading. Build a separate state where `job_context` is None; assert no exception and the prompt still contains the documented placeholder.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T005

- [X] T002 [P] [US1] Write failing test `test_prompt_includes_parsed_job_context_structured_fields` in `tests/unit/test_hiring_review.py` — build a state via `_state_with_job_text(...)` extended with `job_title="Senior Software Engineer — AI/ML Infrastructure"`, `company_name="Helix Compute GmbH"`, `raw_company_text="Helix Compute is a Berlin-based platform team serving research partners."`, `raw_storyboard_text="Lead with infra builder identity."`; call `build_prompt(state)`; assert the constructed user message contains substring `"## Parsed Job Context"`, the verbatim `"Helix Compute GmbH"`, the verbatim job_title, the verbatim company_info, and the verbatim storyboard text (FR-001, FR-002, FR-020, SC-001, SC-002)
- [X] T003 [US1] Write failing test `test_prompt_omits_absent_optional_fields_gracefully` in `tests/unit/test_hiring_review.py` — build a state where `job_context` has only `raw_job_text` and `job_title` (no `company_name`, no `raw_company_text`, no `raw_storyboard_text`); call `build_prompt(state)`; assert the prompt does NOT contain literal substrings `"company_info:"` or `"storyboard:"` or any `"(none)"` placeholder for these fields (FR-004)
- [X] T004 [P] [US1] Write failing regression test `test_review_flags_secondary_domain_opening_with_high_severity` in `tests/unit/test_hiring_review.py` — construct a canned LLM review payload that flags the "opening" section with two weaknesses: `"role_match: letter leads with biomedical-ML, but the job ad emphasises scalable cloud infrastructure"` and `"secondary_topic_dominance: opening paragraph spent on adjacent-domain experience"`, both at severity `"high"`, plus a clean "experience" section; call `parse_response(payload, WeaknessSeverity.medium)`; assert `"opening" in report.sections_to_rewrite`, assert `"experience" not in report.sections_to_rewrite`, assert both weakness texts are preserved on the opening section's `weaknesses[*].text` (FR-023, SC-008)

### Implementation for User Story 1

- [X] T005 [US1] Update `prompts/hiring_reviewer.md` Inputs section per contracts §1.1 — extend the bulleted "You receive:" list to mention the parsed structured job context (job title, company name, optional company-info and storyboard texts). Do NOT touch anything else in the file yet; US2 and US3 will edit different sections.
- [X] T006 [US1] Update `stages/hiring_review.py::build_prompt` per contracts §2 — insert a `## Parsed Job Context` block between the existing `## Original Job Description (verbatim)` block and the existing `## Role Requirements` block; populate it from `state.job_context.job_title`, `state.job_context.company_name`, `state.job_context.raw_company_text`, `state.job_context.raw_storyboard_text`; SKIP any individual field that is None; OMIT the entire block when `state.job_context is None` OR when every structured field is None (FR-003, FR-004)
- [X] T007 [US1] Confirm all US1 tests (T002–T004) pass; confirm the existing 230-test baseline still passes (no regression)

**Checkpoint**: The reviewer now sees the complete job context. The MVP is shippable — even without US2 and US3, role-match and opening-alignment judgements gain precision because the reviewer reads the structured fields the loader extracted in addition to the raw text feature 008 already provided.

---

## Phase 4: User Story 2 — Reviewer Sees the Content Plan (Priority: P2)

**Goal**: `stages/hiring_review.py::build_prompt` additionally inserts a `## Content Plan (read-only context — evaluate only the letter)` block from `state.content_plan` — section titles + first three key_claims per section + (when present) the role_positioning summary + (when present) `evidence_map.known_gaps`. Legacy paths where `state.content_plan is None` continue to build cleanly.

**Independent Test**: Build a state whose `content_plan` carries 2–3 sections with key_claims and a populated `role_positioning` (infrastructure-flavoured); call `build_prompt(state)`; assert the prompt contains a `## Content Plan` heading, each section title, each key claim string, and the role_positioning's primary_role_family and opening_angle values. Separately build a state with `content_plan=None`; assert no exception and the prompt omits the content-plan block entirely.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T011

- [X] T008 [P] [US2] Write failing test `test_prompt_includes_content_plan_summary` in `tests/unit/test_hiring_review.py` — build a state with a `ContentPlan` whose `sections` are `[SectionPlan(title="role_fit", key_claims=["Built scalable Python ML platforms", "Owned inference SLOs"], evidence_refs=[]), SectionPlan(title="platform_experience", key_claims=["Operated EKS fleets"], evidence_refs=[])]`; call `build_prompt(state)`; assert the prompt contains substring `"## Content Plan"`, contains `"role_fit"`, contains `"Built scalable Python ML platforms"`, contains `"platform_experience"`, contains `"Operated EKS fleets"` (FR-005, FR-006, FR-020, SC-003)
- [X] T009 [US2] Write failing test `test_prompt_includes_role_positioning_when_present` in `tests/unit/test_hiring_review.py` — build a state whose `content_plan.role_positioning` is populated with `primary_role_family="AI/ML platform engineering"`, `opening_angle="Lead with infrastructure-builder identity."`, `topics_to_deemphasise=["biomedical domain depth"]`; call `build_prompt(state)`; assert the prompt contains substring `"Role Positioning"`, contains `"AI/ML platform engineering"`, contains `"Lead with infrastructure-builder identity."`, contains `"biomedical domain depth"` (FR-006, SC-003)
- [X] T010 [US2] Write failing test `test_prompt_builds_when_content_plan_is_none` in `tests/unit/test_hiring_review.py` — build a state with `content_plan=None` (the default for a state without going through the planner); call `build_prompt(state)`; assert no exception raised; assert the prompt does NOT contain substring `"## Content Plan"` (FR-005, FR-022, SC-005)

### Implementation for User Story 2

- [X] T011 [US2] Update `prompts/hiring_reviewer.md` per contracts §1.1 and §1.2 — extend the "You receive:" list to mention the content plan; add a new strict-constraint bullet explaining the plan is read-only context and the reviewer evaluates only the letter (FR-007); do NOT touch the dimensions section yet (US3 covers that)
- [X] T012 [US2] Update `stages/hiring_review.py::build_prompt` per contracts §2 — insert a `## Content Plan (read-only context — evaluate only the letter)` block AFTER the `## Role Requirements` block and BEFORE the `## Evaluation Dimensions` block; populate it from `state.content_plan.sections[*].title + key_claims[:3]` (first three key_claims per section), `state.content_plan.role_positioning` sub-fields (when role_positioning is not None), and `state.content_plan.evidence_map.known_gaps` (when non-empty); OMIT the entire block when `state.content_plan is None`; OMIT the Role Positioning sub-block when `role_positioning is None`; OMIT the Known Gaps sub-block when `known_gaps` is empty (FR-005, FR-006)
- [X] T013 [US2] Confirm all US2 tests (T008–T010) pass; confirm US1 tests still pass; confirm the existing 230-test baseline still passes

**Checkpoint**: The reviewer now sees both the full job context (US1) and the content plan that produced the letter (US2). Plan-vs-letter drift becomes callable out concretely in weakness text. US3 layer below adds the sixth always-on dimension.

---

## Phase 5: User Story 3 — `critical_requirements_underweighted` Dimension (Priority: P3)

**Goal**: A new always-on evaluation dimension is added alongside feature 008's five positioning dimensions. The prompt enumerates it; the build_prompt active-dims list includes it; the existing parser routes any `critical_requirements_underweighted: …` weakness at severity ≥ threshold into `sections_to_rewrite` (no parser change needed — severity-driven routing).

**Independent Test**: Call `build_prompt(any_state)`; assert the constructed user message contains `"critical_requirements_underweighted"` in the dimensions list. Construct a canned LLM payload with a single weakness on the "experience" section tagged `"critical_requirements_underweighted: ..."` at severity `"medium"`; call `parse_response(payload, WeaknessSeverity.medium)`; assert `"experience" in report.sections_to_rewrite`.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T016

- [X] T014 [P] [US3] Write failing test `test_active_dimensions_includes_critical_requirements_underweighted` in `tests/unit/test_hiring_review.py` — build any minimal state (use existing `_state_with_job_text` or `_make_state`); call `build_prompt(state)`; assert the prompt contains substring `"critical_requirements_underweighted"`; assert the prompt also still contains the five feature-008 dimension names (`"role_match"`, `"opening_alignment"`, `"secondary_topic_dominance"`, `"tool_density"`, `"overclaiming"`) — verifying the new dimension is additive, not a replacement (FR-008, FR-024, SC-006)
- [X] T015 [P] [US3] Write failing test `test_critical_requirements_underweighted_routes_to_rewrite` in `tests/unit/test_hiring_review.py` — construct a canned LLM payload with one section "experience" carrying one weakness `text="critical_requirements_underweighted: scalable cloud infrastructure barely mentioned; the job ad lists it as a top responsibility"`, `severity="medium"`, `priority_fix="add a paragraph on scalable-infrastructure responsibilities"`; call `parse_response(payload, WeaknessSeverity.medium)`; assert `"experience" in report.sections_to_rewrite`; assert the weakness text is preserved verbatim on the parsed section's weaknesses list (FR-009, FR-010, FR-025, SC-007)

### Implementation for User Story 3

- [X] T016 [US3] Update the `_POSITIONING_DIMENSIONS` tuple in `src/bewerbungs_agent/stages/hiring_review.py` to append `"critical_requirements_underweighted"` as the sixth entry, after `"overclaiming"`. Update the surrounding docstring to clarify the tuple is the always-on dimensions list (a mix of positioning + coverage dimensions). (FR-008, contracts §2)
- [X] T017 [US3] Update `prompts/hiring_reviewer.md` per contracts §1.3 and §1.4 — (a) rename the "Five positioning-specific dimensions" heading to "Six positioning-specific dimensions"; (b) add a new bullet under that heading describing `critical_requirements_underweighted` per contracts §1.3 (failure criterion: top job responsibilities receive thin or no treatment in the letter; honest gaps in plan's `known_gaps` are NOT failures); (c) extend the severity-calibration paragraph to mention this dimension follows the same medium/high logic; (d) preserve all existing prompt content
- [X] T018 [US3] Update the existing `test_hiring_review_prompt_contains_only_active_dimensions` test in `tests/unit/test_hiring_review.py` to expand its expectation from the feature-008 five dimensions to the now-six always-on dimensions (add `"critical_requirements_underweighted"` to the expected dim set); preserve the test's existing assertion shape (FR-014 backward-compat through prompt expansion, not breakage)
- [X] T019 [US3] Confirm all US3 tests (T014, T015) pass; confirm the updated existing test T018 passes; confirm US1 and US2 tests still pass; confirm the full 230+US1+US2+US3 test count is correct

**Checkpoint**: All six always-on positioning + coverage dimensions are wired and tested. The reviewer can now identify three orthogonal failure modes: positioning failures (5 dims from feature 008), coverage failures (1 dim from this feature), plus whatever the operator configured in `review_config.dimensions`. The targeted-rewrite stage routes them all via the existing severity-driven `sections_to_rewrite` mechanism — no downstream code change needed.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T020 [P] Update `ENGINEERING.md` — add a brief paragraph to Section 19 (Role-Positioned Prompting) or Section 16 (Hiring-Manager Review) noting that feature 009 extended the hiring-review prompt to include the parsed structured `job_context` fields, the content plan summary, and the new `critical_requirements_underweighted` always-on dimension; mention the graceful-omission behaviour for legacy/None paths
- [X] T021 Run the full test suite `.venv/bin/pytest tests/ --tb=short`; expected count = previous baseline (230) + 3 US1 + 3 US2 + 2 US3 = 238 passed (T018 modifies an existing test, doesn't add one); halt and fix if any regression
- [X] T022 Run static checks on the files this feature touches: `.venv/bin/ruff check src/bewerbungs_agent/stages/hiring_review.py tests/unit/test_hiring_review.py` and `.venv/bin/mypy src/bewerbungs_agent/stages/hiring_review.py`; fix any errors introduced by this feature (do NOT fix pre-existing errors out of scope)
- [X] T023 Run quickstart §6 manual smoke test (or document explicit deferral) — `jobagent run --job data/examples/jobs/sample_ml_infrastructure.md --template default_de_neutral`, then inspect the `hiring_review` Langfuse trace span's input metadata and confirm the `## Parsed Job Context` and `## Content Plan` blocks are present, and that the dimensions list includes `critical_requirements_underweighted`
- [X] T024 [P] Push the one new prompt version to Langfuse: `uv run jobagent prompts sync --label staging`; expected output: `"Summary: 1 created, 9 unchanged, 0 relabeled, 0 failed."` — the one created is `bewerbungs-agent/hiring_reviewer` (FR-019). If the output reports more or fewer than 1 created, an unintended prompt was modified; investigate with `git diff prompts/` before continuing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial verification — start immediately.
- **Foundational (Phase 2)**: NONE — skip directly to Phase 3.
- **US1 (Phase 3)**: independent. Edits its own block of `build_prompt`. Independently testable.
- **US2 (Phase 4)**: independent of US1's implementation (edits a different block of `build_prompt`); reads `state.content_plan` which feature 008 already added. Can be implemented in parallel with US1 once Phase 1 is done.
- **US3 (Phase 5)**: independent of US1 and US2 implementations. Edits the `_POSITIONING_DIMENSIONS` tuple + adds one prompt bullet + updates one existing test. Can be implemented in parallel with US1/US2 once Phase 1 is done.
- **Polish (Phase 6)**: depends on US1+US2+US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI).
- US1: T005 (prompt edit) and T006 (build_prompt edit) are in different files and can be done in either order; both must land before T007 verification.
- US2: T011 (prompt edit) and T012 (build_prompt edit) are in different files and can be done in either order; both must land before T013 verification.
- US3: T016 (tuple update) → T017 (prompt edit) → T018 (existing-test expectation update) → T019 verification. The tuple update enables the dims-list test (T014) to pass; the prompt edit makes the prompt content reflect what's already wired.

### Cross-story consideration: test_hiring_review_prompt_contains_only_active_dimensions

This existing test (from feature 008) asserts the dims string against the feature-008 five-tuple. US3 expands the tuple to six. T018 is the explicit task that updates the existing test's expectation. If US1 or US2 ship before US3, this test continues to pass (the dims string still contains the feature-008 five). After US3 ships, the test would FAIL without T018 — that's why T018 is part of US3's implementation, not a separate cleanup.

---

## Parallel Opportunities

```bash
# Phase 1: single-task verification.

# Phase 3 US1 — failing tests can be drafted in parallel (different test methods in the same file):
Task T002: test_prompt_includes_parsed_job_context_structured_fields
Task T004: test_review_flags_secondary_domain_opening_with_high_severity  # [P] — different test method

# Phase 4 US2 — three tests are in the same file (write sequentially), but US2 itself
# is independent of US1 implementation, so the whole phase can run in parallel with US1.

# Phase 5 US3 — two failing tests are in the same file (write sequentially), but US3
# is independent of US1/US2 implementation, so the phase can run in parallel.
Task T014: test_active_dimensions_includes_critical_requirements_underweighted  # [P] — different concern
Task T015: test_critical_requirements_underweighted_routes_to_rewrite           # [P] — different concern

# Phase 6 polish — docs edit and prompts sync are independent of each other:
Task T020: Update ENGINEERING.md     # [P]
Task T024: jobagent prompts sync     # [P] — independent operation
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 1 (verify baseline).
2. Skip Phase 2 (none).
3. Complete Phase 3 (US1) — reviewer reads the parsed structured `job_context` fields in addition to the raw text feature 008 already provided.
4. **STOP**: the reviewer is already more grounded. Role-match and opening-alignment weaknesses gain precision because the reviewer sees the company name, job title, and optional company-info/storyboard text — not just the agent's extracted-requirements summary. US2 (content plan) and US3 (new dimension) layer on without disturbing the MVP.

### Incremental Delivery

1. Phase 1 → verification ✓
2. Phase 3 (US1) → reviewer reads full job context ✓ (MVP shippable)
3. Phase 4 (US2) → reviewer reads the content plan; plan-vs-letter drift becomes callable out ✓
4. Phase 5 (US3) → sixth always-on dimension catches under-coverage of critical requirements ✓
5. Phase 6 → docs, full test sweep, Langfuse prompt-version push ✓

### Parallel Team Strategy

With three contributors after Phase 1 lands, all three user stories can proceed in parallel:

- Contributor A: US1 (parsed structured fields block)
- Contributor B: US2 (content plan block + read-only constraint)
- Contributor C: US3 (sixth dimension + tuple update + existing test expectation update)

The three streams edit different sections of `build_prompt` and different sections of `hiring_reviewer.md`. The final merge produces a single coherent prompt and a single coherent build_prompt function. Phase 6 ties them together.

---

## Notes

- `[P]` = different files OR sufficiently-independent test methods, safe to draft in parallel.
- `[USN]` = maps to user story N in spec.md.
- **No schema changes** — the new dimension reuses feature 008's tagging convention; the routing through `sections_to_rewrite` is severity-driven and needs no parser change.
- **Feature 007 prompt registry**: the next `jobagent prompts sync` (T024) MUST report `1 created, 9 unchanged`. The one created is `bewerbungs-agent/hiring_reviewer`. Any other count signals an unintended prompt edit — investigate before merging.
- **Backward-compat through tests**: T010 (US2) and T003 (US1 graceful omission) plus the inherited feature 008 path test (`test_hiring_review_prompt_builds_when_job_context_unavailable` if it exists) cover the legacy/None paths required by FR-003, FR-005, FR-021, FR-022.
- **Non-interference structurally guaranteed**: no MLflow tag names change, no Langfuse span shape changes, no CLI contract change — verified by the existing 230-test suite continuing to pass after T021.
- **Honest-gap carve-out (FR-011)**: enforced by prompt instruction alone (per research.md §R6). No code-side filter. If false positives are observed in production, a later feature can add a deterministic post-parse check.
- **The `_POSITIONING_DIMENSIONS` constant** keeps its name even though the sixth entry is a coverage dimension rather than a positioning dimension. A broader rename is out of scope; the constant's docstring is updated to reflect the broader semantic (T016).
