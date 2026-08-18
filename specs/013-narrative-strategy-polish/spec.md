# Feature Specification: Narrative Strategy & Story Polish

**Feature Branch**: `013-narrative-strategy-polish`
**Created**: 2026-05-27
**Status**: Draft
**Input**: User description: "Add a narrative strategy and story polish layer to improve cover letter quality beyond requirement matching. The system should create a NarrativeStrategy after role positioning and before content planning. NarrativeStrategy should define the candidate story, role story, bridge between the candidate background and target role, opening angle, proof points to use, proof points to avoid, transfer framing guidance, tone guidance, and anti-patterns. The goal is to make letters sound coherent, senior, credible, and less mechanically mapped to requirements. Add a story_polish stage after letter writing and before hiring review. This stage should improve flow, transitions, sentence rhythm, and naturalness without adding new facts, tools, metrics, employers, methods, or claims. It must preserve the factual content and evidence boundaries of the draft. Extend hiring_review to flag over-constructed transfer language, forced analogies, defensive domain-transition framing, overly dramatic AIDA language, weak narrative coherence, low-relevance impact claims, and machine-like requirement mapping. Support a restrained AIDA mode. AIDA should be used as a subtle narrative structure, not as marketing copy. The tone should remain calm, senior, credible, and institutionally appropriate. Do not change retrieval behavior, requirement extraction, role positioning, or evidence mapping in this feature. Add tests for a domain-transition case where the initial draft sounds too constructed and the polished version keeps the same facts but improves narrative flow."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Letters tell a coherent story instead of mapping bullets (Priority: P1)

An operator runs `jobagent run` for a job description. Before the planner produces a paragraph structure, a new `narrative_strategy` step interprets the same inputs the planner sees (job description, weighted requirements, evidence map, role positioning thinking) and produces a `NarrativeStrategy` — a short, opinionated document that names: WHO the candidate is in this letter (one paragraph), WHAT story the company wants told (one paragraph), the BRIDGE between the two (one paragraph), the opening angle, which evidence to lean on, which evidence to deliberately leave out, how to frame domain transitions naturally, the tone, and the anti-patterns the writer must avoid. The planner consumes this strategy. The writer consumes both the content plan and the strategy. The resulting letter reads as a single coherent argument from a senior professional — not as a list of requirements with matching bullets.

**Why this priority**: This is the MVP. Without an explicit narrative strategy, the planner and writer optimise for requirement coverage and produce letters that are factually correct but mechanically constructed. Adding the strategy upstream is the single biggest leverage point on perceived letter quality and runs once per pipeline call, not per draft.

**Independent Test**: Build a `WorkflowState` with a job description, requirements, evidence map, and a content plan that already exists. Run the `narrative_strategy` stage in isolation. Inspect the resulting `NarrativeStrategy` object: assert all nine fields are populated, that `proof_points_to_use` ids exist in the evidence map, that `proof_points_to_avoid` is non-empty (a senior letter chooses what NOT to say), and that the strategy's `tone_guidance` references the configured writing mode.

**Acceptance Scenarios**:

1. **Given** a job description and an evidence map containing 12 evidence claims spanning two domains, **When** `narrative_strategy` runs, **Then** the resulting strategy names ≤ 6 `proof_points_to_use` from the dominant-domain claims and at least 2 `proof_points_to_avoid` from the secondary-domain claims, with rationale.
2. **Given** a domain-transition case (candidate moving from research to industry), **When** `narrative_strategy` runs, **Then** `transfer_framing_guidance` contains concrete instructions on how to bridge the transition naturally (e.g., "lead with the transferable systems thinking; the research context only appears in one sentence as relevant credibility").
3. **Given** a content plan generated AFTER the narrative strategy exists, **When** the planner runs, **Then** the resulting paragraphs reflect the strategy's `opening_angle` and `bridge`, and any paragraph whose claims fall in `proof_points_to_avoid` is dropped or de-emphasised in the plan.
4. **Given** a writer call where both the content plan and the narrative strategy are present, **When** the writer runs, **Then** the produced letter's opening matches the strategy's `opening_angle` in substance (not necessarily verbatim), and the letter does not include claims listed in `proof_points_to_avoid`.
5. **Given** an AIDA writing-mode run, **When** `narrative_strategy` produces `tone_guidance`, **Then** the tone guidance explicitly constrains AIDA to a restrained, senior register (e.g., "use AIDA as a subtle arc, NOT as marketing copy — calm, credible, institutional voice throughout").
6. **Given** a legacy template with no narrative-strategy configuration, **When** the pipeline runs, **Then** the stage produces a minimal `NarrativeStrategy` derived from inputs and the run does not crash.

