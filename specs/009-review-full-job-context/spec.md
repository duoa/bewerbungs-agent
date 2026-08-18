# Feature Specification: Hiring Review with Full Job Context

**Feature Branch**: `009-review-full-job-context`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "Add full job context to the hiring review stage. The hiring_review stage must evaluate the generated cover letter against the complete job description, not only against extracted requirements. Extend the stage input so the review prompt receives the full raw job description, parsed job context if available, extracted requirements, content plan, and letter draft. The review must assess whether the letter reflects the primary role described in the full job description, whether the opening paragraph matches the role's main emphasis, whether secondary domain experience is overemphasized, and whether critical requirements are underweighted. Do not change letter generation, evidence mapping, retrieval, targeted rewriting, or prompt content outside the hiring review feature. Preserve existing non-blocking review behavior. Add tests proving that the hiring_review prompt includes the full job description, that legacy runs without optional job context still work, and that the review can flag a letter whose opening emphasizes a secondary domain instead of the primary role."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Reviewer Sees the Complete Job Context (Priority: P1) 🎯 MVP

When the hiring-review stage runs today (post-feature-008), it sees the draft letter, the extracted requirement list, and the verbatim job description text. What it does NOT see are the smaller parsed-but-structured fields associated with the job (the job title the loader pulled out, the company name, any optional company-info or storyboard text the operator supplied). These structured fields are sitting on `WorkflowState.job_context` waiting to be useful. This story finishes the job: the review prompt is extended so the reviewer sees the full job context — the raw description PLUS the parsed structured fields PLUS the extracted requirements — and can therefore judge role match against the strongest possible source of truth. Legacy runs (where some of these fields are absent) continue to work.

**Why this priority**: This is the load-bearing improvement. Adding content-plan visibility (US2) and the new underweighting dimension (US3) only pay off when the reviewer already has the most complete view of the role it's evaluating against. The MVP delivers value on its own: even without US2/US3, a review run against the fuller context produces more grounded role-match and opening-alignment judgements.

**Independent Test**: Build a `WorkflowState` whose `job_context` carries `raw_job_text` plus a recognisable `job_title`, `company_name`, optional `raw_company_text`, and optional `raw_storyboard_text`. Call `hiring_review.build_prompt(state)`. Assert the constructed prompt contains every populated field verbatim, labelled in a way a hiring manager would parse. Then call `build_prompt` on a state where `job_context` is None entirely and assert the prompt still builds (no exception) with an explicit "(job description unavailable …)" placeholder so the LLM can fall back to evaluating against the requirement list only.

**Acceptance Scenarios**:

1. **Given** a workflow state whose `job_context` is fully populated (raw text + job title + company name + optional company info + optional storyboard), **When** the hiring-review stage builds its prompt, **Then** the constructed user message contains all populated structured fields verbatim, each under a clear heading, in addition to the raw job description.
2. **Given** a workflow state whose `job_context` is fully populated, **When** the review runs, **Then** the review's prompt makes clear which input is the original job ad and which is the agent-extracted requirement summary, so the reviewer can spot any difference between the two and prefer the source.
3. **Given** a workflow state where `job_context` is None entirely (a legacy run, a `validate`-only invocation, or a test path that does not exercise `load_job`), **When** the review stage runs, **Then** the prompt builds cleanly with an explicit placeholder, no exception is raised, and the review can still operate against the extracted requirements alone.
4. **Given** a workflow state where `job_context` exists but optional fields (company info, storyboard) are absent, **When** the review stage runs, **Then** the prompt builds cleanly with only the populated fields present (no empty "(none)" sections for fields the operator chose not to provide).

---

### User Story 2 — Reviewer Sees the Content Plan, Spots Plan-vs-Letter Drift (Priority: P2)

Today the hiring reviewer sees the FINAL letter but not the PLAN that produced it. That means the reviewer cannot distinguish "the plan was misaligned" from "the plan was fine but the writer drifted". This story extends the review prompt to additionally include the structured content plan as read-only context. The reviewer judges only the letter (the existing constraint is preserved); the content plan is exposed as a reference so the reviewer can produce more specific `priority_fix` text when it sees drift (e.g., "the plan called for an infrastructure-led opening but the letter opens with biomedical-ML; align opening with plan.role_positioning.opening_angle").

