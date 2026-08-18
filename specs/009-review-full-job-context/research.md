# Phase 0 Research: Hiring Review with Full Job Context

**Feature**: 009-review-full-job-context
**Date**: 2026-05-26

Resolves implementation-relevant unknowns. Does not re-litigate scope decisions in `spec.md > Assumptions`.

---

## R1 — Is a new constructor argument or input model needed?

**Decision**: No. The hiring-review stage already receives `WorkflowState`, and `WorkflowState` already carries `job_context` (populated by `load_job`) and `content_plan` (populated by `plan_content`). The implementation reads the existing state fields directly inside `build_prompt`. No new constructor arg, no new dataclass, no plumbing change in the LangGraph wiring.

**Rationale**:
- Verified by inspection: `stages/hiring_review.py::build_prompt(state)` already accesses `state.letter_draft`, `state.requirements`, `state.config.review_config`, and (since feature 008) `state.job_context.raw_job_text`. Reading three additional attributes from the same state object is a one-function change.
- The user's spec language ("Add full_job_description and optional job_context to the hiring_review input model or stage call") allows either path; the smaller path (reading state) is consistent with how every other stage in the codebase works.
- Avoids the `merge.py`/`extra="forbid"` propagation gotcha entirely because nothing in `MergedConfig` changes.

**Alternatives considered**:
- Add a typed `HiringReviewInput` dataclass that explicitly bundles the inputs: rejected — adds a new model for no behavioural benefit; the state IS the input dataclass.
- Pass the new context via a config override: rejected — these are runtime data, not configuration.

---

## R2 — What "structured summary" of the content plan goes in the prompt?

**Decision**: A compact text rendering of: each section's `title` + first 3 entries of `key_claims`, plus (when present) the `role_positioning` block (primary_role_family, primary_selling_point, secondary_selling_points, opening_angle, topics_to_emphasise, topics_to_deemphasise). Verbatim claim wording is included (it's small). Raw evidence passages are NOT included — the reviewer doesn't need them to spot drift.

**Rationale**:
- Spec FR-006 explicitly allows omitting passages and notes "verbatim claim wording from `evidence_refs` MAY appear".
- A full `model_dump_json` of `ContentPlan` would dump every evidence_map item with its passage text — that's the body of the candidate's CV and projects, which (a) inflates the prompt token cost noticeably and (b) doesn't help the reviewer judge the LETTER.
- The role_positioning block IS load-bearing: it tells the reviewer what opening the plan intended, so any plan-vs-letter drift is callable out concretely.

**Format example** (what lands in the prompt):

```
## Content Plan (read-only context — evaluate only the letter)

Sections:
- role_fit: ["Built scalable Python ML platforms", "Owned inference SLOs"]
- platform_experience: ["Operated EKS fleets", "Designed cost controls"]
- working_style: ["Mentored mid-level engineers"]

Role Positioning:
- primary_role_family: AI/ML platform engineering
- primary_selling_point: Built scalable Python ML inference platforms for engineering teams.
- secondary_selling_points: ["Biomedical-ML modelling experience as adjacent context"]
- opening_angle: Lead with infrastructure-builder identity; biomedical briefly.
- topics_to_emphasise: ["platform reliability", "AI/ML inference scaling"]
- topics_to_deemphasise: ["biomedical domain depth"]
```

**Alternatives considered**:
- Full `model_dump_json` dump: rejected on size grounds (see above).
- Only section titles, no key_claims: rejected — the reviewer needs the claims to spot drift between "plan said X" and "letter does Y".
- Compress to a one-line summary per section: rejected — too lossy; key_claims are typically 3–6 words each.

---

## R3 — Where do parsed `job_context` structured fields go in the prompt?

**Decision**: A new `## Parsed Job Context` block immediately after the `## Original Job Description (verbatim)` block from feature 008, and before the `## Role Requirements` block. Only populated fields appear (FR-004 — graceful omission rule). Order: job_title, company_name, raw_company_text, raw_storyboard_text.

