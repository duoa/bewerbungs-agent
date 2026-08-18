# Feature Specification: ContentPlan as a Hiring Story

**Feature Branch**: `011-contentplan-hiring-story`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "Upgrade the ContentPlan schema so it represents a clear hiring story, not only a list of claims. Add fields for letter_thesis, paragraph purpose, main_message, requirement_ids, evidence_refs, max_claims, max_tools, emphasise, and deemphasise. The opening paragraph must be planned around the primary role positioning. Each paragraph must have one main message and a limited number of claims. The planner should use weighted requirements and role_positioning to decide what to emphasize and what to de-emphasize. The writer must remain restricted to the ContentPlan and must not see raw profile data. Do not change evidence retrieval or hiring review behavior in this feature. Add tests showing that each planned paragraph has one main message, that the opening paragraph reflects the primary role positioning, and that tool-heavy paragraphs can be constrained by max_tools."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Planner Emits a Story-Shaped Content Plan (Priority: P1) 🎯 MVP

Today the content plan is a useful structure but treats the cover letter as a flat list of sections with claims. Reading it doesn't immediately tell the operator "what's the story this letter is telling about why this candidate fits this role". This story upgrades the plan to carry an explicit `letter_thesis` at the top level — a single sentence stating the candidate's case for the role — plus a list of paragraph-level plans where each paragraph carries an explicit `purpose` (its role in the story), a `main_message` (the single core idea the paragraph delivers), and references to the `requirement_ids` and `evidence_refs` it draws on. The opening paragraph is specifically planned around the role's primary positioning (the `role_family` and `opening_angle` decided by feature 008/010). A reviewer reading the resulting plan can trace, paragraph by paragraph, the story the letter will tell — before any prose exists.

**Why this priority**: This is the foundation. The downstream writer reads the plan and produces prose; without a story-shaped plan the prose will continue to read as a flat list of accomplishments. US2 (density limits) and US3 (backward compat) only deliver value once the new structure exists.

**Independent Test**: Run the planner against the AI/ML infrastructure fixture. Assert the returned content plan has: (a) a non-empty `letter_thesis`, (b) a list of paragraph-level plans each with `purpose`, `main_message`, `requirement_ids`, `evidence_refs`, (c) the first paragraph's `purpose` is "opening" (or equivalent) AND its `main_message` references the planner's `role_positioning.role_family` or `opening_angle`. Separately assert each paragraph has exactly ONE `main_message` (not a list).

**Acceptance Scenarios**:

