# Feature Specification: Positioning Validation & Review Checks

**Feature Branch**: `012-positioning-validation`
**Created**: 2026-05-27
**Status**: Draft
**Input**: User description: "Add validation and review checks for role fit, opening alignment, weighted requirement coverage, tool density, secondary angle dominance, and simple overclaim risk. The validation layer should produce structured findings and scores but should not block successful runs unless configured. The hiring_review stage should report whether the letter matches the primary role family from the full job description and role_positioning object. Add deterministic checks where possible and optional LLM-assisted checks behind configuration. The checks must identify cases where a letter is factually relevant but wrongly positioned. Add tests for a letter that overemphasizes biomedical science for an AI infrastructure role, a letter with excessive tool density, and a letter containing risky wording such as expert-level or production distributed training."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deterministic positioning safety net on every run (Priority: P1)

An operator runs `jobagent run` for any job and template. After the letter is generated, a validation layer evaluates the letter against a fixed suite of deterministic checks — role-fit opening, weighted requirement coverage, tool density per paragraph, secondary-angle dominance, and overclaim risk — and writes a structured `ValidationReport` to the run's output directory. The run still completes successfully even when findings are reported, so operators can ship while iterating on prompts. The report surfaces "this letter passes / has 2 warnings / has 1 error" at a glance, with per-check rationale and citations the operator can click through to in the letter.

**Why this priority**: This is the MVP. The deterministic suite runs every time, costs nothing additional in tokens, and immediately catches the most common positioning failures (tool-soup paragraphs, biomedical-leading opening for an AI-infra role, banned self-rating phrases). It also provides the reusable `ValidationReport` artefact that US2 and US3 build on.

**Independent Test**: Build a `WorkflowState` with a known content plan, a known letter draft, and a known set of weighted requirements. Run the validation layer. Inspect the produced `ValidationReport.findings`: assert the expected check ids appear with the expected severities and that the run exit code is 0.

**Acceptance Scenarios**:

1. **Given** a letter whose opening paragraph mentions "AI/ML infrastructure" when `role_positioning.role_family = "AI/ML platform engineering"`, **When** the validation layer runs, **Then** the `role_fit_opening` finding is `pass` and no warnings about role fit are emitted.
2. **Given** a letter whose opening paragraph leads with "Throughout my biomedical research career..." when `role_positioning.role_family = "AI/ML platform engineering"`, **When** the validation layer runs, **Then** both `role_fit_opening` and `secondary_angle_dominance` findings have severity `warn` or higher and the rationale names the offending substring.
3. **Given** a letter where one paragraph names 8 distinct tools and the template caps `tool_density_max=4`, **When** the validation layer runs, **Then** the `tool_density` finding has severity `warn`, the rationale names the offending paragraph index, and the finding's `evidence.spans` cite the paragraph's character range.
4. **Given** a weighted-requirement set with two `priority=high, evidence_needed=required` items where the letter only mentions one of them, **When** the validation layer runs, **Then** the `weighted_requirement_coverage` finding has severity `warn` and the rationale lists the missing `RequirementItem.id`.
5. **Given** a letter containing the substring "expert-level" or "production distributed training" anywhere in its body, **When** the validation layer runs, **Then** the `overclaim_risk` finding has severity `warn` and the rationale quotes the offending phrase verbatim.
6. **Given** any of the above findings, **When** the run completes, **Then** the pipeline exit code is 0 (non-blocking by default) and the report is persisted at `outputs/<run_id>/artifacts/validation_report.json`.

---

### User Story 2 - Hiring review reports primary-role-family alignment (Priority: P2)

The existing `hiring_review` stage gains an additional structured field: `primary_role_family_match`, taking values `match`, `partial_match`, or `mismatch`, with a short rationale grounded in the full job description text and the content plan's `role_positioning.role_family`. This catches the "factually relevant but wrongly positioned" failure mode: a letter where every claim is true, every tool name is accurate, but the candidate is implicitly applying for the wrong job. When the LLM judges `mismatch`, the rationale must quote evidence from the letter that supports the verdict.

**Why this priority**: P2 because the deterministic checks (US1) catch the obvious surface failures, but the subtle "wrongly positioned" failure requires LLM judgment over the whole letter. It also lives inside an existing stage rather than introducing a new pipeline node, so it ships with low risk.

**Independent Test**: Provide a curated fixture pair (job description for an AI-infra role + a letter that emphasises biomedical science). Run the hiring_review stage. Assert the structured output contains `primary_role_family_match = "mismatch"` and the rationale cites a biomedical-leading sentence from the letter.