**Why this priority**: P2 because US1 already raises the floor of review quality. US2 adds precision: when a weakness exists, the reviewer can name the divergence ("plan said X, letter does Y") instead of just naming the symptom. This is most valuable for routing the existing targeted-rewrite stage (feature 005) to the exact wording change needed.

**Independent Test**: Build a state whose content plan declares an infrastructure-first `role_positioning` and whose letter opens with a biomedical-ML hook. Call `hiring_review.build_prompt(state)`. Assert the prompt contains a clearly-labelled `## Content Plan` block showing the positioning's `primary_role_family` and `opening_angle` values. Separately verify the prompt still works (and the block is omitted or marked "(none)") when `state.content_plan` is None.

**Acceptance Scenarios**:

1. **Given** a workflow state whose `content_plan` is populated (post-planner-stage), **When** the review builds its prompt, **Then** the prompt contains a clearly-labelled section presenting the content plan as read-only context (at minimum: the sections list with titles and key_claims, and — when present — the `role_positioning` summary).
2. **Given** a workflow state whose `content_plan` is None (early stages, validate-only path), **When** the review builds its prompt, **Then** no exception is raised and the content-plan block is either omitted or explicitly marked unavailable.
3. **Given** a letter whose opening drifts from the plan's `opening_angle`, **When** the reviewer evaluates the opening section, **Then** the recorded weakness on that section explicitly references the plan-vs-letter divergence (e.g., "plan called for X-led opening; letter opens with Y") in either the weakness `text` or the `priority_fix`.

---

### User Story 3 — Reviewer Flags Underweighted Critical Requirements (Priority: P3)

A new evaluation dimension — `critical_requirements_underweighted` — joins the existing always-on positioning dimensions established by feature 008. When the letter covers most requirements adequately but leaves a critical one with thin or absent treatment (e.g., one passing mention buried in a single subclause when the job emphasises it as a primary responsibility), the review flags that gap as a section-level weakness with `severity ≥ medium`, attached to the section closest to where the requirement SHOULD have been treated.

**Why this priority**: P3 because US1 + US2 already expand the input set; this story adds one new output dimension. It is the smallest of the three changes and is independently shippable once US1's full context is in the prompt.

**Independent Test**: Construct a canned LLM review response that includes a weakness tagged `"critical_requirements_underweighted: scalable cloud infrastructure barely mentioned, only in a subclause"` on the "experience" section with `severity=medium` and `priority_fix="add a paragraph on scalable infrastructure responsibilities"`. Run `parse_response(data, threshold=medium)`. Assert "experience" is in `sections_to_rewrite`. Separately verify the new dimension name appears in the active-dimensions list inside `hiring_review.build_prompt(state)`.

**Acceptance Scenarios**:

1. **Given** the hiring review runs in any configuration, **When** the prompt is constructed, **Then** the evaluation-dimensions list includes `critical_requirements_underweighted` alongside the existing dimensions from feature 008 (`role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`).
2. **Given** the reviewer identifies a critical job requirement that the letter underweights, **When** it records the weakness, **Then** the weakness text is tagged with the dimension name (`"critical_requirements_underweighted: ..."`) so downstream targeted-rewrite can route the fix correctly.
3. **Given** a critical-requirement-underweighted weakness at severity ≥ the configured `rewrite_threshold`, **When** the review produces the report, **Then** the affected section appears in `sections_to_rewrite`, triggering the existing rewrite path (no new pipeline stage introduced).

---

### Edge Cases

