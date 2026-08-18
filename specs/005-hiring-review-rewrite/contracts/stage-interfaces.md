# Stage Interface Contracts: 005-hiring-review-rewrite

This project has no external API surface — it is a CLI pipeline. Contracts here define the typed inter-stage interfaces (inputs consumed, outputs returned) for the two new stages.

---

## `hiring_review` stage

**Module**: `src/bewerbungs_agent/stages/hiring_review.py`  
**Function signature**: `hiring_review(state: WorkflowState) -> dict[str, Any]`

### Inputs consumed from WorkflowState

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `state.letter_draft` | `LetterDraft \| None` | Yes | Text of the generated letter |
| `state.requirements` | `RequirementExtraction \| None` | Yes | Role requirements from job description |
| `state.config.review_config` | `ReviewConfig` | Yes | Active dimensions and threshold |
| `state.tracker` | `PipelineTracker \| None` | No | If present, logs stage metadata |

### Outputs returned (partial state update dict)

| Key | Type | Condition |
|-----|------|-----------|
| `letter_review` | `LetterReviewReport` | On success |
| *(empty dict)* | — | On LLM failure or `review_config.enabled=False` or missing inputs |

### Failure contract

Any exception from the LLM call is caught. A `warnings.warn()` message is emitted. Returns `{}`. The pipeline continues.

### LLM call inputs

The user message passed to the LLM contains:
- `letter_draft.text`
- `requirements.core_requirement` and all structured requirement fields
- `review_config.dimensions` (list of active evaluation dimensions)

Does NOT include: `knowledge`, `content_plan`, `selected_cv`, or any profile documents.

---

## `targeted_rewrite` stage

**Module**: `src/bewerbungs_agent/stages/targeted_rewrite.py`  
**Function signature**: `targeted_rewrite(state: WorkflowState) -> dict[str, Any]`

### Inputs consumed from WorkflowState

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `state.letter_draft` | `LetterDraft \| None` | Yes | Current letter text (pre-rewrite) |
| `state.letter_review` | `LetterReviewReport \| None` | Yes | Must be non-None to trigger any rewrite |
| `state.requirements` | `RequirementExtraction \| None` | Yes | Role requirements (source of truth for content) |
| `state.config.review_config` | `ReviewConfig` | Yes | Threshold for triggering rewrite |
| `state.tracker` | `PipelineTracker \| None` | No | If present, logs stage metadata |

### Outputs returned (partial state update dict)

| Key | Type | Condition |
|-----|------|-----------|
| `letter_draft` | `LetterDraft` | When at least one section is rewritten |
| *(empty dict)* | — | When `letter_review` is None, `sections_to_rewrite` is empty, or LLM call fails |

### Failure contract

Any exception from the LLM call is caught. A `warnings.warn()` message is emitted. Returns `{}` (original `letter_draft` preserved). The pipeline continues.

### LLM call inputs

The user message passed to the LLM contains:
- `letter_draft.text` (the full original letter)
- `letter_review` (the structured review report as JSON)
- `letter_review.sections_to_rewrite` (explicit list of sections to change)
- `requirements.core_requirement` and all structured fields

Does NOT include: `knowledge`, `content_plan`, `selected_cv`, or any profile documents.

### Invariant

The rewritten letter text MUST NOT contain any fact, skill, employer, project, or result that does not appear in `letter_draft.text` or the `requirements` fields. This is enforced via prompt design and validated in unit tests.

---

## Schema: `hiring_review` LLM tool output

```json
{
  "title": "hiring_review",
  "type": "object",
  "properties": {
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "section_name": { "type": "string" },
          "strengths": { "type": "array", "items": { "type": "string" } },
          "weaknesses": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "text": { "type": "string" },
                "severity": { "type": "string", "enum": ["low", "medium", "high"] },
                "priority_fix": { "type": "string" }
              },
              "required": ["text", "severity", "priority_fix"]
            }
          },
          "assessment": { "type": "string" }
        },
        "required": ["section_name", "strengths", "weaknesses", "assessment"]
      }
    },
    "overall_assessment": { "type": "string" }
  },
  "required": ["sections", "overall_assessment"]
}
```

---

## Schema: `targeted_rewrite` LLM tool output

```json
{
  "title": "targeted_rewrite",
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "description": "The complete cover letter text in Markdown, with weak sections rewritten and strong sections preserved verbatim."
    }
  },
  "required": ["text"]
}
```