**Acceptance Scenarios**:

1. **Given** a letter whose body matches the job's primary role family (≥ 70% of body characters address the primary family), **When** `hiring_review` runs, **Then** `primary_role_family_match = "match"` and the rationale is one sentence.
2. **Given** a letter whose body addresses the primary family but spends > 30% of body characters on a secondary family, **When** `hiring_review` runs, **Then** `primary_role_family_match = "partial_match"` and the rationale names both families.
3. **Given** a letter where the primary family is only mentioned in the closing line and the bulk of the body addresses a different family, **When** `hiring_review` runs, **Then** `primary_role_family_match = "mismatch"` and the rationale quotes evidence from the letter body.
4. **Given** the LLM call to the hiring reviewer fails (timeout, API error), **When** the stage continues, **Then** the `primary_role_family_match` field is recorded as `unknown` with a rationale explaining the failure, and the pipeline does NOT crash.

---

### User Story 3 - Optional configurable "fail on" thresholds (Priority: P3)

An operator running `jobagent run` in a CI / regression-guard context wants the pipeline to exit non-zero when a specific check fails (e.g., when `role_fit_opening` is severity ≥ error, or when the aggregate score drops below a threshold). The operator configures the threshold in the template config or via a CLI flag; when not configured, the default behaviour from US1 (non-blocking) is preserved.

**Why this priority**: P3 because it is purely a configurable behaviour switch on top of US1 — required for serious use of the validator as a regression gate, but not needed for first-class delivery of the value proposition.

**Independent Test**: Run the pipeline with `fail_on_severity = "error"` and a fixture letter that produces an `error`-severity finding; assert exit code is non-zero. Run the same fixture with the default configuration; assert exit code is 0.

**Acceptance Scenarios**:

1. **Given** the operator configures `validation.fail_on_severity = "error"` and the validation report contains at least one `error`-severity finding, **When** the run ends, **Then** the pipeline exits with a non-zero exit code AND the validation report is still persisted.
2. **Given** the operator configures `validation.fail_on_severity = "error"` and the validation report contains only `warn` or `info` findings, **When** the run ends, **Then** the pipeline exits with code 0.
3. **Given** the operator configures `validation.fail_on_check_ids = ["role_fit_opening"]` and the validation report contains a `role_fit_opening` finding at any severity ≥ `warn`, **When** the run ends, **Then** the pipeline exits with a non-zero exit code.
4. **Given** no validation gate configuration, **When** the run ends, **Then** the pipeline exits with code 0 regardless of findings (US1 default preserved).

---

### Edge Cases

- **Legacy content plan with no `role_positioning`**: role-fit-opening and secondary-angle-dominance checks emit a single `info` finding ("skipped — role_positioning not present in plan") and do NOT raise.
- **Legacy content plan with no `paragraphs` (feature 011 absent)**: tool-density check falls back to the global `writer_rules.tool_density_max` for the whole letter rather than per-paragraph; weighted_requirement_coverage skips paragraph-mapping and operates on the whole letter body.
- **Very short letter (< 200 characters)**: all checks emit `info` findings noting "insufficient text to evaluate" rather than warnings; aggregate score is recorded as `null` rather than 0.
- **LLM-assisted checks disabled by config**: only deterministic checks run; report's per-check list omits the LLM-assisted entries (does NOT emit placeholder rows).
- **LLM-assisted check call fails or times out**: failure is recorded as a single `info` finding with rationale explaining the failure; the pipeline continues.
- **Empty `requirement_items`**: weighted_requirement_coverage check emits an `info` finding and does NOT warn.
- **Tool name collisions inside larger words**: tool-density check matches whole words, case-insensitive — "Kafka" inside "kafkaesque" is NOT counted; "AWS" inside "AWS-managed" IS counted.
- **Banned phrase appears inside an evidence passage the letter is anchoring to**: the overclaim_risk check still fires (the letter must rephrase rather than echo banned wording).
- **`fail_on_*` configured but report is empty**: pipeline exits 0 (no findings = nothing to fail on).
- **Concurrent runs writing different `validation_report.json` files**: each run writes under its own `outputs/<run_id>/` directory; no collision.

## Requirements *(mandatory)*

### Functional Requirements

**Validation report shape & artefact**