---

### User Story 2 - A polish pass smooths the letter without changing the facts (Priority: P2)

An operator runs `jobagent run`. After the writer produces a draft letter and before the hiring reviewer evaluates it, a new `story_polish` stage takes the draft and rewrites it for flow, transitions, sentence rhythm, and naturalness — but introduces NO new facts. No tool names appear that weren't in the draft. No employer names appear that weren't in the draft. No numbers or metrics appear that weren't in the draft. No claims appear that weren't in the draft. A deterministic post-check verifies these invariants by extracting the set of tool names, employer names, numeric tokens, and claim sentences from both the pre- and post-polish texts and refusing to advance if the polished version's set is not a subset of the draft's. When the check fails, the pipeline falls back to the unpolished draft and continues. The polished letter (or fallback draft) is what the hiring reviewer sees.

**Why this priority**: P2 because US1's narrative strategy lifts the upstream quality, but the writer still produces some mechanically-constructed seams. The polish stage smooths those seams without risking the factual contract that the rest of the pipeline guarantees. It's an isolated, low-risk improvement that runs once per draft.

**Independent Test**: Take a known draft letter containing a mechanically-constructed paragraph. Run `story_polish` on it. Assert that the polished version's set of {tool names, employer names, numeric tokens} is a subset of the draft's set. Assert that all evidence-anchor sentences from the draft are preserved (possibly reworded but factually identical). Assert that the polished version has at least one improved transition (measured by absence of bullet-like seams the draft had).

**Acceptance Scenarios**:

1. **Given** a draft letter containing 6 tool names (Python, Kafka, EKS, S3, RDS, MSK) and the polish stage runs, **When** the post-check executes, **Then** the polished letter contains a SUBSET of those names (zero new tool names) AND the check passes.
2. **Given** a draft letter with 3 numeric metrics ("1000 jobs/day", "99.9% SLO", "5 years"), **When** the polish stage runs, **Then** all three numeric tokens appear in the polished version (no metrics dropped), and no NEW numeric tokens appear.
3. **Given** a polish-stage LLM call that hallucinates a new tool name "Spark" not in the draft, **When** the post-check executes, **Then** the check FAILS, the pipeline falls back to the original draft, AND a warning is logged in the run output.
4. **Given** a polish-stage LLM call that times out, **When** the stage continues, **Then** the pipeline falls back to the original draft with a warning logged; the run does NOT crash.
5. **Given** the operator configures `story_polish.enabled = false`, **When** the pipeline runs, **Then** the polish stage is skipped entirely and the hiring reviewer sees the writer's draft unchanged.
6. **Given** a draft letter and its polished version, **When** the hiring reviewer evaluates the letter, **Then** it sees the polished version (or the fallback draft) — not both.

---

### User Story 3 - Hiring review catches the seven craft-level failures (Priority: P3)

