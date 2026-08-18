# Feature Specification: Weighted Requirements + Refined Role Positioning

**Feature Branch**: `010-weighted-requirements-positioning`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "Add explicit role positioning and weighted requirement extraction. Extend the requirement extraction output with stable requirement IDs, priority levels, requirement categories, and evidence need. Add a new RolePositioning model that captures role_family, primary_selling_point, secondary_selling_points, opening_angle, emphasise, deemphasise, and risky_or_gap_areas. The planner and hiring_review stages must receive this role_positioning object. The feature must help distinguish the primary hiring story from secondary domain fit. For example, an AI/ML infrastructure software engineering role with biomedical data context should be positioned primarily as infrastructure/software engineering and only secondarily as biomedical data science. Do not change retrieval behavior or final writing behavior except for passing the new structured context forward. Add tests for schema validation, backwards compatibility, prompt assembly, and a fixture where a software infrastructure role is not misclassified as a biomedical data science role."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Weighted Requirement Extraction (Priority: P1) 🎯 MVP

When the agent reads a job description today, the requirement extractor produces a structured list of requirements but each requirement is a thin record (free-form text + a category label + a coarse priority integer). Downstream stages (planner, hiring_review, validators) cannot reliably refer to a specific requirement by a stable identifier; they cannot easily distinguish a "nice-to-have" from a "must-have"; they cannot tell whether the candidate needs strong evidence for the requirement or whether a brief mention suffices. This story enriches every extracted requirement with four explicit attributes: a stable identifier, a priority level on a small ordinal scale, a category, and an evidence-need rating. Once each requirement is individually addressable and weighted, every downstream stage that reasons about the job description can use that structure instead of re-parsing free text.

**Why this priority**: This is the foundation. Without stable IDs the hiring review cannot say "requirement R3 (a top-priority responsibility) is barely covered in paragraph 2"; without priority levels the planner cannot decide which requirements deserve their own section vs. a passing mention; without evidence-need the planner cannot decide which sections need anchor passages vs. one-line acknowledgements. Every downstream improvement depends on this structure.

**Independent Test**: Run the requirement extractor against a fixture job description. Assert that every record in the returned list has a non-empty stable ID, a priority level from the allowed enum, a category from the allowed enum, and an evidence-need value from the allowed enum. Re-run on the same input; assert the IDs are stable across runs (deterministic from requirement content) — or, if generation is random, assert each ID occurs exactly once in the response.

**Acceptance Scenarios**:

1. **Given** a job description fixture, **When** the extractor runs, **Then** every requirement carries a non-empty `id`, a `priority` from the allowed levels, a `category` from the allowed enum, and an `evidence_need` from the allowed enum.
2. **Given** the same fixture run twice, **When** the extractor runs both times, **Then** within each run every requirement ID is unique and IDs are stable enough that downstream stages can reference them throughout the run.
3. **Given** a job description that emphasises one responsibility above all others, **When** the extractor runs, **Then** at least one requirement has the highest priority level and that requirement's `category` matches the primary responsibility's nature (e.g., `core` or `technical` for "design and operate scalable cloud infrastructure", not `optional`).
4. **Given** a job description that includes a "nice to have" sub-section, **When** the extractor runs, **Then** items from that sub-section receive a priority strictly lower than the top responsibilities AND an `evidence_need` value that reflects their optional nature.

---

### User Story 2 — Refined RolePositioning Carried Into Planner and Hiring Review (Priority: P1)

A `RolePositioning` structured object captures, with seven explicit fields, the agent's framing decision for the role: which family the role belongs to, the candidate's primary and secondary selling points, the intended opening angle, the topics to emphasise, the topics to de-emphasise, and the risky-or-gap areas (subjects the letter should avoid or treat carefully because the candidate has no strong evidence). The planner emits this object as part of its content plan; the hiring-review stage receives it as read-only context so it can judge whether the letter actually executes the planned positioning. Both stages reason from the same structured contract.

The seven fields:
- `role_family`
- `primary_selling_point`
- `secondary_selling_points`
- `opening_angle`
- `emphasise`
- `deemphasise`
- `risky_or_gap_areas`

**Why this priority**: Equal to US1 because they ship together as the MVP pair. US1 weights individual requirements; US2 binds them into one cohesive framing decision that downstream stages can act on. Without US2 the weighted requirements would land back as a flat list with no cross-cutting story.