1. **Given** a populated workflow state, **When** the planner runs, **Then** the returned content plan carries a non-empty `letter_thesis` (one sentence stating the candidate's case for the role).
2. **Given** the same plan, **When** any paragraph is inspected, **Then** it carries a non-empty `purpose` value (e.g., "opening", "experience", "platform_credibility", "closing") and a non-empty `main_message` (one sentence) — `main_message` is a single string, not a list.
3. **Given** the same plan, **When** any paragraph is inspected, **Then** it carries a `requirement_ids` list of zero or more references to the `requirement_items` produced by feature 010's extractor, and an `evidence_refs` list of zero or more claim-text references that exist in the plan's evidence map.
4. **Given** the same plan, **When** the opening (first) paragraph is inspected, **Then** its `purpose` indicates an opening role AND its `main_message` references the role family or opening angle from the plan's `role_positioning` (e.g., references "infrastructure", "platform", or the configured opening angle string).
5. **Given** a paragraph that lists topics from the planner's `emphasise` list in its `emphasise` field, **When** the writer downstream reads the paragraph, **Then** the writer can produce prose that develops those topics in this paragraph specifically (vs distributing them across paragraphs).

---

### User Story 2 — Per-Paragraph Density Limits (Priority: P2)

Each paragraph plan additionally carries `max_claims` and `max_tools` integers that cap how many distinct claims and tool/technology names the paragraph may contain. The planner sets these per paragraph based on the paragraph's purpose: an "opening" paragraph may have `max_claims=1` (the headline), while a "platform_credibility" paragraph may have `max_claims=3` and `max_tools=4`. The writer consumes the limits as hard constraints during prose generation; the hiring review can also use them to detect violations.

**Why this priority**: P2 because US1 already produces better-shaped plans; density limits add per-paragraph quality control. Without them the writer (per feature 008's tool-density rule) caps tool names globally but doesn't know the paragraph-specific intent — an "opening" paragraph and a "platform_credibility" paragraph have different appropriate densities.

**Independent Test**: Construct a content plan whose paragraphs carry `max_claims=2` and `max_tools=4`; assert the model validates without error. Construct an invalid plan with `max_claims=0` or `max_tools=-1`; assert validation raises. Construct a paragraph whose `evidence_refs` list length exceeds its `max_claims`; assert validation raises (the planner cannot promise to use more claims than the paragraph allows).

**Acceptance Scenarios**:

1. **Given** a paragraph plan with `max_claims=3` and `max_tools=4`, **When** validated, **Then** the model accepts both integers as positive bounded values.
2. **Given** a paragraph whose `evidence_refs` length is 5 and `max_claims` is 3, **When** validated, **Then** the model raises a clear error naming the violating paragraph.
3. **Given** the writer reads a paragraph plan with `max_tools=4`, **When** the writer's prompt is constructed, **Then** the prompt explicitly tells the writer this paragraph caps at 4 distinct tool names (replacing or refining the global cap from feature 008's `writer_rules.tool_density_max` for this paragraph only).
4. **Given** an "opening" paragraph with `max_claims=1`, **When** the writer's prompt is constructed, **Then** the prompt instructs the writer to use at most one specific claim in the opening — preventing the opening from being a paragraph-long enumeration.

---

### User Story 3 — Backward Compatibility for Legacy ContentPlan Artifacts (Priority: P3)

The repository contains artifacts from earlier runs whose `ContentPlan` JSON does not include `letter_thesis` or the new paragraph-level fields. Engineers occasionally re-load these artifacts during debugging or re-validation. The new model must continue to load every legacy artifact without raising — the new fields default to documented safe values (None for `letter_thesis`; empty list for `paragraphs`; the legacy `sections` field stays populated and usable). The new fields are additive; nothing is removed from the legacy shape.

**Why this priority**: P3 because the value of the feature lands with US1+US2; backward compatibility is a quality-of-life invariant for debugging older runs, not a feature enabling new capability. Existing tests that build minimal `ContentPlan` instances must continue to pass without modification.

**Independent Test**: Construct a JSON document matching the pre-feature `ContentPlan` shape (no `letter_thesis`, no `paragraphs`, only the existing `sections` etc.); load it via the new model; assert the load succeeds and the new fields take their documented defaults (None / empty list). Construct a JSON document containing an unknown top-level key; assert validation raises (preserving `extra="forbid"` discipline from earlier features).

**Acceptance Scenarios**:

1. **Given** a `ContentPlan` JSON written by a pre-feature run (no `letter_thesis`, no `paragraphs`), **When** the new model loads it, **Then** the load succeeds, `letter_thesis` is None, `paragraphs` is an empty list, and all legacy fields (`sections`, `selected_soft_skills`, `evidence_map`, `role_positioning`, ...) are populated unchanged.
2. **Given** a new-shape `ContentPlan` (with `letter_thesis` and `paragraphs`), **When** loaded, **Then** all fields validate and downstream consumers see both the new and the legacy shapes (e.g., the writer can fall back to `sections` when `paragraphs` is empty — or vice versa).
3. **Given** a JSON document with a typo top-level key (e.g., `lettre_thesis`), **When** loaded, **Then** the model surfaces a clear validation error.

---

### Edge Cases

- **A paragraph plan has zero `requirement_ids`**: valid — some paragraphs (e.g., "motivation", "closing") may not directly cover a specific job requirement but still play a role in the story. The writer treats the paragraph as motivational / framing.
- **A paragraph's `requirement_ids` reference an ID that does not exist in the run's `requirement_items`**: the model raises a clear error naming both the paragraph and the missing ID — prevents stale references from a partially-edited plan.
- **`max_claims` set to 1 on an opening paragraph**: enforced; the writer is constrained to use exactly one anchored claim in the opening.
- **A `letter_thesis` longer than ~300 characters**: validated against an upper bound; the model raises a clear error to keep the thesis a single sentence rather than a paragraph.
- **`paragraphs` is populated but `sections` is also populated (legacy + new)**: both are stored as written; downstream consumers prefer `paragraphs` when present. No automatic conversion in this feature.
- **`paragraphs` is empty but `sections` is populated (legacy plan re-used in a new-feature run)**: the writer falls back to reading `sections`; no new behaviour is forced on the writer. The plan is valid but doesn't get the per-paragraph density benefit.
- **`paragraphs[0].purpose` is something other than "opening"**: valid — the planner may use any short-name convention; the test for "opening paragraph reflects role_positioning" checks the FIRST paragraph regardless of its `purpose` label.
- **The planner cannot fit all `priority=high` requirements into a small paragraph count**: the planner SHOULD bias toward giving high-priority requirements their own paragraph; the model does NOT validate this (it's a quality concern caught by hiring_review's `critical_requirements_underweighted` dimension from features 008/009).

## Requirements *(mandatory)*

### Functional Requirements

#### Hiring-story content plan structure

- **FR-001**: The `ContentPlan` MUST gain a top-level `letter_thesis: str | None` field — a single-sentence statement of the candidate's case for THIS role. Optional for backward compatibility; populated by the planner going forward.
- **FR-002**: The `ContentPlan` MUST gain a top-level `paragraphs: list[ParagraphPlan]` field. Each `ParagraphPlan` represents one paragraph the cover letter will contain. The list is ordered; index 0 is the opening paragraph.
- **FR-003**: Each `ParagraphPlan` MUST carry a `purpose: str` field — a short label describing the paragraph's role in the story (e.g., "opening", "platform_credibility", "infrastructure_experience", "working_style", "motivation", "closing"). The set of allowed values is open (the planner chooses).
- **FR-004**: Each `ParagraphPlan` MUST carry a `main_message: str` field — the SINGLE core idea the paragraph delivers, expressed as one sentence (not a list, not multiple sentences). Bounded length (≤ 300 chars) prevents the field from sprawling into a draft paragraph.
- **FR-005**: Each `ParagraphPlan` MUST carry a `requirement_ids: list[str]` field referencing the `RequirementItem.id` values from the run's weighted-requirement extraction (feature 010). Each referenced id MUST exist in the run's `requirements.requirement_items`; an invalid reference raises a clear validation error.
- **FR-006**: Each `ParagraphPlan` MUST carry an `evidence_refs: list[str]` field referencing claim texts that exist in the plan's `evidence_map.items`. Same validity-check pattern as `requirement_ids`.
- **FR-007**: Each `ParagraphPlan` MUST carry `emphasise: list[str]` and `deemphasise: list[str]` paragraph-level fields. These guide what the writer should foreground (or downplay) WITHIN this paragraph, complementing (not replacing) the plan-level `role_positioning.emphasise` / `deemphasise` fields established by feature 010.

#### Density limits

- **FR-008**: Each `ParagraphPlan` MUST carry a `max_claims: int` field constrained to the range [1, 8]. The planner sets this per paragraph based on its purpose; the writer downstream uses it as a hard upper bound on the number of distinct claims expressed in the paragraph.
- **FR-009**: Each `ParagraphPlan` MUST carry a `max_tools: int` field constrained to the range [0, 12]. Zero is valid for paragraphs that should not name any tool (e.g., a motivation paragraph). The writer uses this as a hard upper bound, OVERRIDING the global `writer_rules.tool_density_max` (feature 008) for this paragraph specifically.
- **FR-010**: The model MUST validate that `len(evidence_refs) <= max_claims` for every paragraph. A paragraph cannot promise to use more claims than its own cap allows.

#### Opening paragraph reflects positioning

- **FR-011**: The opening paragraph (index 0 of `paragraphs`) MUST be planned around the plan's `role_positioning.role_family` and `role_positioning.opening_angle` (when `role_positioning` is set). The opening's `main_message` MUST reference the role family or opening angle in substance — verified by a substring check in the test for the AI/ML infrastructure fixture (e.g., contains "infrastructure", "platform", "AI/ML", or matching opening-angle terms).
- **FR-012**: The opening paragraph's `max_claims` MUST be 1 or 2 — never more — to prevent the opening from becoming a paragraph-long enumeration. Validated at parse time.

#### Planner consumption + behaviour

- **FR-013**: The planner stage MUST use the weighted `requirement_items` (feature 010) AND the `role_positioning` (feature 008/010) as the primary inputs when constructing `paragraphs`. High-priority requirements get their own dedicated paragraph (or at least appear as the leading `evidence_refs` of a paragraph); low-priority requirements may share a paragraph or be omitted.
- **FR-014**: The planner stage's prompt MUST explicitly instruct the LLM to: (a) write a `letter_thesis` first, then (b) plan paragraphs in order around the story it implies, (c) ensure the opening paragraph reflects the role family / opening angle, (d) set per-paragraph `max_claims` and `max_tools` based on the paragraph's purpose, and (e) consult the `emphasise` / `deemphasise` lists from `role_positioning` when picking what to develop and what to avoid.

#### Writer isolation invariant preserved

- **FR-015**: The writer stage MUST continue to receive ONLY the `ContentPlan` (no raw profile, no CV, no evidence-map passages it didn't already see). The new fields ride INSIDE the existing `ContentPlan` typed object the writer already consumes; no new constructor argument is added.
- **FR-016**: The writer's prompt MUST be extended (per US2) so the writer is aware of the per-paragraph `max_claims` and `max_tools` limits and can respect them. The writer's existing global rules (tool-density cap from `writer_rules`, banned-phrase ban, role-first opening, etc.) remain in force; per-paragraph limits OVERRIDE the global tool-density cap when stricter.

#### Non-interference with retrieval and hiring review

- **FR-017**: Evidence retrieval (CV variant selection, profile loading, `build_evidence_map`) MUST be unchanged.
- **FR-018**: Hiring-review behaviour MUST be unchanged in shape: same dimensions, same prompt structure, same weakness tagging convention. The reviewer naturally benefits from the richer plan (more grounded judgements on role match and opening alignment) because the content-plan summary block (feature 009) automatically surfaces the new `letter_thesis` and per-paragraph `main_message` values — that visibility is incidental and does not change any hiring-review code path.
- **FR-019**: MLflow tag/metric NAMES MUST be unchanged. Per-prompt content hashes for `planner` (and possibly `writer` and `hiring_reviewer` if those prompts are extended) WILL flip naturally; tag names stay the same.
- **FR-020**: Langfuse trace topology MUST be unchanged: same per-stage spans, same metadata field names. The `prompt_content_hash` on the `plan_content` span (and any other edited prompts) flips naturally — expected signal of the edit.
- **FR-021**: CLI contract MUST be unchanged: same commands, flags, exit codes, output files.

#### Backward compatibility

- **FR-022**: The new `ContentPlan` model MUST accept legacy JSON documents (no `letter_thesis`, no `paragraphs`). `letter_thesis` defaults to None; `paragraphs` defaults to `[]`. All legacy fields (`sections`, `selected_soft_skills`, `evidence_map`, `role_positioning`, ...) continue to load and behave as before.
- **FR-023**: The `extra="forbid"` discipline MUST be preserved on `ContentPlan` and the new `ParagraphPlan`. Unknown top-level keys surface as validation errors.

#### Tests

- **FR-024**: The system MUST include an automated test asserting that, for a canned planner response with the new structure, every paragraph's `main_message` is a non-empty single string (not a list).
- **FR-025**: The system MUST include an automated test asserting that the opening paragraph's `main_message` references the role family or opening angle from the plan's `role_positioning` on a fixture state where `role_positioning.role_family` is infrastructure-flavoured.
- **FR-026**: The system MUST include an automated test asserting that a paragraph plan with `max_tools=4` validates cleanly AND that the writer's constructed prompt explicitly surfaces the per-paragraph cap to the LLM.
- **FR-027**: The system MUST include an automated test asserting `len(evidence_refs) <= max_claims` validation raises clearly when violated.
- **FR-028**: The system MUST include an automated test asserting that a legacy `ContentPlan` JSON (no `letter_thesis`, no `paragraphs`) loads cleanly with documented defaults.
- **FR-029**: The system MUST include an automated test asserting that `ContentPlan.extra="forbid"` still rejects unknown top-level keys (parallel to feature 010's `RequirementExtraction` and `RolePositioning` coverage).
- **FR-030**: The system MUST include an automated test asserting that a paragraph's `requirement_ids` referencing an unknown `RequirementItem.id` raises a clear validation error.

### Key Entities

- **Hiring Story (Letter Thesis)**: a single-sentence statement at the top of the content plan capturing what the candidate is being pitched as — the story the letter tells. Optional for backward compatibility; populated by the planner going forward.
- **ParagraphPlan**: a new typed record on the content plan representing one paragraph of the cover letter. Carries `purpose`, `main_message`, `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise`, `max_claims`, `max_tools`. Read by the writer to produce the paragraph's prose under the documented constraints.
- **Per-Paragraph Density Limits**: `max_claims` (1..8) and `max_tools` (0..12) bound how many distinct claims and tool/technology names the writer may use in one paragraph. Default for the opening paragraph: `max_claims=1` or `2`. Default for other paragraphs: set by the planner based on the paragraph's purpose.
- **Opening Paragraph**: index 0 of `paragraphs`. Specifically planned around the plan's `role_positioning.role_family` and `role_positioning.opening_angle`. Its `main_message` references those values in substance.
- **Requirement Reference**: a `RequirementItem.id` string (e.g., `R1`, `R2`) appearing in a paragraph's `requirement_ids` list. Validated against the run's `requirement_items` at parse time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of planner runs producing the new structure, `letter_thesis` is a non-empty string of ≤ 300 characters.
- **SC-002**: For 100% of planner runs producing the new structure, every paragraph carries a non-empty `main_message` of ≤ 300 characters AND `purpose`, `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise` fields populated (lists may be empty for some paragraphs).
- **SC-003**: For 100% of planner runs on the AI/ML infrastructure fixture, the opening paragraph's `main_message` contains a substring drawn from `role_positioning.role_family` or `role_positioning.opening_angle` (e.g., "infrastructure", "platform", "AI/ML", or the configured opening-angle terms).
- **SC-004**: For 100% of paragraph plans, `len(evidence_refs) <= max_claims` AND `max_tools` is in [0, 12] AND `max_claims` is in [1, 8]. Plans that violate these bounds raise at parse time.
- **SC-005**: For 100% of legacy `ContentPlan` JSON payloads (pre-feature shapes), the new model loads without raising, with documented defaults applied to absent fields. Existing 254 tests continue to pass without modification.
- **SC-006**: For 100% of writer-prompt invocations on a state whose plan has populated `paragraphs`, the constructed writer prompt surfaces the per-paragraph `max_claims` and `max_tools` limits in a clearly-labelled section so the LLM can respect them.
- **SC-007**: Evidence retrieval (CV variant selection, profile loading, evidence-map population), hiring-review behaviour (same dimensions, same routing), MLflow tag/metric names, Langfuse trace shape, and CLI contract are unchanged — verified by the existing test suite continuing to pass and by the only allowed per-prompt content-hash flips being on the prompts this feature actually edits.

## Assumptions

- The existing `ContentPlan` carries `sections: list[SectionPlan]` (introduced by features 001/005). Feature 011 adds `paragraphs: list[ParagraphPlan]` ALONGSIDE that field; `sections` stays untouched for backward compatibility. The planner produces `paragraphs` going forward; legacy artifacts continue to load with `paragraphs=[]`.
- The `ParagraphPlan` model is new in this feature (no overlap with `SectionPlan`). The two coexist; downstream consumers prefer `paragraphs` when present and fall back to `sections` when only the legacy field is populated.
- `letter_thesis` is bounded to ≤ 300 characters by Pydantic field constraint to keep it a single sentence rather than a paragraph-length intro.
- `main_message` is bounded to ≤ 300 characters for the same reason.
- `max_claims` default is 3 when not specified; the opening paragraph default is 1 or 2 (enforced by FR-012 at parse time). `max_tools` default is the global `writer_rules.tool_density_max` (4) when not specified.
- `purpose` is a free-form short string (no closed enum) so operators can adopt any naming convention without a code change. The test for "opening paragraph" looks at index 0 of the list, not at the `purpose` label.
- The planner's tool schema is auto-generated from `ContentPlan.model_json_schema()`. Adding fields to `ContentPlan` and the new nested `ParagraphPlan` propagates automatically into the LLM's required-output schema — no manual schema editing.
- The writer's tool schema (`_WRITE_SCHEMA = {text, mode}`) is unchanged. The new fields are surfaced to the writer via the prompt-content path (existing `_format_positioning_block` style), NOT via the writer's output schema.
- Per-paragraph `max_tools` OVERRIDES the global `writer_rules.tool_density_max` for that paragraph specifically. When `max_tools` is absent (legacy paragraph plan), the global cap applies.
- The hiring-review prompt is NOT edited by this feature. The content-plan summary block from feature 009 surfaces the new `letter_thesis` and per-paragraph `main_message` automatically because it serialises the `ContentPlan` typed object — no code change needed.
- The fixture AI/ML infrastructure SWE job + the biomedical-ML profile project added in feature 008 are reused as the deterministic regression guard; no new fixture files are required.
- This feature does NOT introduce a new pipeline stage, a new artefact file, a new CLI command, or a new MLflow/Langfuse metric. All changes land inside the `ContentPlan` / `ParagraphPlan` Pydantic models, the planner prompt, the planner `build_prompt`, and the writer prompt + `build_prompt`.
- This feature does NOT change evidence retrieval, evidence mapping, requirement extraction (feature 010 owns that), or hiring-review behaviour. The hiring review automatically benefits from the richer plan via its existing content-plan summary block — no review-code change.