**Rationale**:
- Adjacency to the raw job description means the reviewer reads source-of-truth content together, then sees the agent's interpretation (requirement extraction) afterwards.
- Graceful omission satisfies the "stay focused" goal — empty placeholders waste tokens and confuse the LLM about what's optional.
- `raw_company_text` and `raw_storyboard_text` may be long; if so, the operator already opted to provide them — passing them to the reviewer mirrors what the planner sees and avoids the situation where the reviewer judges role match without knowing the company context the writer worked from.

**Alternatives considered**:
- Inline the structured fields under the same heading as the raw job text: rejected — operators reading the trace need to distinguish raw-from-disk vs. parsed-by-loader.
- Always emit "(none)" for absent fields: rejected — FR-004 specifically forbids this.

---

## R4 — Is `critical_requirements_underweighted` truly additive or could it overlap with feature 008's dimensions?

**Decision**: Truly additive. The five 008 dimensions evaluate STRUCTURE (role match, opening alignment, secondary dominance, tool density, overclaiming). The new dimension evaluates COVERAGE (does the letter actually address a top job requirement, or is it skipped/buried). A letter could pass all five 008 dimensions while still underweighting a critical requirement — e.g., a perfectly-opened infrastructure-first letter that never discusses on-call rotation or efficient compute when those are core to the job.

**Rationale**:
- Empirical evidence from feature 008's smoke runs (the AI/ML infra fixture): the planner does well at picking the right primary role family, the writer does well at opening with infrastructure framing, but middle paragraphs sometimes coast on Python generalities and skip specific top responsibilities the ad emphasises (e.g., "co-own incidents end-to-end"). That's exactly the new dimension.
- Reusing one of the existing 008 dimensions to cover this would be semantically wrong: `role_match` is about framing, not coverage; `opening_alignment` is only about the first paragraph; `secondary_topic_dominance` is the opposite direction.
- Adding a sixth dimension keeps the routing tag clean (`critical_requirements_underweighted: …`) so downstream targeted_rewrite knows exactly which corrective rewrite to apply.

**Alternatives considered**:
- Stretch the meaning of `role_match` to include coverage: rejected — muddies semantics, harder for the LLM to apply consistently.
- Make the new dimension opt-in via `review_config.dimensions`: rejected — spec FR-014 specifies always-on; gates the value of the feature behind a config flag operators won't know to set.

---

## R5 — Where does the LLM get the cue that the new dimension is always-on?

**Decision**: Two places. (a) The dimension name is added to the always-on tuple `_POSITIONING_DIMENSIONS` in `stages/hiring_review.py` (currently length 5, becomes length 6); `build_prompt` already unions configured + always-on dims into the prompt's `## Evaluation Dimensions` list. (b) `prompts/hiring_reviewer.md` adds a new bullet under "Six positioning-specific dimensions" describing the dimension's failure criterion and the `critical_requirements_underweighted: …` text-tagging convention.

**Rationale**:
- Two-channel: the structural channel (dimension name in the dimensions list) tells the LLM what's enabled; the natural-language channel (prompt file) tells the LLM what the dimension means.
- Matches exactly how feature 008's five dimensions are wired today.
- The constant is named `_POSITIONING_DIMENSIONS` but semantically the sixth dimension is closer to "coverage" than "positioning". The constant name stays the same to avoid a wider rename; the docstring is updated to clarify the broader scope.

**Alternatives considered**:
- Rename the tuple to `_ALWAYS_ON_DIMENSIONS`: rejected — broader rename for cosmetic gain; out of scope.

---

## R6 — How is the "honest gap" carve-out (FR-011) enforced?

**Decision**: Two-layer enforcement, both via the prompt.
1. The `## Content Plan` block exposes `evidence_map.known_gaps` (when present) so the reviewer can see acknowledged gaps directly.
2. The reviewer prompt is updated with an explicit instruction: "Do NOT flag a `critical_requirements_underweighted` weakness when the gap is openly acknowledged in `known_gaps` — those are honest absences the planner already accepted."

No code-side enforcement is added. The reviewer is an LLM with reasoning ability; making the carve-out explicit in the prompt is the right level of intervention. If false positives are observed in practice, a deterministic check in `parse_response` could be added in a later feature.

**Rationale**:
- Spec FR-011 mandates the carve-out exists, not the mechanism. Prompt-level enforcement is the lightest-weight option and matches the "context-passing feature" framing.
- A code-side filter would need to match weakness text against `known_gaps` strings — fragile across phrasings.
- The content plan exposure (US2) already puts known_gaps in the reviewer's reading frame; the prompt instruction closes the loop.