**Independent Test**: Run the planner against a fixture state whose requirements (from US1) emphasise infrastructure responsibilities. Assert the resulting `RolePositioning` records `role_family` matching the infrastructure family, lists biomedical-ML in `secondary_selling_points` (not `primary_selling_point`), names at least one entry in `risky_or_gap_areas` if the candidate has visible gaps, and provides a non-empty `opening_angle`. Separately, build a hiring-review prompt from a state whose plan carries that positioning; assert the prompt contains the positioning fields verbatim.

**Acceptance Scenarios**:

1. **Given** a populated `RolePositioning` object on the content plan, **When** the planner stage runs, **Then** every required field is populated and the structure validates without error.
2. **Given** a workflow state where `RolePositioning` has been recorded by the planner, **When** the hiring-review stage builds its prompt, **Then** the prompt contains a clearly-labelled block exposing all seven fields' values to the reviewer.
3. **Given** a job description primarily about AI/ML infrastructure software engineering AND a profile with strong infrastructure evidence plus a notable biomedical-ML project, **When** the planner produces positioning, **Then** `role_family` reflects the infrastructure family (e.g., "AI/ML platform engineering", "ML infrastructure SWE") — NOT a biomedical-ML or biomedical-data-science family. The biomedical-ML angle, if mentioned at all, appears in `secondary_selling_points` and/or `deemphasise`.
4. **Given** a positioning with at least one entry in `risky_or_gap_areas`, **When** the downstream writer prepares the letter (existing behaviour, unchanged), **Then** the writer's prompt continues to receive the same positioning input shape — risky-or-gap areas inform the writer's caution without changing its generation behaviour beyond what feature 008 already established.

---

### User Story 3 — Backward Compatibility for Legacy Artifacts (Priority: P3)

The agent ships with artifacts (`artifacts/requirements.json`, `artifacts/content_plan.json`) saved by earlier runs that pre-date this feature. Engineers occasionally re-load these artifacts during debugging or replay scenarios. The new schema must continue to load every legacy artifact without raising — missing new fields default sensibly (None, empty list, or a defined default) — and old field names (where this feature renames or restructures any) continue to be accepted alongside the new field names.

**Why this priority**: P3 because the MVP value lands with US1+US2; backward compatibility is a quality-of-life invariant for debugging older runs, not a feature enabling new capability.

**Independent Test**: Construct a JSON document matching the pre-feature `RequirementExtraction` shape (no per-requirement ID, no evidence-need); load it via the new model; assert the load succeeds and new fields take their documented defaults. Construct a JSON document matching the feature 008 `RolePositioning` shape (with field names `primary_role_family`, `topics_to_emphasise`, `topics_to_deemphasise`); load it via the new model; assert the load succeeds and the new `risky_or_gap_areas` field defaults to an empty list.

**Acceptance Scenarios**:

1. **Given** a `RequirementExtraction` JSON written by a pre-feature run (no per-requirement ID or evidence_need), **When** the new model loads it, **Then** the load succeeds and each requirement's new fields are populated with safe defaults.
2. **Given** a `RolePositioning` JSON written by the previous feature (008) using the older field names, **When** the new model loads it, **Then** the load succeeds, the older field names are accepted via aliases (or normalised on load), and the new `risky_or_gap_areas` field defaults to an empty list.
3. **Given** a JSON document with unknown keys mixed in (e.g., a hand-edited artifact), **When** the new model loads it, **Then** the load surfaces a clear validation error rather than silently dropping the unknown keys — preserving the existing `extra="forbid"` discipline of the project.

---

### Edge Cases

- **Two requirements with identical text**: each must still get a unique ID. The extractor disambiguates (e.g., by appending a sequence suffix) so downstream references stay distinct.
- **A job description with only one paragraph and no clear sub-sections**: the extractor produces at minimum a single highest-priority requirement; categories/evidence-need fall back to sensible defaults rather than refusing to extract.
- **A candidate profile with no evidence for any of the top-priority requirements**: positioning still names the correct `role_family`; the gaps are recorded explicitly in `risky_or_gap_areas` rather than swept into `secondary_selling_points`.
- **A candidate's strongest evidence is in `deemphasise` territory**: positioning still treats the job's primary need as primary; the strong-evidence-but-off-domain story moves to `secondary_selling_points` AND is referenced in `deemphasise` so the writer knows to keep it brief.
- **`risky_or_gap_areas` overlaps with `deemphasise`**: both lists may share entries (a topic can be both "we should de-emphasise this because the role doesn't need it" and "we'd be exposed if we leaned in on it"). Downstream stages are expected to dedupe or treat the lists as additive.
- **An evidence-need of "required" on a requirement with zero matching evidence**: this surfaces a gap that downstream validators may flag; the requirement extractor does NOT itself refuse to extract — it reports the structure faithfully and lets validators decide consequences.
- **Older artifact has only a subset of the new RolePositioning fields**: backward compatibility loads the available fields; missing fields default; alias-renamed fields are accepted.
- **An empty job description**: the extractor returns an empty-but-valid `RequirementExtraction`; the planner produces a minimal positioning rather than raising.