- **FR-001**: System MUST produce a structured `ValidationReport` after letter generation that contains a list of per-check findings and an aggregate score.
- **FR-002**: Each finding MUST include `check_id`, `severity` (one of `info`, `warn`, `error`), `score` (numeric or null when skipped), short `rationale`, and an `evidence` block citing the offending span(s) of the letter or content plan.
- **FR-003**: The aggregate score MUST be a single numeric value in `[0, 100]` (higher = better) OR `null` when too few checks ran to score (see edge cases).
- **FR-004**: The `ValidationReport` MUST be persisted at `outputs/<run_id>/artifacts/validation_report.json` alongside existing artefacts.

**Default non-blocking behaviour**

- **FR-005**: By default, the validation layer MUST NOT change the pipeline's exit code regardless of findings; runs that successfully produce a letter continue to exit 0.
- **FR-006**: Operators MUST be able to configure a `fail_on_severity` threshold (one of `warn`, `error`); when set, the pipeline exits non-zero when at least one finding meets or exceeds that severity.
- **FR-007**: Operators MUST be able to configure a `fail_on_check_ids` list naming specific checks; when set, the pipeline exits non-zero when any of those checks emits a finding with severity ≥ `warn`.
- **FR-008**: When both `fail_on_severity` and `fail_on_check_ids` are set, the pipeline exits non-zero if EITHER condition matches.

**Deterministic checks**

- **FR-009**: System MUST emit a `role_fit_opening` finding evaluating whether the letter's opening (first ~400 characters) references the `role_positioning.role_family` or `role_positioning.opening_angle` substantively; the finding's severity MUST be `pass` when the role family or opening angle appears verbatim or via a short documented synonym list, `warn` when neither appears, and `info` when `role_positioning` is absent from the plan.
- **FR-010**: System MUST emit a `weighted_requirement_coverage` finding listing every `requirement_items[*].id` with `priority=high, evidence_needed=required` whose text or claim proxy does NOT appear in the letter or in any paragraph plan's `requirement_ids`; severity is `warn` if at least one is missing, `pass` otherwise, `info` when `requirement_items` is empty.
- **FR-011**: System MUST emit a `tool_density` finding evaluating each paragraph of the letter against its per-paragraph cap (`ParagraphPlan.max_tools` when present, otherwise `writer_rules.tool_density_max`); severity is `warn` if any paragraph exceeds its cap, `pass` otherwise; rationale must name the offending paragraph index and the over-quota tool names.
- **FR-012**: System MUST emit a `secondary_angle_dominance` finding evaluating whether topics listed in `role_positioning.deemphasise` appear in the opening paragraph or in the first one-third of the letter body; severity is `warn` if any such topic appears in those zones, `pass` otherwise, `info` when `role_positioning` is absent.
- **FR-013**: System MUST emit an `overclaim_risk` finding scanning the letter for banned-phrase substrings drawn from `writer_rules.banned_phrases` (existing config field) extended with a hard-coded baseline set including `"expert-level"`, `"world-class"`, `"production distributed training"`, `"guru"`, `"rockstar"`, `"10x"`, `"ninja"`; severity is `warn` when any phrase appears, `pass` otherwise; rationale quotes the offending phrase verbatim.

**Hiring-review extension (LLM-driven, lives inside existing `hiring_review` stage)**

- **FR-014**: The `hiring_review` stage MUST add a `primary_role_family_match` field with values `match`, `partial_match`, `mismatch`, or `unknown` to its structured output.
- **FR-015**: The judgement MUST be derived from BOTH the full job description text AND the content plan's `role_positioning.role_family`; the reviewer prompt is updated to instruct that derivation order (job description first, role_positioning as confirming context).
- **FR-016**: When `primary_role_family_match` is `partial_match` or `mismatch`, the rationale MUST quote at least one sentence from the letter body as evidence.
- **FR-017**: When `primary_role_family_match` is `mismatch`, the hiring review's existing aggregate `pass / needs_minor_revision / needs_major_revision` verdict MUST escalate to at minimum `needs_minor_revision` (cannot remain `pass`).
- **FR-018**: When the hiring-review LLM call fails or times out, `primary_role_family_match` MUST be recorded as `unknown` with a rationale explaining the failure; the pipeline MUST NOT crash.

**LLM-assisted validator checks (optional)**

- **FR-019**: System MUST gate any LLM-assisted validation checks behind a configuration flag (e.g., `validation.llm_checks_enabled`); when disabled (default), only deterministic checks run.
- **FR-020**: When LLM-assisted checks are enabled, the system MUST add a `wrongly_positioned` LLM-rated finding asking the model whether the letter is "factually accurate but applied to the wrong job", with severity derived from the model's verdict.
- **FR-021**: LLM-assisted check failures MUST be recorded as `info`-severity findings with rationale explaining the failure; they MUST NOT raise.
- **FR-022**: When LLM-assisted checks run, they MUST issue at most one additional LLM call per run (batched), not one per check.