- **`job_context` is partially populated** (e.g., `raw_job_text` present but `job_title` is None): build_prompt emits only the populated fields, each clearly labelled; absent optional fields are silently omitted rather than rendered as "(none)" empty placeholders.
- **`content_plan.role_positioning` is None** (a plan produced by a pre-feature-008 run, loaded from artefact for a re-review): the content-plan block in the prompt omits the positioning summary or marks it `(not recorded)`; the reviewer continues to evaluate against the letter and requirements.
- **`content_plan` itself is None** (validate-only CLI invocation that skips the planner): the content-plan block is omitted entirely; the prompt is shorter but otherwise identical in shape.
- **`raw_company_text` or `raw_storyboard_text` is very long** (multi-page company info): no special truncation is applied here — this stage trusts the upstream loaders' decisions. If LLM token budget becomes a concern, the operator can omit the optional file from the run.
- **A letter has no clear sections**: the existing fallback (treat the whole letter as one section named "letter") is preserved; the new dimensions still fire against that single section.
- **The reviewer is asked to evaluate a letter that does not match the plan at all** (writer regressed or was replaced): the content-plan visibility makes this scenario produce a sharper, more specific weakness — the reviewer can quote both sides of the divergence.
- **A critical requirement is not coverable from the candidate's evidence** (legitimate gap recorded in `evidence_map.known_gaps`): the reviewer should NOT flag this as `critical_requirements_underweighted` — gaps acknowledged in the plan are not letter regressions. The prompt instructs the reviewer accordingly.
- **The hiring-review LLM call fails entirely** (network error, schema validation failure): the existing non-blocking behaviour from feature 005 is preserved — one warning, no `letter_review` produced, pipeline continues to `validate_outputs` and then to artefacts.

## Requirements *(mandatory)*

### Functional Requirements

#### Inputs to the review prompt