The existing `hiring_review` stage gains seven new always-on dimensions targeting craft-level failure modes that requirement-matching reviewers miss: `over_constructed_transfer_language`, `forced_analogies`, `defensive_domain_transition`, `overdramatic_aida`, `weak_narrative_coherence`, `low_relevance_impact_claims`, and `machine_like_requirement_mapping`. Each dimension produces a severity (`pass`, `warn`, `error`), a one-sentence rationale, and an evidence span quoted verbatim from the letter when severity ≥ `warn`. The reviewer prompt is rewritten so these dimensions are evaluated consistently and the existing aggregate verdict considers them in its calculus.

**Why this priority**: P3 because the upstream work in US1+US2 reduces the *occurrence* of these failures, but the reviewer is the last-mile detector. Without these dimensions, a polished letter might still slip through with overdramatic AIDA copy or machine-like requirement mapping and ship to the operator unflagged. This closes the loop.

**Independent Test**: Provide a fixture letter containing two clearly-overdramatic AIDA sentences ("Imagine a world where..." and "I am THE engineer for this role!"). Run the hiring reviewer on a canned response. Assert the structured output contains `overdramatic_aida` with severity ≥ `warn` and that the rationale quotes one of the offending sentences.

**Acceptance Scenarios**:

1. **Given** a letter whose opening reads "Although my background is in biomedical science, I want to assure you that my skills transfer to AI infrastructure...", **When** `hiring_review` runs, **Then** `defensive_domain_transition` has severity ≥ `warn` and the rationale quotes the defensive framing.
2. **Given** a letter that says "I am a 10x engineer like a violin virtuoso, fluently playing each tool as a Stradivarius...", **When** `hiring_review` runs, **Then** `forced_analogies` has severity ≥ `warn` and the rationale quotes the offending analogy.
3. **Given** a letter where each paragraph reads as a direct mapping to a requirement ("Requirement: Python expertise. Response: I have 5 years of Python..."), **When** `hiring_review` runs, **Then** `machine_like_requirement_mapping` has severity ≥ `warn` and the rationale names the offending paragraph(s).
4. **Given** an AIDA-mode letter whose opening reads "PICTURE THIS: a world where your inference platform never wakes you at 3am — I'm here to deliver that dream!", **When** `hiring_review` runs, **Then** `overdramatic_aida` has severity ≥ `warn` and the rationale quotes the offending sentence.
5. **Given** a well-crafted letter that passes all seven dimensions, **When** `hiring_review` runs, **Then** all seven new dimensions report `pass` AND the aggregate verdict is unchanged from a pre-feature-013 baseline run on the same letter.
6. **Given** any letter, **When** `hiring_review` runs, **Then** the structured output contains entries for all seven new dimensions (no dimension is silently skipped).

---

### Edge Cases

- **Legacy `WorkflowState` with no `NarrativeStrategy` field** (re-running an old saved state through a new pipeline): the `narrative_strategy` stage produces a fresh strategy and writes it onto the state; subsequent stages consume it normally.
- **No evidence map** (extreme failure mode upstream): `narrative_strategy` produces a minimal strategy with empty `proof_points_to_use`, severity-warn `anti_patterns` noting the missing evidence; pipeline does not crash.
- **`narrative_strategy` LLM call fails or times out**: the stage falls back to a deterministic minimal strategy derived from the role positioning fields and weighted requirements; the run continues with a warning logged.
- **`story_polish` post-check encounters a polished version with fewer evidence anchors than the draft** (e.g., LLM dropped a metric): post-check fails; pipeline falls back to the original draft with a warning.
- **Polish-stage LLM rewrites a number from "1000 jobs/day" to "~1000 jobs/day"**: the deterministic numeric-token extractor treats "1000" and "~1000" as the same numeric token; check passes. The extractor normalises whitespace and surrounding punctuation but is strict on digit sequences.
- **A draft letter contains a quoted phrase from the job description that includes a banned phrase** (e.g., the JD says "world-class"): polish stage must NOT echo the banned phrase even when reordering. The post-check does not enforce banned-phrase reduction (that's the validator's job), so the polish prompt itself must instruct the model on this.
- **AIDA mode + restrained tone guidance conflict in legacy templates** that hardcode dramatic AIDA copy: the restrained guidance from `NarrativeStrategy.tone_guidance` takes precedence over legacy template hardcoded style.
- **`story_polish.enabled = false`**: the stage is bypassed entirely; the hiring reviewer sees the writer's draft.
- **`narrative_strategy.enabled = false`**: the stage produces a minimal deterministic strategy (same as failure fallback) so downstream stages always have a NarrativeStrategy to consume; no consumer needs to handle a missing strategy.
- **A polish-stage diff contains both legitimate flow improvements AND a hallucinated employer name**: post-check fails on the hallucinated employer; fallback to draft; the legitimate flow improvements are lost. This is the intended trade-off — correctness over flow.