**Configuration & override surface**

- **FR-023**: System MUST reuse `writer_rules.banned_phrases` as the seed for the overclaim_risk check; operators MUST be able to override or extend the seed list via template config.
- **FR-024**: System MUST allow operators to provide a custom tool-name registry per template via config; when absent, the system uses a default registry derived from the project's known stack.
- **FR-025**: System MUST allow operators to suppress individual checks via a `validation.disabled_checks` list of check ids; suppressed checks do NOT appear in the report and do NOT contribute to the aggregate score.

**Observability integration**

- **FR-026**: The aggregate validation score MUST be logged as an MLflow metric on the run; per-check severities MUST be logged as MLflow tags (one tag per check id).
- **FR-027**: The aggregate score and per-check severities MUST be attached to the Langfuse trace as span attributes on a dedicated `validation` span; the new span MUST be additive to the existing topology (no rename/restructure of existing spans).
- **FR-028**: New MLflow metric and tag names MUST follow the existing project naming convention (no breaking changes to existing dashboards).

**Non-interference & backward-compat**

- **FR-029**: System MUST handle a content plan without `role_positioning` (legacy) by emitting `info` findings for the affected checks (role_fit_opening, secondary_angle_dominance) rather than raising or returning `error` severity.
- **FR-030**: System MUST handle a content plan without `paragraphs` (pre-feature-011) by falling back to the whole-letter tool-density evaluation against `writer_rules.tool_density_max`.
- **FR-031**: System MUST handle a `RequirementExtraction` without `requirement_items` (legacy) by emitting an `info` finding for `weighted_requirement_coverage` rather than raising.
- **FR-032**: Existing artefacts (`letter.md`, `content_plan.json`, etc.) MUST NOT change format or filename; the validation report is purely additive.
- **FR-033**: Existing CLI exit codes for non-validation failure modes (LLM call failure during letter generation, missing inputs, etc.) MUST be preserved unchanged.

**Required test surface (FR-034–FR-037 — explicit per user request)**

- **FR-034**: A test MUST verify that a fixture letter overemphasizing biomedical-science content for a job whose `role_positioning.role_family = "AI/ML platform engineering"` produces BOTH a `role_fit_opening` finding with severity ≥ `warn` AND a `secondary_angle_dominance` finding with severity ≥ `warn`.
- **FR-035**: A test MUST verify that a fixture letter containing one paragraph naming 8 distinct tool names (cap = 4) produces a `tool_density` finding with severity `warn`, naming the offending paragraph index in the rationale.
- **FR-036**: A test MUST verify that fixture letters containing `"expert-level"` and `"production distributed training"` respectively each produce an `overclaim_risk` finding with severity `warn` whose rationale quotes the exact offending substring.
- **FR-037**: A test MUST verify that a "wrongly positioned" fixture letter (factually true but pitched at the wrong role family) produces `primary_role_family_match = "mismatch"` in the hiring-review output AND the hiring-review aggregate verdict is at minimum `needs_minor_revision`.

### Key Entities *(include if feature involves data)*