## Requirements *(mandatory)*

### Functional Requirements

#### Weighted requirement structure

- **FR-001**: The system MUST record, for every extracted requirement, a stable identifier (`id`) that is unique within the run and usable by downstream stages to reference the requirement by name (e.g., "R3", "req_3", or any short stable token).
- **FR-002**: The system MUST record, for every extracted requirement, a `priority` value drawn from a small ordinal enum (recommended: `high` / `medium` / `low`, or numeric 1..3). The chosen scale MUST be documented and used consistently across all extracted requirements.
- **FR-003**: The system MUST record, for every extracted requirement, a `category` value drawn from a small enum representing the requirement's nature (recommended set: `core`, `technical`, `collaboration`, `domain`, `optional`). The scale matches the existing categorical fields in the requirement-extraction schema so existing consumers keep working.
- **FR-004**: The system MUST record, for every extracted requirement, an `evidence_need` value drawn from a small enum signalling how strongly evidence is needed for that requirement (recommended: `required` / `preferred` / `optional`).
- **FR-005**: Within a single run, requirement IDs MUST be unique (no two requirements share an ID) so downstream stages can reference any requirement unambiguously.
- **FR-006**: The system MUST set the highest available priority level on at least one requirement whenever the job description clearly emphasises a primary responsibility; the extractor MUST NOT down-weight every requirement to the same level.

#### Refined RolePositioning structure

- **FR-007**: The system MUST provide a structured `RolePositioning` object with exactly these seven fields:
  - `role_family` — a short human-readable string naming the role family the job is hiring for.
  - `primary_selling_point` — one-sentence framing of the candidate's main match for the primary role.
  - `secondary_selling_points` — list of additional matches worth mentioning briefly.
  - `opening_angle` — short instruction shaping the letter's opening paragraph.
  - `emphasise` — list of topic names the letter should develop in its main paragraphs.
  - `deemphasise` — list of topic names the letter should mention only briefly.
  - `risky_or_gap_areas` — list of topic names the letter should avoid or treat carefully because the candidate has no strong evidence (or the alignment is weak in a way that could backfire if leaned on).
- **FR-008**: `role_family`, `primary_selling_point`, and `opening_angle` MUST be required non-empty strings. The four list fields MAY be empty.
- **FR-009**: The planner stage MUST emit a `RolePositioning` object as part of its structured content plan; the planner's output schema MUST require the object's required fields and validate them at parse time.
- **FR-010**: The hiring-review stage MUST receive the `RolePositioning` object via the existing state-passing channel (i.e., as part of the content plan it already reads). The review prompt MUST contain a clearly-labelled section presenting the positioning fields verbatim so the reviewer can judge whether the letter executes the planned positioning.
- **FR-011**: When the job description is primarily about one role family (e.g., AI/ML infrastructure software engineering) and the candidate's profile contains evidence in a different domain (e.g., biomedical-ML), the planner's `RolePositioning.role_family` MUST reflect the job's primary family — not the candidate's strongest-evidence family. The strong-but-off-domain evidence belongs in `secondary_selling_points` and/or `deemphasise`, never in `role_family`.

#### Non-interference with existing stages

