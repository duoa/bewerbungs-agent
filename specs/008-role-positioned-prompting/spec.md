# Feature Specification: Role-Positioned Prompting

**Feature Branch**: `008-role-positioned-prompting`
**Created**: 2026-05-13
**Status**: Draft
**Input**: User description: "Add role-positioned prompting for the job application agent. The feature must improve the existing prompt behavior so generated cover letters are organized around the primary hiring story of the job, not around a flat list of matched evidence. The planner must identify the primary role family, primary selling point, secondary selling points, topics to emphasize, topics to deemphasize, and the intended opening angle. The writer must use this positioning to open with the role's main hiring thesis, prefer system-level outcomes over tool lists, avoid overloading paragraphs with technologies, avoid self-rating phrases such as expert-level or deep expertise, and introduce no claims that are not present in the content plan. The hiring review must receive the full job description in addition to extracted requirements and the draft letter, and must explicitly evaluate whether the letter matches the primary role described in the original job ad, whether the opening paragraph reflects the top requirements, whether secondary domain topics dominate the main role, whether tool density is too high, and whether any wording risks overclaiming. The feature must keep retrieval behavior, evidence mapping behavior, MLflow logging, Langfuse tracing, and final CLI contract unchanged except for passing the full job description into the hiring review context. Prefer prompt and context changes over schema changes. Only change schemas if the existing structures cannot represent the required role-positioning information. Add or update tests using a fixture similar to an AI/ML infrastructure software engineering job where biomedical data is a secondary advantage, and verify that the planner and review prefer an infrastructure-first positioning rather than a biomedical-ML-first positioning."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Planner Produces an Explicit Role-Positioning Decision (Priority: P1) 🎯 MVP

A candidate applies for a role that, on the surface, intersects two domains: the role's *primary* purpose (e.g., building AI/ML infrastructure for software engineering teams) and a *secondary* asset the candidate happens to bring (e.g., biomedical-ML background that's a nice-to-have but not the job). Today, the planner would mostly fold all matched evidence into a flat list of sections and the letter often leads with the candidate's strongest evidence — which is frequently the secondary domain, not the role. With this story, the planner explicitly decides the role's primary family, the single best-fit selling point, two or three secondary selling points, which topics to emphasise, which topics to de-emphasise, and the opening angle the letter should take. The downstream writer and reviewer both see this decision and work from it.

**Why this priority**: This is the foundation. Without an explicit positioning decision attached to the content plan, the writer has nothing to align against and the reviewer has nothing to evaluate alignment with. Every other improvement in this feature depends on it.

**Independent Test**: Run the planner stage on a fixture AI/ML infrastructure job with a profile that has both strong infrastructure projects and a notable biomedical-ML project. Assert the resulting plan explicitly records `primary_role_family` as an infrastructure/platform/MLOps category (not "biomedical ML"), names an infrastructure-flavoured `primary_selling_point`, lists biomedical-ML in `secondary_selling_points`, and chooses an opening angle that frames the candidate as a systems/infrastructure builder.

**Acceptance Scenarios**:

1. **Given** an AI/ML infrastructure job description and a profile with both infrastructure and biomedical-ML evidence, **When** the planner runs, **Then** the resulting content plan records: `primary_role_family ≈ infrastructure/ML platform`, `primary_selling_point` referencing systems/platform work, `secondary_selling_points` including the biomedical-ML angle, `topics_to_emphasise` covering pipelines/observability/platform reliability, `topics_to_deemphasise` covering biomedical domain depth, and `opening_angle` that leads with infrastructure/systems framing.
2. **Given** a job description that is primarily about biomedical-data ML modelling, **When** the same profile runs through the planner, **Then** the positioning flips: `primary_role_family ≈ ML modelling on biomedical data`, `primary_selling_point` references biomedical-ML, and infrastructure work moves to `secondary_selling_points`. The same evidence set produces a different positioning depending on the job.
3. **Given** a job description where the role is unambiguous (only one family appears), **When** the planner runs, **Then** `secondary_selling_points` MAY be empty or short and `topics_to_deemphasise` MAY be empty; the planner does not fabricate a fake secondary domain just to fill the slot.

---

### User Story 2 — Writer Opens with the Role's Hiring Thesis, Not a Tool List (Priority: P1)

