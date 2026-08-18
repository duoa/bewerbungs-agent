# Phase 1 Data Model: Hiring Review with Full Job Context

**Feature**: 009-review-full-job-context
**Date**: 2026-05-26

**No new Pydantic models. No new fields on existing models. No new state attributes.** This feature is purely about reading existing state fields in a new place. The data-model document below catalogues which existing entities the hiring-review stage now reads — for traceability and so the planning phase can confirm the read-only relationship.

---

## 1. Entities the hiring-review stage already read (pre-feature-009)

| Source on `WorkflowState` | Fields read | Used for |
|---|---|---|
| `state.letter_draft` | `text` | Letter under evaluation |
| `state.requirements` | `core_requirement`, `technical_requirements`, `collaboration_requirement`, `domain_requirement`, `optional_requirement` | Structured requirement summary |
| `state.config.review_config` | `enabled`, `dimensions`, `rewrite_threshold` | Configured dimensions, threshold, on/off gate |
| `state.job_context` | `raw_job_text` (from feature 008) | Verbatim job description |
| `state.tracker` | n/a (used only for logging) | MLflow tag emission |

## 2. Entities the hiring-review stage now ADDITIONALLY reads (feature 009)

All of these are pre-existing on `WorkflowState`; this feature only widens the set of attributes read.

| Source on `WorkflowState` | Fields read | Used for |
|---|---|---|
| `state.job_context` | `job_title`, `company_name`, `raw_company_text`, `raw_storyboard_text` | Parsed structured fields shown under `## Parsed Job Context` |
| `state.content_plan` | `sections[*].title`, `sections[*].key_claims`, `role_positioning` (six sub-fields when present), `evidence_map.known_gaps` | Content plan summary block shown under `## Content Plan (read-only context)` |

No field is mutated. No new field is added to any model.

---

## 3. The output schema is unchanged

`LetterReviewReport`, `SectionReview`, `WeaknessEntry` are unchanged. The new evaluation dimension `critical_requirements_underweighted` is identified by a tag prefix inside `WeaknessEntry.text` — exactly the same convention feature 008 established for `role_match`, `opening_alignment`, etc.

```python
# Example weakness produced by the LLM for the new dimension:
WeaknessEntry(
    text="critical_requirements_underweighted: scalable cloud infrastructure is "
         "barely mentioned, only in a subclause; the job ad lists it as a top "
         "responsibility.",
    severity=WeaknessSeverity.medium,
    priority_fix="add a dedicated paragraph on scalable-infrastructure responsibilities "
                 "with one concrete project anchor from the plan.",
)
```

The targeted-rewrite stage already scans weakness text for routing cues, so no downstream consumer change is needed.

---

## 4. Implicit invariants relevant to this feature

| Invariant | Source | Relevance |
|---|---|---|
| Pipeline graph runs `load_job` → … → `plan_content` → `write_letter` → `hiring_review` (per feature 005 wiring) | `graph/workflow.py` | Guarantees that when `hiring_review` runs in the full pipeline, `state.job_context` and `state.content_plan` are populated. |
| `WorkflowState.job_context` is `JobContext \| None`, default `None` | `models/state.py` | Legacy or test-only invocations may have `None`; backward-compat path applies. |
| `WorkflowState.content_plan` is `ContentPlan \| None`, default `None` | `models/state.py` | Same. |
| `JobContext.raw_company_text` and `raw_storyboard_text` are `str \| None` | `models/state.py` | Graceful omission per FR-004. |
| `ContentPlan.role_positioning` is `RolePositioning \| None` (added by feature 008) | `models/state.py` | Plans produced before feature 008 may have `None`. |
| `LetterReviewReport.sections_to_rewrite` is pre-computed by `parse_response` from weaknesses ≥ threshold | `stages/hiring_review.py` | Routing of the new dimension to the rewrite path uses this existing mechanism — no new code. |

---

## 5. State transitions

None. This feature does not introduce a stateful entity. The hiring-review stage continues to be a stateless reader that produces a `LetterReviewReport`. The reader's input set widens; the output's shape is identical.

---

## 6. Backward-compat audit

| Concern | Before feature 009 | After feature 009 | Behaviour |
|---|---|---|---|
| `state.job_context is None` | Prompt builds with `(unavailable …)` placeholder for raw_job_text | Same; structured fields omitted entirely (graceful) | Identical user-visible behaviour |
| `state.content_plan is None` | Prompt builds without any plan block | Same; new plan block omitted entirely (graceful) | Identical user-visible behaviour |
| `state.job_context.raw_company_text is None` | Field was never used | Field continues to be unused — omitted from prompt | No regression |
| `state.content_plan.role_positioning is None` | Field added by feature 008; readers all check for None | Same check applied here | No regression |
| Operator on a starter template that disables `review_config.enabled` | Stage returns `{}` (feature 005 behaviour) | Same; new context is never built because the enabled guard runs first | No regression |
| Operator with `review_config.dimensions=[clarity]` only | Prompt active dims = `clarity` + feature-008 five-tuple = 6 dims | Prompt active dims = `clarity` + feature-008 five-tuple + new sixth = 7 dims | Expected expansion (FR-008/FR-014) |

The only existing test sensitive to this change is `test_hiring_review_prompt_contains_only_active_dimensions` — it asserts the dims string content. Update its expectation to include the new sixth dimension.
