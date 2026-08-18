# Contract: Hiring-Review Prompt and `build_prompt` Inputs

**Feature**: 009-review-full-job-context
**Date**: 2026-05-26

Two contracts: (a) what `prompts/hiring_reviewer.md` MUST instruct the LLM to do, (b) what `stages/hiring_review.py::build_prompt` MUST place into the constructed user message. The schema contract is unchanged from feature 005/008 and is restated for completeness.

---

## 1. `prompts/hiring_reviewer.md` — required content additions

The reviewer prompt MUST cover the feature 008 content (5 positioning dimensions, severity rubric, quote-not-paraphrase rule, strict constraints) PLUS these additions:

### 1.1 Inputs section addition

The "Inputs" section MUST be updated to list the new context blocks the reviewer will receive:

```text
You receive:
- The complete cover letter text.
- The role requirements extracted from the job description.
- The original job description text (verbatim).
- (NEW) The parsed structured job context: job title, company name, and
  optional company-info and storyboard texts when the operator provided them.
- (NEW) The content plan that produced the letter, as read-only reference:
  the planner's section titles + key claims, and (when present) the role
  positioning summary.
- The list of evaluation dimensions to apply.
```

The "You do NOT receive" line MUST be preserved (no profile, no CV variants, no evidence map). The content plan is read-only context, NOT an evidence-map proxy — passages and full evidence items remain off-limits.

### 1.2 Read-only constraint on content plan

A new strict-constraint bullet:

```text
- The content plan is read-only context for understanding the writer's
  intended framing. Evaluate the LETTER only. Do NOT record weaknesses
  against the plan itself. Do NOT use the plan's evidence references to
  introduce facts that are not already in the letter.
```

### 1.3 Six positioning-specific dimensions (was five)

The "Five positioning-specific dimensions" heading becomes "Six positioning-specific dimensions" and a new bullet is added:

```text
- **critical_requirements_underweighted** — Does the letter meaningfully
  cover the top one or two responsibilities the job ad emphasises? A
  critical requirement gets a weakness when it receives thin treatment
  (one passing mention in a subclause when the ad makes it a top
  responsibility) or no treatment at all. Honest gaps that the planner
  acknowledged in the content plan's `known_gaps` are NOT failures —
  do not flag them.
```

### 1.4 Severity calibration note (extended)