The writer must reorganise its output around the planner's positioning decision. The opening paragraph leads with the role's primary thesis (what the company is hiring for), not the candidate's longest evidence trail. Paragraphs prefer system-level outcomes ("ran a 1000-job/day pipeline reliably under tight SLOs") over tool laundry lists ("Python, Airflow, Kafka, Spark, Beam, Snowflake, dbt, Terraform, Kubernetes, Argo, ..."). The writer avoids self-rating phrases like "expert-level", "deep expertise", "world-class". The writer introduces no claim not present in the content plan — the existing factuality invariant — and additionally surfaces nothing the planner explicitly marked as `topics_to_deemphasise` except as a brief secondary mention.

**Why this priority**: Same priority as US1 because the positioning data only delivers value if the writer actually uses it. A planner that decides infrastructure-first but a writer that still opens with "I have deep biomedical-ML expertise" produces a letter that reads as misaligned regardless of how good the upstream plan is. US1 + US2 ship together as the MVP.

**Independent Test**: Run the writer on a fixture content plan whose `primary_role_family` is "AI/ML infrastructure" and whose `topics_to_deemphasise` includes "biomedical domain depth". Assert the opening paragraph (first 400 chars) references infrastructure/systems language; assert no paragraph contains more than a configurable number of distinct tool names (default 4); assert the rendered letter contains zero instances of the banned self-rating phrases; assert the de-emphasised topic appears at most once in the letter.

**Acceptance Scenarios**:

1. **Given** a content plan whose positioning declares an infrastructure primary role, **When** the writer renders the letter, **Then** the first paragraph references the role's infrastructure thesis (e.g., "platform reliability", "pipeline scaling", "MLOps systems") within the first 400 characters and does not lead with the candidate's biomedical background.
2. **Given** the same content plan, **When** the writer renders the letter, **Then** no paragraph contains more than the configured maximum number of distinct tool/technology names (default 4) — outcomes and responsibilities take precedence over tool inventories.
3. **Given** the same content plan, **When** the writer renders the letter, **Then** the rendered text contains zero instances of the banned self-rating phrases ("expert-level", "deep expertise", "world-class", "guru", "rockstar"). The list of banned phrases is configurable.
4. **Given** a content plan with positioning fields populated, **When** the writer renders the letter, **Then** every concrete claim in the letter traces to an entry in the plan's `key_claims` or `evidence_refs` — no new tools, employers, or results are introduced.
5. **Given** a content plan whose `topics_to_deemphasise` lists "biomedical domain depth", **When** the writer renders the letter, **Then** the de-emphasised topic appears at most as a brief secondary mention (not as a section heading, not in the opening paragraph, not repeated).

---

### User Story 3 — Hiring Review Sees Full Job Context and Flags Positioning Failures (Priority: P2)

The existing hiring-review stage (feature 005) currently sees the draft letter and the structured requirement extraction. It does NOT see the original job description text. This is a gap: a reviewer trying to judge "does the letter match the actual role" cannot do so without the original ad. With this story the review stage additionally receives the full job description text. The reviewer's evaluation gains five explicit positioning-aware checks: (1) does the letter match the primary role described in the original job ad? (2) does the opening paragraph reflect the job's top requirements? (3) do secondary-domain topics dominate the main role? (4) is the tool density too high? (5) does any wording risk overclaiming? Each check produces a strength/weakness entry, and structurally weak letters trigger the existing targeted-rewrite path.

**Why this priority**: P2 because US1+US2 already produce better letters; this story closes the verification loop. Without it, positioning regressions could slip past the review. With it, the existing rewrite stage (also feature 005) has a chance to catch and fix positioning errors per-section.

**Independent Test**: Run the hiring-review stage on a fixture where the draft letter leads with biomedical-ML and the job is infrastructure-focused. With the full job text supplied, assert the review's `weaknesses` for the opening section include an entry flagging "letter leads with secondary domain", severity ≥ medium, and the opening section is on the `sections_to_rewrite` list. Run the same review with positioning correctly aligned; assert no positioning-flavoured weakness is raised.

**Acceptance Scenarios**:

1. **Given** the hiring-review stage runs after a draft letter is generated, **When** building its prompt, **Then** the prompt input MUST include the full job description text in addition to the extracted requirements and the letter text. The review must NOT see the candidate's profile, CV variants, or evidence map.
2. **Given** a letter whose opening paragraph leads with a secondary-domain story while the job is primarily about a different role family, **When** the review runs, **Then** the review records a weakness on the opening section explicitly naming "letter leads with secondary domain / does not match primary role", severity at least medium.
3. **Given** a letter where any paragraph names more than the configured number of tools, **When** the review runs, **Then** the review records a weakness explicitly naming "tool density too high in <section>", severity at least medium.
4. **Given** a letter containing any banned self-rating phrase, **When** the review runs, **Then** the review records a weakness explicitly naming "overclaiming language detected", severity at least medium, with the offending phrase quoted.
5. **Given** a letter whose positioning is well aligned with the job ad, **When** the review runs, **Then** none of the new positioning-specific weaknesses fire, and `sections_to_rewrite` is empty (assuming no other quality issues).