- **FR-012**: Retrieval behaviour (CV variant selection, profile loading, evidence mapping) MUST be unchanged. This feature only enriches the requirement structure and the positioning structure passed downstream; it does not change which sources are loaded or how evidence is matched.
- **FR-013**: Final writing behaviour MUST be unchanged except for the addition of the new structured context. The writer prompt continues to consume positioning as established by feature 008; if the writer needs to know about the new field (`risky_or_gap_areas`), this is included additively without altering the writer's existing rules (role-first opening, tool-density cap, banned phrases, no-claim-outside-plan).
- **FR-014**: The existing pipeline graph (load_job → extract_requirements → load_profile → … → validate_outputs) MUST remain unchanged in order and stage composition.
- **FR-015**: MLflow logging behaviour MUST be unchanged: no new tag or metric names; the per-stage prompt hashes for `requirements`, `planner`, and `hiring_reviewer` MAY flip naturally because those prompts change to surface the new structure — that is the correct intended signal.
- **FR-016**: Langfuse trace structure MUST be unchanged: no new spans, no new metadata field names.
- **FR-017**: CLI contract MUST be unchanged: same commands, same flags, same exit codes, same output files.

#### Backward compatibility

- **FR-018**: The new `RequirementExtraction` model MUST accept legacy JSON documents written by pre-feature runs (no per-requirement `id`, `evidence_need`, or refined `category`). Missing new fields MUST default to documented safe values (e.g., a deterministic placeholder ID; `priority="medium"`; `category="optional"`; `evidence_need="optional"`).
- **FR-019**: The new `RolePositioning` model MUST accept legacy JSON documents written by the previous feature (feature 008) under the older field names (`primary_role_family`, `topics_to_emphasise`, `topics_to_deemphasise`). The previous field names MUST continue to load via Pydantic field aliases or an equivalent normalisation step; the new `risky_or_gap_areas` field MUST default to an empty list when absent.
- **FR-020**: Both models MUST continue to forbid unknown keys (preserving the existing `extra="forbid"` discipline of the project), surfacing typos in operator-edited artifacts rather than silently dropping them.

#### Tests

- **FR-021**: The system MUST include an automated test that loads a fixture `RequirementExtraction` payload, asserts every requirement carries the four new fields with valid enum values, and asserts IDs are unique within the response.
- **FR-022**: The system MUST include an automated test that loads a fixture `RolePositioning` payload with all seven fields, asserts the load succeeds, and asserts each field's value matches the input.
- **FR-023**: The system MUST include an automated test that loads a legacy `RequirementExtraction` JSON (no IDs, no evidence_need) and asserts the load succeeds with documented defaults applied.
- **FR-024**: The system MUST include an automated test that loads a legacy `RolePositioning` JSON using the previous (feature 008) field names and asserts the load succeeds with the new field names accessible.
- **FR-025**: The system MUST include an automated test that asserts the hiring-review prompt assembly contains every populated `RolePositioning` field verbatim under a clearly-labelled heading when the content plan carries a populated positioning.
- **FR-026**: The system MUST include an automated test using a fixture AI/ML infrastructure SWE job description (with biomedical data as a secondary domain context) plus a candidate profile that has both infrastructure and biomedical-ML evidence; the test asserts the planner-produced `RolePositioning.role_family` reflects the infrastructure family (NOT a biomedical-ML or biomedical-data-science family) and that biomedical-ML appears only in `secondary_selling_points` and/or `deemphasise`.
- **FR-027**: The system MUST include an automated test that asserts both `RequirementExtraction` and `RolePositioning` reject a JSON document containing an unknown top-level key, surfacing the typo via a validation error.

### Key Entities

