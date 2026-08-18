# Implementation Plan: Hiring-Manager Review and Targeted Rewrite Stage

**Branch**: `005-hiring-review-rewrite` | **Date**: 2026-04-15 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/005-hiring-review-rewrite/spec.md`

## Summary

Add two new LangGraph pipeline stages after `write_letter`: a `hiring_review` stage that evaluates the generated letter section-by-section from a hiring manager's perspective and produces a structured `LetterReviewReport`, and a `targeted_rewrite` stage that rewrites only sections flagged as weak above a severity threshold while preserving all others verbatim. Both stages are non-blocking (failures return original letter), read only the generated letter and extracted role requirements (not the profile), and integrate with the Feature 004 thinking/tracking infrastructure.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: anthropic SDK ≥ 0.25, pydantic v2, langgraph 0.2+, mlflow ≥ 2.12 (optional, for tracking)  
**Storage**: Local files only (prompts/ directory for new prompt files)  
**Testing**: pytest, TDD (tests written before implementation)  
**Target Platform**: macOS / Linux (same as existing pipeline)  
**Project Type**: CLI pipeline (internal Python modules only; no external API surface)  
**Performance Goals**: Review + rewrite add ≤ 2 LLM round-trips to a run; no latency targets beyond that  
**Constraints**: Must not change LangGraph topology for existing stages; must not break existing tests; `extra="forbid"` on MergedConfig — all new fields must be declared explicitly  
**Scale/Scope**: Same as existing pipeline (single-run, local execution)

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Factual Integrity | ✅ Pass | Both stages read only letter_draft + requirements; no profile access. Rewrite prompt explicitly forbids fact invention. |
| II. Approved Sources Only | ✅ Pass | hiring_review and targeted_rewrite read no approved sources directly — only the structured pipeline outputs from prior stages. |
| III. Structured-Before-Generative | ✅ Pass | Review produces structured LetterReviewReport before rewrite generates revised prose. The existing pipeline order is preserved; new stages slot in after step 6 (generate outputs) and before step 7 (validate). |
| IV. Separation of Concerns | ✅ Pass | Review and rewrite are separate stages. Review does not generate prose; rewrite does not re-evaluate quality. |
| V. Deterministic Interfaces & Typed State | ✅ Pass | All new models are Pydantic BaseModel. New fields declared in WorkflowState and MergedConfig with full type annotations. |
| VI. Test Coverage | ✅ Pass | TDD: tests written first. Unit tests for both stages + ReviewConfig; integration test extension. |

## Project Structure

### Documentation (this feature)

```text
specs/005-hiring-review-rewrite/
├── plan.md              # This file
├── research.md          # Decisions and alternatives
├── data-model.md        # Data entities and topology
├── quickstart.md        # Integration test scenarios
├── contracts/
│   └── stage-interfaces.md  # Typed stage I/O contracts + LLM schemas
└── tasks.md             # Phase 2 output (/speckit.tasks — not yet created)
```

### Source Code changes

```text
src/bewerbungs_agent/
├── config/
│   └── models.py                    # + ReviewDimension, WeaknessSeverity, ReviewConfig
│                                    # + review_config field on StarterTemplate + MergedConfig
├── models/
│   └── state.py                     # + WeaknessEntry, SectionReview, LetterReviewReport
│                                    # + letter_review field on WorkflowState
├── stages/
│   ├── hiring_review.py             # NEW: hiring_review stage
│   └── targeted_rewrite.py          # NEW: targeted_rewrite stage (note: different from existing rewrite.py)
│                                    # (existing rewrite.py handles validation-failure rewrites; unchanged)
├── graph/
│   └── workflow.py                  # Edge changes only; two new nodes registered
└── utils/
    └── merge.py                     # review_config added to base dict

prompts/
├── hiring_reviewer.md               # NEW: system prompt for hiring_review stage
└── targeted_rewriter.md             # NEW: system prompt for targeted_rewrite stage