---

### Edge Cases

- **Job description is ambiguous between two role families**: the planner picks the family with the strongest signal from the job description text itself, NOT the candidate's strongest evidence. If the job is genuinely 50/50, the planner records both in a single comma-separated `primary_role_family` value and the writer leads with the union framing rather than picking one arbitrarily.
- **Profile has no evidence for the primary role family**: the planner still positions toward the primary role and explicitly records the gap in the existing `known_gaps` field; the writer opens with the strongest adjacent transferable experience and acknowledges (briefly, factually) the gap rather than inventing matching evidence.
- **All candidate evidence is in the secondary domain**: same as above — positioning toward the primary role wins; the letter does not silently flip to a secondary-domain pitch because the evidence is stronger there.
- **A job calls for both a strong primary role and a strong secondary domain** (e.g., "ML infra engineer with biomedical-data experience"): positioning records both correctly; secondary-domain mentions are allowed in the body but the opening leads with the primary role.
- **Tool density limit conflicts with a sentence quoting a job requirement**: when the job ad itself lists 6 technologies, the writer is permitted to echo those technologies once in a single sentence (acknowledging the requirement) but MUST NOT repeat similar density elsewhere in the letter.
- **Banned self-rating phrase appears inside a quoted evidence passage**: still flagged as overclaiming. The candidate's own copy is not exempt from the constraint just because it was previously approved as evidence.
- **Existing letters in the profile contain banned phrases**: those previous letters are evidence of phrasing the candidate has used, not a license to reuse them in the new letter; the writer ignores them as exemplars when they violate the new constraints.
- **A previous run wrote a letter that violates the new constraints, and that letter is now in the profile as a previous_letter example**: the new prompts treat this case as a known anti-pattern; the writer is instructed to favour newer constraints over older phrasings.

## Requirements *(mandatory)*

### Functional Requirements

#### Planner positioning output

- **FR-001**: The planner stage MUST produce, alongside the existing sections and evidence references, a structured positioning decision with the fields: `primary_role_family` (single string), `primary_selling_point` (single string), `secondary_selling_points` (list of strings, may be empty), `topics_to_emphasise` (list of strings), `topics_to_deemphasise` (list of strings, may be empty), `opening_angle` (single string describing the angle the letter should take in its opening paragraph).
- **FR-002**: The planner MUST derive positioning primarily from the job description and the extracted requirements — NOT from whichever evidence happens to be strongest. The candidate's evidence informs how the positioning is supported, not what it is.
- **FR-003**: When the job is unambiguous (a single dominant role family), the planner MUST populate `primary_role_family` with the matching family name; `secondary_selling_points` and `topics_to_deemphasise` MAY be short or empty.
- **FR-004**: When the candidate's strongest evidence does NOT match the job's primary role family, the planner MUST still position toward the job's primary role; the candidate's strongest evidence is recorded in `secondary_selling_points`, not in `primary_selling_point`.
- **FR-005**: When no evidence supports the primary role family, the planner MUST record the gap in the existing `known_gaps` field rather than fabricate a matching `primary_selling_point` or downgrade the `primary_role_family` to whatever the evidence supports.

#### Writer behaviour

- **FR-006**: The writer MUST read the planner's positioning fields. The opening paragraph of the rendered letter MUST reference the `primary_role_family` and the `opening_angle` within its first 400 characters; the opening paragraph MUST NOT lead with content drawn primarily from `secondary_selling_points` or `topics_to_deemphasise`.
- **FR-007**: The writer MUST prefer system-level outcomes (responsibilities, scope, results, measurable impact) over flat tool/technology enumerations. No paragraph in the rendered letter MAY contain more than the configured maximum number of distinct tool/technology names (default 4).
- **FR-008**: The writer MUST NOT use any phrase from the configured ban list of self-rating expressions. Default ban list includes: "expert-level", "deep expertise", "world-class", "guru", "rockstar", "10x", "ninja". The list MUST be configurable.
- **FR-009**: The writer MUST NOT introduce any concrete claim (skill, tool, employer, role, project, metric) that is not already represented in the content plan's evidence references or key-claim list. This restates and reinforces the existing factuality invariant.
- **FR-010**: Topics listed in `topics_to_deemphasise` MAY appear in the letter only as brief secondary mentions — never as a section heading, never inside the opening paragraph, never repeated across multiple paragraphs.