The existing severity-calibration paragraph MUST be extended to mention that `critical_requirements_underweighted` follows the same medium/high threshold logic as the other positioning dimensions: medium when the underweighting would meaningfully reduce competitiveness, high when it would be glaring (e.g., the job ad's top responsibility is entirely absent from the letter).

### 1.5 Tagging convention reaffirmed

The existing tagging instruction ("tag the weakness text with the dimension name") is preserved verbatim and is applied to the new dimension exactly as to the other five. The downstream `targeted_rewrite` stage performs simple substring scans on weakness text to route fixes; no code-side schema change is needed.

---

## 2. `stages/hiring_review.py::build_prompt` — required input additions

The constructed user message MUST be organised as the following ordered blocks:

```
Review the following cover letter from the perspective of a hiring manager.

## Original Job Description (verbatim)
<state.job_context.raw_job_text>   ← unchanged from feature 008

## Parsed Job Context                ← NEW (feature 009)
- job_title: <value>                 ← omit if None
- company_name: <value>              ← omit if None
- company_info: <raw_company_text>   ← omit if None
- storyboard: <raw_storyboard_text>  ← omit if None
(omit the entire block if state.job_context is None OR all fields are None)

## Role Requirements
<existing requirements block>        ← unchanged

## Content Plan (read-only context — evaluate only the letter)  ← NEW (feature 009)
Sections:
- <title>: ["<claim 1>", "<claim 2>", ...]
...

Role Positioning:
- primary_role_family: <value>       ← omit Role Positioning block if role_positioning is None
- primary_selling_point: <value>
- secondary_selling_points: [<list>] ← omit if empty
- opening_angle: <value>
- topics_to_emphasise: [<list>]      ← omit if empty
- topics_to_deemphasise: [<list>]    ← omit if empty

Known gaps acknowledged in the plan:
- <gap text>                          ← include only when known_gaps is non-empty
(omit the entire Content Plan block when state.content_plan is None)

## Evaluation Dimensions (evaluate ONLY these)
<comma-joined list>                  ← UPDATED: now contains 6 always-on positioning dimensions

## Cover Letter
<state.letter_draft.text>            ← unchanged

Identify each section ... For each weakness on a positioning dimension
(role_match, opening_alignment, secondary_topic_dominance, tool_density,
overclaiming, critical_requirements_underweighted), tag the weakness text
with the dimension name (e.g. 'role_match: ...').
```

### Graceful-omission rules (FR-003, FR-004, FR-005)

- `state.job_context is None` → "Original Job Description" block uses the feature 008 fallback `(job description unavailable — base evaluation on requirements only)`; "Parsed Job Context" block is OMITTED entirely.
- `state.job_context` is set but ALL optional structured fields are None → "Parsed Job Context" block is OMITTED entirely (only job_title and company_name belong here normally; raw_company_text and raw_storyboard_text are optional).
- An individual structured field is None → that single line is omitted; the block still appears with the populated fields.
- `state.content_plan is None` → "Content Plan" block is OMITTED entirely.
- `state.content_plan.role_positioning is None` → the "Role Positioning" sub-section is OMITTED; the "Sections" sub-section still appears.
- `state.content_plan.evidence_map.known_gaps` is empty → the "Known gaps acknowledged in the plan" sub-section is OMITTED.

### `_POSITIONING_DIMENSIONS` constant update

```python
_POSITIONING_DIMENSIONS: tuple[str, ...] = (
    "role_match",
    "opening_alignment",
    "secondary_topic_dominance",
    "tool_density",
    "overclaiming",
    "critical_requirements_underweighted",  # NEW (feature 009)
)
```

The build_prompt logic that unions `configured_dims + always-on dimensions` is unchanged — it picks up the new tuple member automatically.

---

## 3. Output schema (unchanged)

`LetterReviewReport`, `SectionReview`, `WeaknessEntry` are unchanged. `parse_response(data, threshold)` continues to:

1. Iterate over `data["sections"]`.
2. Build a `SectionReview` per section with all weaknesses.
3. Compute `sections_to_rewrite` as the set of section names whose maximum weakness severity meets or exceeds the threshold.

A `critical_requirements_underweighted: …` weakness at severity ≥ threshold routes its section into `sections_to_rewrite` exactly like every other weakness — the routing is severity-driven, not dimension-driven. No parser change needed.

---

## 4. Non-interference contract

Same as feature 008's contract restated:

- `jobagent run` exit codes unchanged.
- MLflow run-level params and metrics unchanged in NAMES; per-stage `prompt_hash` tag VALUE for `hiring_reviewer` flips because the prompt file changes (correct, intended signal).
- Langfuse trace topology unchanged; `prompt_content_hash` metadata field VALUE flips for the `hiring_review` span only.
- Langfuse prompt-registry: next `jobagent prompts sync` reports `1 created, 9 unchanged` — exactly the `bewerbungs-agent/hiring_reviewer` prompt is bumped.
- Pipeline graph topology, the set of output artefacts, the writer/planner/targeted_rewrite/validate stages: all unchanged.

---

## 5. Test surface (mapped from the contract)

| Behaviour to test | Test name (suggested) | File |
|---|---|---|
| Prompt includes raw job description + parsed structured fields | `test_prompt_includes_parsed_job_context_structured_fields` | `tests/unit/test_hiring_review.py` |
| Prompt omits optional structured fields when None | `test_prompt_omits_absent_optional_fields_gracefully` | same |
| Prompt includes content plan summary block | `test_prompt_includes_content_plan_summary` | same |
| Prompt includes role_positioning sub-block when present | `test_prompt_includes_role_positioning_when_present` | same |
| Prompt builds cleanly when `job_context` is None | `test_prompt_builds_when_job_context_is_none` | same |
| Prompt builds cleanly when `content_plan` is None | `test_prompt_builds_when_content_plan_is_none` | same |
| Active-dims list includes `critical_requirements_underweighted` | `test_active_dimensions_includes_critical_requirements_underweighted` | same |
| Canned review with high-severity wrong-opening lands "opening" in sections_to_rewrite | `test_review_flags_secondary_domain_opening_with_high_severity` | same |
| Canned review with `critical_requirements_underweighted` routes section to rewrite | `test_critical_requirements_underweighted_routes_to_rewrite` | same |
| Existing `test_hiring_review_prompt_contains_only_active_dimensions` expectation updated for 6 always-on dims | n/a — edit existing test | same |

The MLflow/Langfuse non-interference invariant (SC-009) is verified by the existing 230-test suite continuing to pass.