## Requirements *(mandatory)*

### Functional Requirements

**NarrativeStrategy creation (US1)**

- **FR-001**: A new `narrative_strategy` pipeline stage MUST run between the evidence-mapping stage and the content-planning stage.
- **FR-002**: The stage MUST produce a `NarrativeStrategy` object with nine required fields: `candidate_story`, `role_story`, `bridge`, `opening_angle`, `proof_points_to_use`, `proof_points_to_avoid`, `transfer_framing_guidance`, `tone_guidance`, `anti_patterns`.
- **FR-003**: `candidate_story` MUST be a 1–3 sentence statement of who the candidate is in this letter (the implicit hiring narrative they bring).
- **FR-004**: `role_story` MUST be a 1–3 sentence statement of what story the company is implicitly inviting candidates to tell, derived from the job description.
- **FR-005**: `bridge` MUST be a 1–3 sentence statement linking the candidate background to the target role explicitly — this is the load-bearing element when the candidate is making a domain transition.
- **FR-006**: `opening_angle` MUST be a single short instruction (≤ 240 chars) telling the writer how to open the letter; it MUST be consistent with the bridge.
- **FR-007**: `proof_points_to_use` MUST be a list of evidence-claim references (from the existing evidence map) that the writer should lean on; each entry MUST trace to an existing `EvidenceItem.claim`.
- **FR-008**: `proof_points_to_avoid` MUST be a list (possibly empty when the strategy is unambiguous, but typically non-empty for domain transitions) of evidence-claim references the writer should deliberately leave out because they dilute the narrative or pull the letter off-message; each entry MUST trace to an existing `EvidenceItem.claim`.
- **FR-009**: `transfer_framing_guidance` MUST be a short paragraph (≤ 600 chars) of concrete instructions for how to frame any domain transition naturally; for non-transition cases it MAY be a short note explaining no special framing is needed.
- **FR-010**: `tone_guidance` MUST be a short paragraph (≤ 600 chars) of tone instructions; when the writing mode is AIDA, it MUST explicitly constrain the tone to a restrained, senior, credible register.
- **FR-011**: `anti_patterns` MUST be a list of short phrasings, openings, or moves the writer must avoid (e.g., "do NOT open with 'Although my background is...' — that is defensive framing").
- **FR-012**: The planner MUST consume the `NarrativeStrategy` when constructing paragraphs; paragraphs whose `evidence_refs` overlap `proof_points_to_avoid` MUST be dropped from the plan.
- **FR-013**: The writer MUST receive the `NarrativeStrategy` as a structured block in its prompt; the writer's opening prose MUST reflect `opening_angle` in substance.
- **FR-014**: When `narrative_strategy.enabled = false` OR the stage's LLM call fails/times out, the stage MUST produce a minimal deterministic strategy derived from the existing inputs (so downstream stages always have a `NarrativeStrategy`); the run MUST NOT crash and a warning MUST be logged.
- **FR-015**: The `NarrativeStrategy` MUST be persisted as an artefact in the run's output directory.

**Story polish (US2)**