#### Hiring review with full job context + positioning checks

- **FR-011**: The hiring-review stage MUST receive the full original job description text in addition to the previously-supplied draft letter and structured requirements. The review MUST NOT receive the candidate's profile, CV variants, evidence map, or rendered prompts.
- **FR-012**: The hiring-review evaluation MUST include all five positioning-specific dimensions:
  - (a) role match — does the letter match the primary role described in the original job ad?
  - (b) opening alignment — does the opening paragraph reflect the job's top requirements?
  - (c) secondary-topic dominance — do secondary-domain topics dominate the main role?
  - (d) tool density — is the tool density too high?
  - (e) overclaiming — does any wording risk overclaiming?
- **FR-013**: When any of (a)–(e) fails, the review MUST record a weakness with severity at least medium, attached to the relevant section, with a `priority_fix` describing the corrective rewrite the targeted-rewrite stage should perform.
- **FR-014**: Sections whose weaknesses include at least one positioning-specific failure at severity ≥ the configured `rewrite_threshold` MUST appear in `sections_to_rewrite` and trigger the existing targeted-rewrite path. No new pipeline stage is introduced — the existing rewrite stage handles the corrective action using the new weakness entries.

#### Non-interference with the rest of the pipeline

- **FR-015**: Retrieval behaviour (which sources are loaded, which CV variant is selected) MUST be unchanged.
- **FR-016**: Evidence mapping behaviour (which claims are evidenced, which passages are stored) MUST be unchanged.
- **FR-017**: MLflow logging behaviour MUST be unchanged: same parameters, tags, metrics, and per-stage records as before this feature.
- **FR-018**: Langfuse tracing behaviour MUST be unchanged: same trace structure, same per-stage spans, same metadata fields. The new positioning fields appear inside the existing content plan summary and the existing hiring-review prompt; they do NOT add new spans, new metrics, or new tags.
- **FR-019**: The final CLI contract MUST be unchanged: same commands, same flags, same exit codes, same output files. The only operator-visible change is improved letter quality.
- **FR-020**: The hiring-review stage gains the full job description as a new input. This is the ONLY new data flow introduced by the feature.

#### Implementation discipline

- **FR-021**: The feature MUST prefer prompt-content changes over schema changes. Schema additions are permitted ONLY when the existing structures cannot represent the required positioning information (e.g., adding the positioning sub-object to the existing content plan), and each addition MUST be justified in the implementation plan.
- **FR-022**: Tool-density and ban-phrase lists MUST live in configuration (per starter template), with the documented defaults applied when unset. They MUST NOT be hard-coded in prompt files.

#### Tests

- **FR-023**: The system MUST include a new fixture job description for an AI/ML infrastructure software-engineering role plus a fixture profile that has both strong infrastructure projects and a notable biomedical-ML project.
- **FR-024**: The system MUST include an automated test that runs the planner on that fixture and asserts the positioning fields name an infrastructure/platform `primary_role_family`, an infrastructure-flavoured `primary_selling_point`, and biomedical-ML in `secondary_selling_points` (NOT in `primary_selling_point`).
- **FR-025**: The system MUST include an automated test that constructs a content plan with the wrong positioning (biomedical-ML primary), runs the writer, runs the hiring review on the resulting letter with the full infrastructure job text supplied, and asserts the review flags at least the role-match and opening-alignment weaknesses with severity ≥ medium.
- **FR-026**: The system MUST include an automated test that runs the writer on a correctly-positioned plan and asserts: opening paragraph contains an infrastructure keyword in its first 400 characters; no paragraph contains more than the configured number of distinct tool names; the letter contains zero instances of any banned self-rating phrase.
- **FR-027**: The system MUST include an automated test that asserts MLflow logging and Langfuse trace shape are byte-identical (or field-equivalent) between a pre-feature run and a post-feature run on the same fixture inputs, except for the new positioning summary fields on the content-plan trace span.

### Key Entities

