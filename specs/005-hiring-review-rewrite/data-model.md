# Data Model: 005-hiring-review-rewrite

## New Pydantic models (in `src/bewerbungs_agent/models/state.py`)

---

### WeaknessEntry

One identified weakness within a reviewed letter section.

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Description of the weakness |
| `severity` | `"low" \| "medium" \| "high"` | How serious the weakness is |
| `priority_fix` | `str` | Concrete guidance on what to improve |

---

### SectionReview

Assessment of one named section of the cover letter.

| Field | Type | Description |
|-------|------|-------------|
| `section_name` | `str` | LLM-identified name for this section (e.g. "opening", "motivation") |
| `strengths` | `list[str]` | List of strength observations for this section |
| `weaknesses` | `list[WeaknessEntry]` | List of identified weaknesses with severity and fix guidance |
| `assessment` | `str` | One-sentence overall assessment of this section |

---

### LetterReviewReport

Full structured output of the `hiring_review` stage. Stored as `WorkflowState.letter_review`.

| Field | Type | Description |
|-------|------|-------------|
| `sections` | `list[SectionReview]` | Per-section review entries |
| `overall_assessment` | `str` | One-sentence overall assessment of the letter |
| `sections_to_rewrite` | `list[str]` | Section names whose max weakness severity ≥ configured threshold (pre-computed by the review stage) |

---

## New configuration model (in `src/bewerbungs_agent/config/models.py`)

### ReviewDimension (Enum)

| Value | Meaning |
|-------|---------|
| `clarity` | Is the writing clear and easy to understand? |
| `specificity` | Are claims specific and concrete? |
| `credibility` | Are assertions believable and supported? |
| `role_relevance` | Is the content relevant to the target role? |
| `differentiation` | Does the letter stand out from generic applications? |

---

### WeaknessSeverity (Enum)

| Value | Meaning |
|-------|---------|
| `low` | Minor issue, cosmetic improvement only |
| `medium` | Noticeable gap; worth fixing |
| `high` | Significant weakness likely to hurt the application |

---

### ReviewConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Whether the hiring_review + targeted_rewrite stages run at all |
| `dimensions` | `list[ReviewDimension]` | All five | Active evaluation dimensions |
| `rewrite_threshold` | `WeaknessSeverity` | `medium` | Minimum severity that triggers rewriting |

Added to `StarterTemplate` and `MergedConfig` as `review_config: ReviewConfig`. Must be added explicitly to the `base` dict in `merge_config()`.

---

## WorkflowState additions (in `src/bewerbungs_agent/models/state.py`)

| Field | Type | Default | Stage that populates it |
|-------|------|---------|------------------------|
| `letter_review` | `LetterReviewReport \| None` | `None` | `hiring_review` |

`letter_draft` continues to be updated in-place by `targeted_rewrite` (overwrites the `write_letter` output). No new field needed for the rewritten letter.

---

## LangGraph topology change (in `src/bewerbungs_agent/graph/workflow.py`)

Edges removed:
```
write_letter → validate_outputs
```

Edges added:
```
write_letter   → hiring_review
hiring_review  → targeted_rewrite
targeted_rewrite → validate_outputs
```

Unchanged edges:
```
plan_content → write_letter
plan_content → tailor_cv
tailor_cv    → validate_outputs   (fan-in, unchanged)
```

Full updated pipeline order:
```
load_job → extract_requirements → load_profile → select_cv_variant
  → build_evidence_map → plan_content
  → [write_letter → hiring_review → targeted_rewrite]  (one branch)
  → [tailor_cv]                                         (parallel branch)
  → validate_outputs → [conditional: rewrite_if_needed → validate_outputs | END]
```

---

## New prompt files

| Path | Used by |
|------|---------|
| `prompts/hiring_reviewer.md` | `hiring_review` stage (system prompt) |
| `prompts/targeted_rewriter.md` | `targeted_rewrite` stage (system prompt) |