- **ValidationReport**: The top-level artefact produced after letter generation. Attributes: `run_id`, `aggregate_score` (numeric or null), `findings` (ordered list of CheckFinding), `report_version` (string for forward compatibility), `generated_at` (ISO 8601). Persisted as `validation_report.json`.
- **CheckFinding**: One row per check. Attributes: `check_id` (stable string, e.g., `role_fit_opening`), `severity` (`info` | `warn` | `error`), `score` (numeric or null), `rationale` (≤ 240 chars), `evidence` (list of citation spans referencing letter or plan offsets), `is_deterministic` (boolean), `disabled` (boolean for suppressed checks).
- **CitationSpan**: Attributes: `source` (`letter` | `content_plan` | `requirement_items`), `paragraph_index` (optional int), `char_start` / `char_end` (optional int), `quoted_text` (verbatim).
- **HiringReviewOutput (extended)**: Existing model gains `primary_role_family_match` (one of `match` | `partial_match` | `mismatch` | `unknown`), `primary_role_family_rationale` (string). All existing fields preserved.
- **ValidationConfig**: Per-template / per-run knobs. Attributes: `fail_on_severity` (optional `warn` | `error`), `fail_on_check_ids` (optional list of strings), `llm_checks_enabled` (boolean, default `false`), `disabled_checks` (optional list of check ids), `tool_registry` (optional list of tool names, overrides the default seed), `banned_phrase_extensions` (optional list of strings, additive to `writer_rules.banned_phrases`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of runs that successfully produce a letter also produce a `validation_report.json`.
- **SC-002**: 100% of runs that successfully invoke the `hiring_review` stage produce a `primary_role_family_match` value (`match`, `partial_match`, `mismatch`, or `unknown`).
- **SC-003**: On the curated fixture set described in FR-034 (biomedical-leading letter for an AI-infra role), the deterministic checks flag the mispositioning (at least one of `role_fit_opening`, `secondary_angle_dominance` at severity ≥ `warn`) in 100% of test runs.
- **SC-004**: On a curated fixture set of 10 well-positioned letters, the deterministic checks produce zero `warn`-or-higher findings on `role_fit_opening` AND zero `warn`-or-higher findings on `tool_density`, demonstrating < 5% false-positive rate at the per-check level.
- **SC-005**: When LLM-assisted checks are disabled (default), the validation layer adds ≤ 200 ms of median wall-clock overhead per run on a developer laptop, measured against the existing pipeline baseline.
- **SC-006**: When LLM-assisted checks are enabled, they add at most one additional LLM round-trip per run; no nested or sequential LLM calls are introduced.
- **SC-007**: 100% of legacy runs (content plan without `role_positioning`, without `paragraphs`, or without `requirement_items`) complete without raising; affected checks emit `info`-severity findings rather than errors.
- **SC-008**: When `fail_on_severity = "error"` is configured and the run produces zero `error`-severity findings, the pipeline exits with code 0.
- **SC-009**: When `fail_on_severity = "warn"` is configured and the run produces at least one `warn`-severity finding, the pipeline exits with a non-zero code AND the `validation_report.json` is still persisted in full.
- **SC-010**: The `validation_report.json` file is ≤ 50 KB on a representative run (no exorbitant payload bloat).

## Assumptions

- **Existing model surface stable**: `RolePositioning`, `WriterRules`, `RequirementItem`, `ParagraphPlan`, and the hiring-review structured output from features 008/010/011 remain stable and are reused as inputs to the new checks. No new dependencies, no new pipeline stages — the validation layer extends the existing post-letter validation surface and the existing `hiring_review` stage.
- **Where the validator lives**: The deterministic suite is added as an enhancement to the existing post-letter validation flow (existing `stages/validate.py` is the natural home). A new validation stage is NOT introduced. This preserves the pipeline graph and minimises observability churn.
- **Tool registry seed**: A small built-in seed list (Python, Kafka, Spark, Airflow, Beam, Snowflake, dbt, Terraform, Kubernetes, EKS, S3, MSK, RDS, AWS, GCP, Azure, Argo, Docker, PostgreSQL, Redis, PyTorch, TensorFlow, JAX, Ray, MLflow, FastAPI, Django, React, TypeScript, etc.) ships with the validator; operators can override or extend per template via config.
- **Banned-phrase seed**: The hard-coded baseline for `overclaim_risk` is the seven phrases already documented in `WriterRules.banned_phrases` (`expert-level`, `deep expertise`, `world-class`, `guru`, `rockstar`, `10x`, `ninja`) plus the explicitly-named additions from the user prompt (`production distributed training`). Operators can extend further via `banned_phrase_extensions`.
- **"Wrongly positioned" is LLM-only by default**: The deterministic checks catch the surface signals (opening misses role family, secondary topics dominate the opening, banned phrases). The full "factually relevant but wrongly positioned" judgement requires understanding the letter as a whole, which is delegated to the LLM-assisted check (when enabled) and to the existing hiring reviewer (US2).
- **`fail_on_*` defaults to off**: Default behaviour preserves backward compatibility — every existing run completes exactly as before, just with an extra artefact written.
- **Observability is additive**: New MLflow metrics/tags and Langfuse span attributes are added; no existing names are renamed or removed.
- **Legacy artefacts**: Old runs predating this feature (no `validation_report.json` in their output directory) continue to be valid; downstream consumers of the output directory MUST NOT assume the file's presence.
- **LLM judge for `primary_role_family_match`**: Reuses the existing `hiring_review` LLM call rather than adding a new one; the reviewer's structured-output schema is extended with two new fields, and the existing prompt is updated to ask for that judgement explicitly.
- **No CLI surface changes**: New configuration is read from the template / run config object; no new CLI flags or commands are introduced in this feature. (A future feature could add `--fail-on-severity` if useful, but it is out of scope here.)
- **Tests run with no real LLM calls**: All test fixtures use canned hiring-review responses where LLM judgement is needed; deterministic checks need no mocking.