- **Role Positioning**: a structured decision attached to the content plan, recording how the letter should be framed relative to the target job — primary role family, primary selling point, secondary selling points, topics to emphasise / de-emphasise, opening angle. Lives within the content plan, not as a separate stage output.
- **Hiring-Review Job Context**: the full job description text passed into the hiring-review stage in addition to the existing structured requirements + draft letter. Read-only for the review; never passed to the writer or targeted-rewrite stage (those keep their existing isolation).
- **Tool-Density Threshold**: a configurable integer (default 4) capping the number of distinct tool/technology names allowed in a single paragraph of the rendered letter.
- **Self-Rating Ban List**: a configurable list of phrases the writer is forbidden from producing and the reviewer is required to flag. Default list documented in FR-008.
- **Positioning Weakness**: a hiring-review weakness entry tagged with one of the five positioning dimensions (role match, opening alignment, secondary-topic dominance, tool density, overclaiming). Routes to the existing targeted-rewrite stage via the existing `sections_to_rewrite` mechanism.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of runs on a fixture job description where the primary role family is unambiguous, the planner produces a `primary_role_family` value matching that family (not the candidate's strongest-evidence domain).
- **SC-002**: For 100% of runs on the AI/ML-infrastructure fixture with a profile carrying both infrastructure and biomedical-ML evidence, the planner records the biomedical-ML angle in `secondary_selling_points` and does NOT record it in `primary_selling_point`.
- **SC-003**: For 100% of rendered letters produced by the writer when given a positioning-populated content plan, the opening paragraph (first 400 characters) references the `primary_role_family` or `opening_angle` and does not lead with a `topics_to_deemphasise` topic.
- **SC-004**: Across a corpus of 20 rendered letters produced under default configuration, zero paragraphs contain more than 4 distinct tool/technology names.
- **SC-005**: Across the same corpus, zero rendered letters contain any banned self-rating phrase from the default list.
- **SC-006**: For 100% of hiring-review invocations the review prompt receives the full job description text alongside the requirements and draft letter; the review prompt does not receive the candidate's profile, CV variants, or evidence map.
- **SC-007**: When the writer produces a draft that violates a positioning constraint, the hiring review flags the matching weakness at severity ≥ medium in 100% of cases for an audit set of 20 deliberately-miswritten fixtures (one per failure mode × 4 examples).
- **SC-008**: Retrieval, evidence mapping, MLflow logging, Langfuse tracing, and CLI contract behaviour are unchanged: comparing pre-feature and post-feature outputs on the same fixture inputs produces equivalent results for these subsystems (the only allowed differences are the new positioning summary fields on the content-plan span and the improved letter content).

## Assumptions

- The existing content plan (`ContentPlan`) is the natural carrier for the positioning decision; positioning is added as a nested sub-object so the existing structure does not need to be restructured. This is the only schema change anticipated and is permitted under FR-021.
- The existing `WorkflowState.job_context` already carries the full job description text (it was loaded by the `load_job` stage); the hiring-review stage simply reads it via state rather than receiving a new constructor argument. No new data load is introduced.
- "Tool / technology name" is recognised against a working list (programming languages, frameworks, platforms, services) sufficient for the current candidate's domain; precision is not perfect but is good enough to enforce the cap. Operators can tune the list later via configuration.
- "Primary role family" values are short human-readable strings (e.g., "ML platform engineering", "biomedical data ML modelling", "backend platform engineering"), not a closed enum. The planner picks language that mirrors the job ad's own framing.
- The writer's "no paragraph contains more than N tool names" rule is enforced primarily by prompt instruction. Deterministic post-validation (counting tool names per paragraph) is a useful safety net but is not required for v1; if added, it goes through the existing validation rule mechanism.
- The hiring-review prompt change is additive (one new context block + one new dimension list); it does not require a new structured-output schema. The existing `LetterReviewReport` already supports section-attached weaknesses with severity and priority-fix text — the positioning checks reuse those slots.
- Default tool-density cap is 4 distinct tool/technology names per paragraph. Default self-rating ban list is the seven entries in FR-008. Both are exposed in the starter template under a new optional `writer_rules` block.
- This feature does NOT introduce a new pipeline stage, a new artefact file, or a new CLI command. It does NOT change MLflow tag names, Langfuse span structure, or the output artefact set. Operators see better letters, not new interfaces.
- This feature does NOT depend on Langfuse or MLflow being enabled. With observability turned off, planner positioning and writer behaviour still work; only the trace-visibility benefit is reduced.
- Bounding `topics_to_deemphasise` to "appears at most as a brief secondary mention" is enforced primarily by prompt instruction; the review stage catches violations via the secondary-topic-dominance check (FR-012c) and the targeted-rewrite stage corrects them.
- The fixture AI/ML infrastructure job description (FR-023) describes a hire whose core remit is platform/MLOps work — building, scaling, and operating ML inference and training infrastructure for software engineering teams — with biomedical data listed as a nice-to-have context rather than a primary requirement.