- **FR-016**: A new `story_polish` pipeline stage MUST run between the letter-writing stage and the hiring-review stage.
- **FR-017**: The stage MUST take the letter draft as input and produce a polished letter that improves flow, transitions, sentence rhythm, and naturalness.
- **FR-018**: The polish stage MUST NOT introduce new tool names, employer names, numeric tokens, or factual claims that were not present in the draft.
- **FR-019**: A deterministic post-check MUST extract the set of tool names, employer names, and numeric tokens from BOTH the draft and the polished version; if the polished set is not a subset of the draft set, the post-check MUST fail.
- **FR-020**: When the post-check fails, the pipeline MUST fall back to the original draft and log a warning; the run MUST NOT crash.
- **FR-021**: When the polish LLM call fails or times out, the pipeline MUST fall back to the original draft and log a warning; the run MUST NOT crash.
- **FR-022**: The polish stage MUST preserve every evidence-anchor sentence from the draft as a recognisable factual unit (rephrased OK; factually altered NOT OK); the post-check verifies this via numeric-token preservation as a proxy.
- **FR-023**: The polish stage MUST be configurable via `story_polish.enabled`; when set to `false`, the stage is skipped entirely and the hiring reviewer sees the writer's draft.
- **FR-024**: The polished letter (or fallback draft) MUST be what the hiring reviewer evaluates and what gets persisted as the final `letter.md` artefact.
- **FR-025**: The post-check tool-name extractor MUST match whole words case-insensitively from the same tool registry the validation layer uses (feature 012, when shipped) or a built-in seed list otherwise.
- **FR-026**: The post-check numeric-token extractor MUST treat `1000` and `~1000` as the same token (whitespace/punctuation tolerance) but MUST treat `1000` and `1500` as different.

**Hiring review extension (US3)**

- **FR-027**: The `hiring_review` stage's structured output MUST gain seven new always-on dimensions: `over_constructed_transfer_language`, `forced_analogies`, `defensive_domain_transition`, `overdramatic_aida`, `weak_narrative_coherence`, `low_relevance_impact_claims`, `machine_like_requirement_mapping`.
- **FR-028**: Each new dimension MUST report a severity (`pass`, `warn`, `error`), a rationale (≤ 240 chars), and when severity is ≥ `warn`, an evidence span quoted verbatim from the letter.
- **FR-029**: The hiring reviewer's prompt MUST be updated to evaluate the seven new dimensions consistently and to consider them in its aggregate verdict.
- **FR-030**: When `overdramatic_aida` is severity ≥ `warn`, the aggregate verdict MUST be at minimum `needs_minor_revision` (cannot remain `pass`).
- **FR-031**: When `defensive_domain_transition` is severity ≥ `warn`, the aggregate verdict MUST be at minimum `needs_minor_revision`.

**Restrained AIDA mode (cross-cutting)**

- **FR-032**: The AIDA style instructions MUST be updated to emphasise restraint: AIDA is a subtle narrative arc (attention → interest → desire → action), NOT marketing copy; the tone is calm, senior, credible, and institutionally appropriate throughout.
- **FR-033**: When `WritingMode = aida`, the `NarrativeStrategy.tone_guidance` MUST contain explicit instructions constraining AIDA to the restrained register described in FR-032.
- **FR-034**: The `hiring_review.overdramatic_aida` dimension MUST flag AIDA prose that crosses into marketing copy (banned hallmarks: ALL-CAPS attention grabs, exclamation marks in the opening, second-person imperatives in the opening, hyperbolic adjectives like "revolutionary"/"world-class"/"unparalleled" in the opening, etc.).

**Out-of-scope guards (explicit per user request)**

- **FR-035**: This feature MUST NOT change retrieval behaviour (existing evidence-mapping stage is unchanged).
- **FR-036**: This feature MUST NOT change requirement extraction (existing requirements stage is unchanged).
- **FR-037**: This feature MUST NOT change the existing role-positioning production logic inside the content-planning stage; `narrative_strategy` is positioning-aware but does not produce or replace the existing `role_positioning` object.
- **FR-038**: This feature MUST NOT change evidence-mapping behaviour or the evidence-map artefact format.