**Alternatives considered**:
- Strip `critical_requirements_underweighted` weaknesses that mention any term from `known_gaps`: rejected as too brittle.
- Add a separate post-parse filter step: rejected — out of scope, prompt instruction is sufficient for v1.

---

## R7 — Backward-compat: how do existing tests stay green?

**Decision**: Three precautions.
1. The new prompt blocks only fire when their respective state fields exist (`state.job_context` and `state.content_plan` independently gated; either may be None).
2. The existing `hiring_review` test `test_hiring_review_prompt_contains_only_active_dimensions` asserts the dims string. We update it to also allow the new sixth dimension (it's expected to appear).
3. The existing integration test in `test_full_run.py` runs the full pipeline; since feature 008 already added `raw_job_text` and 5 dims, adding 1 dim + 2 optional context blocks is purely additive. Integration test stays green without modification.

**Rationale**:
- The failing test from feature 008 (`test_hiring_review_prompt_contains_only_active_dimensions`) is the one most likely to be sensitive to this change. Update is a one-line change to expand the expected list.
- Test fixtures that don't populate `job_context` or `content_plan` (most unit tests) automatically hit the graceful-omission paths — backward-compat coverage is "free".

**Alternatives considered**:
- Hide the new context behind a feature flag: rejected — fragmentation; once shipped, always on.

---

## R8 — How will Langfuse prompt-registry behave on the next `prompts sync`?

**Decision**: Exactly one new version of `bewerbungs-agent/hiring_reviewer` will be created. The other 9 prompts will report `unchanged` (their content hashes don't change). Operator runs `jobagent prompts sync --label staging` once after merging this feature.

**Rationale**:
- Feature 007's content-hash-in-config idempotence check (verified by 30+ tests) means only edited files create new versions.
- Confirmed semantically: this feature only edits `hiring_reviewer.md`.

**Alternatives considered**:
- None — this is determined by the feature 007 design.

---

## R9 — Test surface mapped to spec FRs

| Test | FR(s) covered | File |
|---|---|---|
| `test_prompt_includes_parsed_job_context_structured_fields` | FR-001, FR-002, FR-004, FR-020, SC-001, SC-002 | `tests/unit/test_hiring_review.py` |
| `test_prompt_includes_content_plan_summary` | FR-005, FR-006, FR-020, SC-003 | same |
| `test_prompt_includes_role_positioning_block_when_present` | FR-006, SC-003 | same |
| `test_prompt_builds_when_job_context_is_none` | FR-003, FR-021, SC-004 | same |
| `test_prompt_builds_when_content_plan_is_none` | FR-005, FR-022, SC-005 | same |
| `test_prompt_active_dimensions_list_includes_critical_requirements_underweighted` | FR-008, FR-024, SC-006 | same |
| `test_review_flags_secondary_domain_opening_with_high_severity` | FR-023, SC-008 | same |
| `test_review_routes_critical_requirements_underweighted_to_rewrite` | FR-009, FR-010, FR-025, SC-007 | same |
| `test_existing_dimensions_assertion_still_holds_with_six_dims` | non-regression | same (extends `test_hiring_review_prompt_contains_only_active_dimensions`) |

The MLflow/Langfuse non-interference invariant (SC-009) is structurally guaranteed (no schema or trace-shape changes) — the existing 230-test suite continuing to pass IS the proof.

---

## Open questions resolved

- "Does Pydantic round-trip through LangGraph break if a state field is None?" — No; LangGraph passes partial dicts via `model_copy(update=...)`; None handling is at our `build_prompt` reading site, not at the framework level.
- "Will the new prompt blocks blow out the Anthropic token budget?" — No; the parsed `job_context` fields are typically <200 chars each; the content-plan summary is a structured but compact representation. Estimated total addition: ~800 tokens, well within Claude Sonnet's input budget for this pipeline.
- "Does the existing `_POSITIONING_DIMENSIONS` tuple addition affect feature 008 tests?" — Yes, one test does a substring assertion over the dimensions string and will need a small expectation update; the feature 008 wiring otherwise stays correct.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