tests/
├── unit/
│   ├── test_hiring_review.py        # NEW
│   ├── test_targeted_rewrite.py     # NEW
│   └── test_config_models.py        # EXTEND: ReviewConfig parsing
└── integration/
    └── test_full_run.py             # EXTEND: full pipeline with review+rewrite stages
```

**Structure Decision**: Single-project layout (existing). No new packages or directories beyond `stages/` (two new modules) and `prompts/` (two new files).

## Implementation Details

### 1. Config additions (`config/models.py`)

```python
class ReviewDimension(str, Enum):
    clarity = "clarity"
    specificity = "specificity"
    credibility = "credibility"
    role_relevance = "role_relevance"
    differentiation = "differentiation"

class WeaknessSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

class ReviewConfig(BaseModel):
    enabled: bool = True
    dimensions: list[ReviewDimension] = Field(
        default_factory=lambda: list(ReviewDimension)
    )
    rewrite_threshold: WeaknessSeverity = WeaknessSeverity.medium
```

Added to `StarterTemplate` and `MergedConfig`:
```python
review_config: ReviewConfig = Field(default_factory=ReviewConfig)
```

### 2. State additions (`models/state.py`)

```python
class WeaknessEntry(BaseModel):
    text: str
    severity: WeaknessSeverity
    priority_fix: str

class SectionReview(BaseModel):
    section_name: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[WeaknessEntry] = Field(default_factory=list)
    assessment: str

class LetterReviewReport(BaseModel):
    sections: list[SectionReview] = Field(default_factory=list)
    overall_assessment: str
    sections_to_rewrite: list[str] = Field(default_factory=list)
    # ^ pre-computed by hiring_review stage based on threshold
```

Added to `WorkflowState`:
```python
letter_review: LetterReviewReport | None = None
```

### 3. `hiring_review` stage (`stages/hiring_review.py`)

- Checks `state.config.review_config.enabled`; if False, returns `{}`.
- Checks `state.letter_draft` and `state.requirements`; if either is None, returns `{}`.
- Builds a user message containing: letter text, requirements text, active dimensions list.
- Calls LLM with `_REVIEW_SCHEMA` (structured tool-use).
- Parses response into `LetterReviewReport`; pre-computes `sections_to_rewrite` based on threshold.
- All LLM calls wrapped in `try/except Exception`; on failure: `warnings.warn()`, return `{}`.
- Logs to MLflow tracker if `state.tracker` is set.

### 4. `targeted_rewrite` stage (`stages/targeted_rewrite.py`)

- Checks `state.letter_review`; if None or `sections_to_rewrite` is empty, returns `{}`.
- Builds user message containing: full letter text, structured review JSON, requirements text, list of sections to rewrite.
- Calls LLM with `_REWRITE_SCHEMA`.
- Parses response text into a new `LetterDraft` (preserves `mode` and `content_plan_hash` from original).
- All LLM calls wrapped in `try/except Exception`; on failure: `warnings.warn()`, return `{}`.
- Logs to MLflow tracker if `state.tracker` is set.

### 5. Workflow topology (`graph/workflow.py`)

Remove edge:
```python
graph.add_edge("write_letter", "validate_outputs")  # REMOVED
```

Add:
```python
graph.add_node("hiring_review", hiring_review_fn)
graph.add_node("targeted_rewrite", targeted_rewrite_fn)
graph.add_edge("write_letter", "hiring_review")
graph.add_edge("hiring_review", "targeted_rewrite")
graph.add_edge("targeted_rewrite", "validate_outputs")
```

### 6. `merge_config()` addition (`utils/merge.py`)

```python
"review_config": template.review_config,  # MUST be explicit — Pydantic does not auto-propagate
```

### 7. Prompt files

`prompts/hiring_reviewer.md` — instructs the model to act as an experienced hiring manager, evaluate each section across the specified dimensions only, and return a structured assessment. Explicitly forbids access to information outside the provided letter and requirements.

`prompts/targeted_rewriter.md` — instructs the model to rewrite only the listed sections, reproduce strong sections verbatim, and not introduce any fact absent from the provided letter text or role requirements. Requires complete letter output.

## Complexity Tracking

No constitution violations. No complexity justification required.