**Observability**

- **FR-039**: The `narrative_strategy` stage MUST emit its own observability span (Langfuse) and stage tag (MLflow) following existing project conventions.
- **FR-040**: The `story_polish` stage MUST emit its own observability span with attributes for diff size (characters changed) and post-check outcome (pass/fail/fallback/skipped).
- **FR-041**: The hiring-review span MUST attach the seven new dimension severities as attributes.

**Required test surface (FR-042–FR-045 — explicit per user request)**

- **FR-042**: A test MUST cover a domain-transition fixture: given an initial draft that sounds mechanically constructed (e.g., a research-to-industry candidate's draft that opens "Although my background is in biomedical science, my skills transfer to AI infrastructure..."), the polished version MUST keep every numeric token from the draft AND MUST improve the opening to one that reflects `narrative_strategy.opening_angle` (no defensive framing).
- **FR-043**: A test MUST verify that the deterministic post-check fails when a polished letter contains a tool name absent from the draft, and that the pipeline falls back to the original draft.
- **FR-044**: A test MUST verify that an AIDA-mode draft with overdramatic copy (e.g., "PICTURE THIS:" opening) is flagged by `hiring_review.overdramatic_aida` with severity ≥ `warn`.
- **FR-045**: A test MUST verify that the planner drops a paragraph whose evidence references overlap with `narrative_strategy.proof_points_to_avoid`.

### Key Entities *(include if feature involves data)*

- **NarrativeStrategy**: The strategy object produced by the new stage. Attributes: `candidate_story` (string), `role_story` (string), `bridge` (string), `opening_angle` (string), `proof_points_to_use` (list of evidence-claim references), `proof_points_to_avoid` (list of evidence-claim references), `transfer_framing_guidance` (string), `tone_guidance` (string), `anti_patterns` (list of strings). Persisted as `narrative_strategy.json`.
- **StoryPolishOutput**: Wraps the polished letter and the post-check outcome. Attributes: `polished_text` (string, possibly identical to draft if fallback), `post_check_passed` (boolean), `post_check_rationale` (string explaining pass/fail), `tool_names_in_draft` / `tool_names_in_polish` (lists), `numeric_tokens_in_draft` / `numeric_tokens_in_polish` (lists), `employer_names_in_draft` / `employer_names_in_polish` (lists), `used_fallback` (boolean). Persisted as `story_polish_output.json`.
- **HiringReviewOutput (extended)**: Existing model gains a `craft_dimensions` block containing seven dimension entries: `over_constructed_transfer_language`, `forced_analogies`, `defensive_domain_transition`, `overdramatic_aida`, `weak_narrative_coherence`, `low_relevance_impact_claims`, `machine_like_requirement_mapping`. Each entry has `severity`, `rationale`, `evidence_quote`. All existing fields preserved.
- **NarrativePolishConfig**: Per-template / per-run knobs. Attributes: `narrative_strategy_enabled` (boolean, default `true`), `story_polish_enabled` (boolean, default `true`), `restrained_aida` (boolean, default `true`), `tool_registry` (optional list of tool names, overrides default seed).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of runs successfully produce a `NarrativeStrategy` (either from the LLM call or from the deterministic fallback).
- **SC-002**: 100% of runs that successfully invoke `story_polish` produce a `StoryPolishOutput` with `post_check_passed` clearly recorded (true or false with rationale).
- **SC-003**: On a curated fixture corpus of 5 well-crafted polish inputs, the post-check produces zero false-positive failures (no legitimate flow improvement is incorrectly rejected as fact addition).
- **SC-004**: On a curated fixture corpus of 5 LLM-hallucinated polish outputs (each adds a new tool name, employer name, or metric), the post-check produces 100% true-positive failures (every hallucination is caught).
- **SC-005**: 100% of runs that successfully invoke `hiring_review` produce all seven new craft-dimension entries (no dimension silently skipped).
- **SC-006**: On the domain-transition fixture (FR-042), the polished letter preserves 100% of numeric tokens from the draft AND opens with substance from `narrative_strategy.opening_angle` (not defensive framing).
- **SC-007**: On the AIDA-restraint fixture (FR-044), `hiring_review.overdramatic_aida` flags the overdramatic copy in 100% of runs.
- **SC-008**: The end-to-end pipeline runtime increase from this feature is ≤ 30 seconds median on a developer laptop (two new LLM calls, each batched).
- **SC-009**: The aggregate hiring-review verdict does NOT regress on a baseline corpus of 5 already-well-crafted letters (each letter that was `pass` pre-feature-013 remains `pass` post-feature-013).
- **SC-010**: Legacy runs (no `NarrativeStrategy` in saved state, no narrative-polish config in template) complete without raising; the fallback path produces a minimal `NarrativeStrategy` and `story_polish` defaults to enabled.
- **SC-011**: `narrative_strategy.json` and `story_polish_output.json` artefacts are each ≤ 30 KB on a representative run.

## Assumptions

- **Where `narrative_strategy` sits in the pipeline**: It runs as a NEW stage between the existing evidence-mapping stage and the existing content-planning stage. The user's phrase "after role positioning and before content planning" is honoured conceptually — the `narrative_strategy` stage is positioning-aware (it reasons over the same role-positioning inputs the planner uses) but does NOT produce or displace the existing `role_positioning` object that the content-planning stage produces today. This preserves the explicit out-of-scope constraint that role-positioning logic must not change.
- **Reuses existing inputs only**: `narrative_strategy` reads `job_context`, `requirements` (including `requirement_items`), `evidence_map`, and `config`. It does NOT need raw profile data or InternalKnowledge; the privacy boundary established for the writer applies here too.
- **`story_polish` is a separate LLM call**: It uses the same Anthropic client and tracker plumbing as existing stages. It can be disabled via config for cost-sensitive runs.
- **Deterministic post-check is the safety net**: The post-check on `story_polish` is the load-bearing element of US2's correctness contract. It MUST be implemented before the polish LLM call is wired in (TDD).
- **Tool registry seed**: When the feature-012 validation tool registry is not yet present, `story_polish` ships with its own built-in seed list (same seed described in feature 012's spec) plus the project's known stack.
- **Employer-name extraction**: Done via a small built-in heuristic (capitalised multi-word phrases following "at"/"bei"/"with" in the draft) plus the project's known employer list seeded from the candidate's profile. Tests use canned inputs so the heuristic is deterministic.
- **Numeric-token extraction**: Digit-sequence extractor with whitespace + punctuation tolerance ("1000", "~1000", "1,000", "1000+" all map to the same numeric token "1000"). "1000" and "1500" are different.
- **Restrained AIDA = prompt-level**: The AIDA style update is a prompt edit (no new model fields). `NarrativeStrategy.tone_guidance` carries the restrained-tone instruction when mode=aida.
- **Hiring review extension is additive**: Seven new dimensions are added to the existing structured output; existing fields preserved; existing aggregate-verdict logic extended (not replaced).
- **No new CLI surface**: Configuration is read from the template / run config object; no new CLI flags or commands. (A `--no-story-polish` flag could be added in a future feature.)
- **Tests run with canned LLM responses**: All test fixtures use canned planner/writer/polish/reviewer responses; deterministic post-checks need no mocking.
- **Pipeline graph change is contained**: The new graph order is `... → build_evidence_map → narrative_strategy → plan_content → write_letter → story_polish → hiring_review → ...`. Two new nodes, no removed nodes, no reordered existing nodes.
