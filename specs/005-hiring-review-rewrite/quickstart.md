# Quickstart: 005-hiring-review-rewrite

## Overview

This feature inserts two new pipeline stages after `write_letter`:

1. **`hiring_review`** — evaluates the generated letter section-by-section from a hiring manager's perspective; produces a `LetterReviewReport` stored in `WorkflowState.letter_review`.
2. **`targeted_rewrite`** — uses the review report to rewrite only sections flagged as weak above the configured threshold; overwrites `WorkflowState.letter_draft`.

Downstream stages (`validate_outputs`, `rewrite_if_needed`) are unchanged and operate on the same `letter_draft` field they always did.

---

## Key integration test scenario

**Setup**:
- A fixture `WorkflowState` with:
  - `letter_draft.text` = a letter with two recognisable sections: a generic "opening" and a specific "relevant experience" section
  - `requirements` = a `RequirementExtraction` with `core_requirement = "Python backend engineer with API design experience"`
  - `config.review_config = ReviewConfig(enabled=True, rewrite_threshold=WeaknessSeverity.medium)`
- A mocked LLM client that returns:
  - **Review call**: a `LetterReviewReport` with the opening section flagged as `severity=high` and the experience section as strength-only
  - **Rewrite call**: a revised letter with only the opening paragraph changed

**Expected outcomes**:
1. `state.letter_review` is populated with a `LetterReviewReport`.
2. `state.letter_review.sections_to_rewrite == ["opening"]` (the flagged section).
3. `state.letter_draft.text` differs from the original (opening was rewritten).
4. The experience section text is identical in the output to the input letter.
5. No content appears in the output that was absent from both the original letter and the requirements text.

---

## Failure / no-op scenarios

**Review LLM fails**:
- `hiring_review` catches the exception, logs a warning, returns `{}` (no `letter_review` update).
- `targeted_rewrite` sees `state.letter_review is None`, returns `{}` (no `letter_draft` update).
- Pipeline continues to `validate_outputs` with the original `letter_draft`.

**All sections are strong**:
- `letter_review.sections_to_rewrite` is empty.
- `targeted_rewrite` returns `{}` (no rewrite performed).

**Review disabled via config**:
- `config.review_config.enabled = False`
- `hiring_review` returns `{}` immediately without making any LLM call.
- `targeted_rewrite` returns `{}` immediately.

---

## Prompt file responsibilities

### `prompts/hiring_reviewer.md` (system prompt)
- Instructs the model to act as an experienced hiring manager for the target role.
- Requires structured output following the review schema.
- Instructs the model to evaluate each section independently across the configured dimensions only.
- Forbids any access to information outside the provided letter and requirements.

### `prompts/targeted_rewriter.md` (system prompt)
- Instructs the model to rewrite only the flagged sections.
- Forbids introduction of any fact not present in the provided letter text or role requirements.
- Requires the output to be a complete letter (full text), not a diff.
- Strong sections must be reproduced verbatim.

---

## Stage module locations

| Module | Path |
|--------|------|
| hiring_review stage | `src/bewerbungs_agent/stages/hiring_review.py` |
| targeted_rewrite stage | `src/bewerbungs_agent/stages/targeted_rewrite.py` |
| Updated workflow | `src/bewerbungs_agent/graph/workflow.py` |
| Updated state | `src/bewerbungs_agent/models/state.py` |
| Updated config | `src/bewerbungs_agent/config/models.py` |
| Updated merge | `src/bewerbungs_agent/utils/merge.py` |

---

## Test module locations

| Test | Path |
|------|------|
| hiring_review unit | `tests/unit/test_hiring_review.py` |
| targeted_rewrite unit | `tests/unit/test_targeted_rewrite.py` |
| config ReviewConfig | `tests/unit/test_config_models.py` (extend existing) |
| integration (full pipeline) | `tests/integration/test_full_run.py` (extend existing) |
