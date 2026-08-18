# Research: 005-hiring-review-rewrite

## Decision 1: Section identification strategy

**Decision**: LLM-determined dynamically — the review LLM identifies section boundaries and assigns names itself.

**Rationale**: The letter is unstructured Markdown prose. A fixed canonical taxonomy (e.g., opening/motivation/experience/closing) would need to match the actual letter structure produced by `write_letter`, which varies by template and mode. Letting the reviewer identify sections naturally avoids a brittle name-matching layer. For the first iteration this is the lowest-friction approach; a fixed taxonomy can be introduced later if consistency across runs becomes important.

**Alternatives considered**:
- Markdown headings (`##`) — rejected because the letter may not use headings consistently; style is template-dependent.
- Fixed taxonomy hardcoded — rejected because it would require maintaining a mapping between taxonomy names and letter structure, and breaks when templates produce different section orderings.

---

## Decision 2: State field ownership for rewrite output

**Decision**: The `targeted_rewrite` stage overwrites `letter_draft` in-place. A new field `letter_review: LetterReviewReport | None` is added to `WorkflowState` to store the review output.

**Rationale**: `validate_outputs` already reads `letter_draft`. Overwriting it means validation works unchanged with zero modifications to the validate stage. The review report is preserved in `letter_review` for auditing and MLflow logging.

**Alternatives considered**:
- Separate `letter_reviewed: LetterDraft` field — rejected because it would require the validate stage to know which field to check, breaking the existing interface.
- Replacing `letter_draft` entirely at the state level — same as chosen approach; just semantic framing.

---

## Decision 3: Inputs to the targeted rewrite stage

**Decision**: The rewrite stage reads only `letter_draft.text` (the generated letter), `requirements` (the structured extraction from the job description), and `letter_review` (the structured review report). It does NOT read `content_plan`, `knowledge`, or any profile documents.

**Rationale**: Per FR-007 and the user's clarification ("reads only generated letter plus role requirements, not the full raw profile"). The content plan was already consumed by `write_letter` and is encoded in the letter text; the rewrite stage refines the letter, not the plan. Limiting inputs enforces the factual-integrity principle mechanically.

**Alternatives considered**:
- Passing `content_plan` as context — rejected (would allow fabrication from plan facts not in the letter); also unnecessary since the review output already identifies specific issues.
- Passing `knowledge` — explicitly rejected by user.

---

## Decision 4: Prompt files

**Decision**: Two new prompt files in `prompts/`: `hiring_reviewer.md` (system-level instructions for the review LLM) and `targeted_rewriter.md` (system-level instructions for the rewrite LLM). Stage-specific content is built inline in each stage module; shared instructions go in the prompt files.

**Rationale**: Consistent with the existing pattern where all stages use `load_prompt()` for shared system instructions. Keeps prompts version-controlled and diff-able.

**Alternatives considered**:
- Inline prompts in stage modules — rejected for consistency and traceability.

---

## Decision 5: LangGraph topology change

**Decision**: Remove the direct `write_letter → validate_outputs` edge. Insert two new nodes between them:

```
write_letter → hiring_review → targeted_rewrite → validate_outputs
tailor_cv    →                                  → validate_outputs  (fan-in unchanged)
```

**Rationale**: The `targeted_rewrite` stage produces the final `letter_draft` that validation should inspect. `tailor_cv` runs in parallel to `write_letter` (plan_content fan-out), so its edge to `validate_outputs` is unaffected. LangGraph's StateGraph supports this fan-in pattern natively.

**Alternatives considered**:
- Separate graph branch or sub-graph — rejected (over-engineering for two stages).
- Running hiring_review and tailor_cv in parallel — rejected; hiring_review depends on write_letter output, not plan_content.

---

## Decision 6: Failure handling

**Decision**: If the hiring_review LLM call raises any exception, the stage catches it, logs a warning, and returns an empty dict (no `letter_review` update). The `targeted_rewrite` stage checks if `letter_review is None` and short-circuits with an empty dict (original `letter_draft` preserved). The pipeline continues to `validate_outputs` unchanged.

**Rationale**: Per FR-009. Non-blocking is the governing principle across all stages (pattern established in Feature 004 for MLflow tracking; extended here for review/rewrite).

---

## Decision 7: Configuration extension

**Decision**: Add a `ReviewConfig` model to `config/models.py`. Add a `review_config: ReviewConfig` field to both `StarterTemplate` and `MergedConfig`. Add it explicitly to the `base` dict in `merge_config()` (mandatory — see Feature 004 merge_config bug).

**Rationale**: Per FR-010. Enables operators to restrict dimensions and raise the rewrite threshold without code changes.

**Alternatives considered**:
- Separate YAML file for review config — rejected (over-engineering; the existing override mechanism covers this).