- **Weighted Requirement**: a single extracted requirement carrying `id`, `text`, `category`, `priority`, and `evidence_need`. Identified by `id` throughout the run; categorised by `category`; weighted by `priority`; tagged by `evidence_need` to signal how strongly evidence is needed.
- **Refined RolePositioning**: a structured framing decision attached to the content plan, recording how the cover letter should be positioned for THIS specific job. Seven fields total (FR-007). Distinguishes the primary hiring story (`role_family`, `primary_selling_point`, `emphasise`) from the secondary domain fit (`secondary_selling_points`, `deemphasise`) and from known risk areas (`risky_or_gap_areas`).
- **Stable Requirement ID**: a short, unique-within-the-run identifier for each requirement. Used by the planner (e.g., to associate sections with the requirements they address) and by the hiring-review weaknesses (e.g., to name which requirement is underweighted).
- **Evidence Need**: an enum value per requirement signalling how strongly the writer should anchor evidence to that requirement. Drives downstream prompts to insist on strong anchors for `required` items vs. allowing one-liner acknowledgements for `optional` items.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of requirement extractions, every requirement carries the four new fields (`id`, `priority`, `category`, `evidence_need`) populated from the allowed enums.
- **SC-002**: For 100% of requirement extractions, all requirement IDs within the response are unique.
- **SC-003**: For 100% of planner runs, the produced content plan carries a `RolePositioning` object whose three required fields (`role_family`, `primary_selling_point`, `opening_angle`) are non-empty strings.
- **SC-004**: For 100% of hiring-review prompt invocations on a state whose content plan carries a populated `RolePositioning`, the constructed prompt contains every populated positioning field verbatim under a clearly-labelled heading.
- **SC-005**: For the AI/ML infrastructure SWE fixture (with biomedical-ML profile evidence), the planner produces `RolePositioning.role_family` that contains an infrastructure-flavoured term (e.g., "platform", "infrastructure", "ML platform", "SWE", "software engineering") and does NOT contain "biomedical" or "data science" in 100% of test executions.
- **SC-006**: For 100% of legacy `RequirementExtraction` and `RolePositioning` JSON payloads (pre-feature shapes), the new models load without raising, with documented defaults applied to absent fields.
- **SC-007**: For 100% of new payloads containing an unknown top-level key, the models surface a clear validation error rather than silently dropping the key.
- **SC-008**: Retrieval, evidence mapping, final writing behaviour, MLflow tag/metric names, Langfuse trace shape, and the CLI contract are unchanged — verified by comparing pre-feature and post-feature outputs on the same fixture inputs (the only allowed differences are the new structured fields on the requirement and positioning artefacts, and the natural per-prompt content-hash flips on `requirements`, `planner`, and `hiring_reviewer`).

## Assumptions

- The existing `RolePositioning` model already shipped in feature 008 with six fields under slightly different names (`primary_role_family`, `topics_to_emphasise`, `topics_to_deemphasise`). This feature EVOLVES the model: the names are normalised to those listed in FR-007, a new `risky_or_gap_areas` field is added, and a backward-compat alias path keeps legacy artifacts loading (FR-019). Engineers reading either name will find one canonical structure.
- The existing `Requirement` model already carries `label`, `text`, and `priority` fields. This feature extends it with `id` and `evidence_need` and adopts the recommended enums for `priority`/`category`/`evidence_need`. The existing `label` field becomes the `category` field (or stays as `label` with the enum tightened — implementation detail for the plan phase).
- Requirement IDs are short tokens chosen by the extractor (e.g., `R1`, `R2`, …) for human readability in the constructed prompts; uniqueness is per-run, not global across runs. Stability across runs (deterministic from content) is desirable but not required.
- The `evidence_need` enum's three values map intuitively: `required` for top responsibilities that a hiring manager would want to see explicit evidence for; `preferred` for important but not absolute needs; `optional` for nice-to-haves the letter can mention briefly or skip.
- The writer prompt continues to receive positioning by reading the content plan (existing behaviour from feature 008). The new `risky_or_gap_areas` field flows to the writer additively. The writer's rules (role-first opening, tool-density cap, banned phrases, no-claim-outside-plan) are unchanged.
- The hiring-review prompt's existing content-plan summary block (added by feature 009) is the natural carrier for the refined positioning. The block is extended to surface the new `risky_or_gap_areas` field alongside the others.
- "Misclassification" in the AI/ML infrastructure example is judged by the `role_family` field's content: it MUST NOT contain "biomedical" or "data science" terms when the job is primarily about software / infrastructure engineering. The deterministic test asserts on substring presence/absence, not on the LLM's reasoning quality.
- This feature does NOT introduce a new pipeline stage, a new artefact file, a new CLI command, or a new MLflow/Langfuse metric. All changes land inside the `requirements`/`planner`/`hiring_reviewer` prompts (so their content-hashes flip and feature 007's prompt registry records new versions on the next `jobagent prompts sync`), inside the relevant Pydantic models (`Requirement`, `RequirementExtraction`, `RolePositioning`), and inside the build_prompt formatters that surface the new fields to the LLMs.
- This feature does NOT introduce new always-on review dimensions beyond what features 008 and 009 already established (`role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`, `critical_requirements_underweighted`). The refined positioning gives the reviewer more grounded context for the existing dimensions, not new dimensions to evaluate.
- The fixture AI/ML infrastructure SWE job + the biomedical-ML profile project added in feature 008 (`data/examples/jobs/sample_ml_infrastructure.md` + `data/examples/profile/projects/biomedical_ml_project.md`) are reused as the deterministic regression guard; no new fixture files are required.