- **FR-001**: The hiring-review stage MUST construct its user message from these inputs, in this fixed order:
  1. Original job description (verbatim raw text — preserves feature 008's behaviour)
  2. Parsed job-context structured fields when present (job title, company name, optional company info text, optional storyboard text)
  3. Extracted requirements (the existing structured summary)
  4. Content plan (typed structured object; preferred fields below)
  5. Cover letter draft (the existing letter text)
  6. Active evaluation dimensions list (existing standard dimensions + the always-on positioning dimensions from feature 008 + the new `critical_requirements_underweighted` dimension introduced here)
- **FR-002**: The review prompt MUST clearly label each input block with a heading the LLM can use to distinguish the source job ad from the extracted-requirement summary, the structured content plan from the rendered letter, and so on.
- **FR-003**: When `state.job_context` is None, the prompt MUST still build cleanly with an explicit placeholder `(job description unavailable — base evaluation on requirements only)` so legacy or partial-state runs do not crash.
- **FR-004**: When `state.job_context` is populated but optional structured fields (company info, storyboard) are absent, the prompt MUST omit those fields entirely rather than emit empty placeholder sections.
- **FR-005**: When `state.content_plan` is None, the content-plan block MUST be omitted or explicitly marked unavailable; no exception is raised; the rest of the prompt is unaffected.
- **FR-006**: The content-plan block in the prompt MUST present at minimum: the plan's section titles + key claims, and (when present) the `role_positioning` summary (primary role family, primary selling point, opening angle, topics to emphasise / de-emphasise). Verbatim claim wording from `evidence_refs` MAY appear; raw evidence passages are NOT required and may be omitted to keep the prompt focused.

#### Evaluation semantics

- **FR-007**: The review MUST continue to evaluate the LETTER, not the plan. The content plan is read-only reference context; weaknesses are recorded on letter sections, not on plan fields.
- **FR-008**: The review MUST add `critical_requirements_underweighted` as an always-on evaluation dimension, alongside feature 008's `role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`.
- **FR-009**: Weaknesses arising from `critical_requirements_underweighted` MUST be tagged with the dimension name in their `text` field (e.g., `"critical_requirements_underweighted: ..."`) so downstream targeted-rewrite can identify the dimension via text scanning, consistent with feature 008's tagging convention.
- **FR-010**: A `critical_requirements_underweighted` weakness at severity ≥ the configured `rewrite_threshold` MUST cause the affected section to appear in `sections_to_rewrite`. No new pipeline stage is introduced — the existing targeted-rewrite path handles the corrective action.
- **FR-011**: A critical requirement that is openly acknowledged as a gap in `evidence_map.known_gaps` MUST NOT trigger a `critical_requirements_underweighted` weakness; the reviewer is instructed to recognise honest gaps as such, not as letter regressions.

#### Scope discipline

- **FR-012**: This feature MUST NOT change letter generation behaviour, evidence-mapping behaviour, retrieval (CV variant selection, profile loading), targeted-rewriting behaviour, or any prompt files outside `prompts/hiring_reviewer.md`. All changes are confined to the hiring-review stage's prompt content and its `build_prompt` formatter.
- **FR-013**: The existing non-blocking review behaviour MUST be preserved: any LLM-call failure inside `hiring_review` continues to emit a single warning, return an empty result, and let the pipeline proceed to validation and artefact writing (the feature 005 behaviour).
- **FR-014**: The existing review configuration (dimensions list, `rewrite_threshold`, enabled flag) MUST continue to work without operator changes. The new `critical_requirements_underweighted` dimension is always on (not opt-in via `review_config.dimensions`) because it is core to the review's purpose.
- **FR-015**: The existing review-stage Pydantic output schema (`LetterReviewReport`, `SectionReview`, `WeaknessEntry`) MUST remain unchanged. The new dimension is encoded as a weakness-text tag, not as a new schema field.

#### Non-interference

- **FR-016**: MLflow logging behaviour MUST be unchanged: same tag names, same metric names. The per-stage prompt hash for `hiring_reviewer` WILL flip naturally because `hiring_reviewer.md` and `hiring_review.build_prompt` change; tag NAMES stay the same.
- **FR-017**: Langfuse trace structure MUST be unchanged: same per-stage spans, same metadata field names. The `prompt_content_hash` for the `hiring_review` span flips naturally; the trace shape is identical.
- **FR-018**: The CLI contract MUST be unchanged: same commands, same flags, same exit codes, same output files.
- **FR-019**: The Langfuse prompt-registry (feature 007) MUST be expected to record one new version of `bewerbungs-agent/hiring_reviewer` on the next `jobagent prompts sync`, with the other 9 prompts unchanged. This is the intended observable signal of the prompt edit.

#### Tests

- **FR-020**: The system MUST provide an automated test asserting that the constructed hiring-review prompt contains the raw job description text verbatim AND the populated parsed-job-context structured fields AND (when present) the content plan AND the extracted-requirement summary AND the letter text — all under clearly distinguishable labels.
- **FR-021**: The system MUST provide an automated test asserting that the hiring-review stage runs without exception when `state.job_context` is None (legacy / no-job-context path).
- **FR-022**: The system MUST provide an automated test asserting that the hiring-review stage runs without exception when `state.content_plan` is None (validate-only path; no planner output).
- **FR-023**: The system MUST provide an automated test asserting that a canned LLM review payload flagging a letter whose opening emphasises a secondary domain (the `secondary_topic_dominance` or `role_match` dimension at severity ≥ medium) routes the opening section into `sections_to_rewrite` — verifying the rewrite-routing behaviour on the new combined-context shape, not just on the feature 008 minimum context.
- **FR-024**: The system MUST provide an automated test asserting that the prompt's active-dimensions list contains `critical_requirements_underweighted` in addition to the existing dimensions.
- **FR-025**: The system MUST provide an automated test asserting that a canned LLM review payload flagging `critical_requirements_underweighted` at severity ≥ medium routes the affected section into `sections_to_rewrite`.

### Key Entities

- **Job Context Block**: the labelled prompt section the reviewer reads first. Contains the verbatim raw job description and any populated structured fields (job title, company name, optional company info text, optional storyboard text). Omits any field that is None on `state.job_context`.
- **Content Plan Block**: a labelled prompt section presenting the structured plan as read-only context for the reviewer. Contains section titles + key claims and, when present, the role-positioning summary. NOT a target for evaluation — only the letter is evaluated.
- **Critical-Requirements Dimension**: a new always-on evaluation dimension that complements the existing five from feature 008. Fires when a top-priority job requirement receives thin or absent treatment in the letter. Tagged in weakness text so the existing tag-scanning routing works unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of hiring-review invocations on states where `job_context.raw_job_text` is populated, the constructed prompt contains the raw job description text verbatim.
- **SC-002**: For 100% of hiring-review invocations on states where `job_context` carries any populated structured field (job title, company name, etc.), the constructed prompt contains that field's value verbatim under a distinguishable heading.
- **SC-003**: For 100% of hiring-review invocations on states where `content_plan` is populated, the constructed prompt contains the plan's section titles + key claims, and (when present) the role-positioning summary.
- **SC-004**: For 100% of hiring-review invocations on states where `job_context` is None, the prompt builds without exception and contains the documented placeholder.
- **SC-005**: For 100% of hiring-review invocations on states where `content_plan` is None, the prompt builds without exception.
- **SC-006**: For 100% of hiring-review prompts the evaluation-dimensions list contains the seven dimensions: the five from feature 008 plus the new `critical_requirements_underweighted` plus whatever standard dimensions the operator's `review_config.dimensions` requests.
- **SC-007**: When a canned LLM review payload flags `critical_requirements_underweighted` at severity ≥ medium on a section, the parsed `LetterReviewReport.sections_to_rewrite` contains that section in 100% of test executions.
- **SC-008**: A canned LLM review payload flagging a secondary-domain opening on the AI/ML infrastructure regression fixture (from feature 008) causes the parsed `LetterReviewReport.sections_to_rewrite` to contain the opening section in 100% of test executions, confirming that the combined-context shape preserves feature 008's rewrite routing.
- **SC-009**: Outputs of MLflow logging and Langfuse tracing (excluding the naturally-flipping `prompt_content_hash` for `hiring_reviewer`) are unchanged compared to a pre-feature run on the same fixture inputs — verified by structural equivalence of MLflow run params/tags/metrics and Langfuse span shape.

## Assumptions

- The hiring-review stage already receives `WorkflowState`, which already carries `job_context`, `requirements`, `content_plan`, and `letter_draft`. No new state field or constructor argument is introduced.
- The verbatim raw job description was added to the review prompt by feature 008; this feature ADDITIONALLY adds the parsed structured fields (job title, company name, optional company info, optional storyboard) and the content plan. The combined effect is "full job context" as named in this feature.
- The content-plan block is a structured summary (section titles + key claims + role-positioning summary), not the full JSON dump. Operators who want to see the full plan can still read `artifacts/content_plan.json`; the prompt focuses on what helps the reviewer judge alignment.
- `critical_requirements_underweighted` is added as an always-on dimension (parallel to feature 008's five), not as a config opt-in. Operators who want to disable any standard dimension can still tune `review_config.dimensions`; the always-on positioning + criticality dimensions are core to the stage's purpose.
- "Critical requirement" is judged by the LLM from the job description — the prompt instructs it to treat the top one or two responsibilities from the job ad as critical, not every bullet in the requirements list. This avoids the reviewer flagging every minor mention as a failure.
- Backward compatibility for None fields uses graceful omission (not "(none)" placeholders) so the prompt stays readable and focused.
- The Langfuse prompt registry (feature 007) automatically picks up the prompt change: the next `jobagent prompts sync` will produce one new `bewerbungs-agent/hiring_reviewer` version and leave the other 9 prompts unchanged.
- This feature does NOT introduce a new pipeline stage, a new artefact file, a new CLI command, or a new MLflow/Langfuse metric. All changes live inside `prompts/hiring_reviewer.md` and `stages/hiring_review.py::build_prompt`.
- This feature does NOT modify the `LetterReviewReport` Pydantic schema. The new dimension is identified by a tag inside the existing `WeaknessEntry.text` field — consistent with how feature 008's five positioning dimensions are routed.
- This feature does NOT change the writer prompt, the planner prompt, the targeted-rewrite prompt, or any other prompt file. Only `prompts/hiring_reviewer.md` is edited.
