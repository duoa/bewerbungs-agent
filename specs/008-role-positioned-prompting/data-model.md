# Phase 1 Data Model: Role-Positioned Prompting

**Feature**: 008-role-positioned-prompting
**Date**: 2026-05-13

Two new Pydantic models. One additive optional field on `ContentPlan`. One additive field on `StarterTemplate` and `MergedConfig`. No other state-model changes. No prompt-only-feature would normally have a data-model section, but the two small typed additions need to be specified precisely so the planner's auto-generated tool schema is correct and the writer/reviewer can consume the new fields reliably.

---

## 1. `RolePositioning` — new sub-object on `ContentPlan`

Lives in `src/bewerbungs_agent/models/state.py`.

```python
class RolePositioning(BaseModel):
    """The planner's explicit decision about how to frame the cover letter.

    Derived from the job description + extracted requirements. Informs the
    writer's opening, paragraph order, and emphasis decisions. Evaluated by
    the hiring-review stage against the full job description text.
    """
    model_config = ConfigDict(extra="forbid")

    primary_role_family: str                       # e.g., "AI/ML platform engineering"
    primary_selling_point: str                     # one-sentence framing of the candidate's main match
    secondary_selling_points: list[str] = Field(default_factory=list)  # may be empty
    topics_to_emphasise: list[str] = Field(default_factory=list)
    topics_to_deemphasise: list[str] = Field(default_factory=list)     # may be empty
    opening_angle: str                             # short instruction on how the letter should open
```

**Validation rules**:
- `primary_role_family`, `primary_selling_point`, `opening_angle` are required non-empty strings (Pydantic default validation for non-Optional str types).
- The four list fields default to empty; the planner emits them in every response, possibly empty.
- `extra="forbid"` stops the model from drifting on a typo.

**No min/max length constraints**: the prompt instructs short forms, but the LLM may produce slightly longer text and we shouldn't reject parses on prose length.

---

## 2. Addition to `ContentPlan`

Lives in the same file. Only the new field is shown.

```python
class ContentPlan(BaseModel):
    # ... existing fields unchanged ...
    role_positioning: RolePositioning | None = None
```

**Why optional**:
- Backward compatibility: any existing JSON content-plan artefact written by a previous run can still load — the field defaults to None.
- The planner prompt makes the field behaviourally required (the LLM is instructed to fill it), so a real run produces a non-None value. The Optional typing is a parse-robustness measure, not a semantic loosening.

**Field placement**: appended at the end of the model so existing serialisation order is unchanged.

---

## 3. `WriterRules` — new sub-object on `StarterTemplate` and `MergedConfig`

Lives in `src/bewerbungs_agent/config/models.py`.

```python
class WriterRules(BaseModel):
    """Per-template constraints on writer prose.

    Enforced primarily by prompt instruction; the hiring-review stage
    catches violations and routes them through targeted_rewrite.
    """
    model_config = ConfigDict(extra="forbid")

    tool_density_max: int = Field(default=4, ge=1, le=20)
    banned_phrases: list[str] = Field(default_factory=lambda: [
        "expert-level",
        "deep expertise",
        "world-class",
        "guru",
        "rockstar",
        "10x",
        "ninja",
    ])
```

Mounted on both `StarterTemplate` and `MergedConfig` as `writer_rules: WriterRules = Field(default_factory=WriterRules)`.

`utils/merge.py` gains the now-familiar one-line addition to the `base` dict (the documented `extra="forbid"` propagation gotcha):

```python
base = {
    # ... existing ...
    "writer_rules": template.writer_rules,
}
```

Validation rules:
- `tool_density_max` constrained to [1, 20] — a value of 0 would disable the rule; 21+ defeats the purpose.
- `banned_phrases` may be empty if an operator explicitly wants to disable the ban (degenerate case; not recommended).

---

## 4. Insertion into existing schemas — invariants preserved

| Existing model | Field added | Default | Required? |
|---|---|---|---|
| `ContentPlan` | `role_positioning: RolePositioning \| None` | `None` | optional (prompt-required) |
| `StarterTemplate` | `writer_rules: WriterRules` | factory default | optional |
| `MergedConfig` | `writer_rules: WriterRules` | factory default | optional |

No removals. No type changes on any existing field. No re-ordering of `WorkflowState` fields. No new `WorkflowState` fields at all (the new data flows through `ContentPlan` and the already-loaded `job_context`).

---

## 5. Auto-generated tool schemas: planner picks up the field automatically

`stages/plan_content.py` builds the tool schema with `schema = ContentPlan.model_json_schema()`. Adding `role_positioning` to `ContentPlan` means the LLM's tool input schema automatically requires the field. No hand-edited JSON schema to maintain.

`stages/write_letter.py` uses a hand-written `_WRITE_SCHEMA = {"text": str, "mode": str}` — unchanged, because the writer doesn't output positioning, it consumes positioning. The writer's `build_prompt` formats the input `ContentPlan` (including the new sub-object) into the user message.

`stages/hiring_review.py` uses a hand-written `_REVIEW_SCHEMA` for output — unchanged in shape. The new positioning-specific dimensions ride as additional entries in the existing `weaknesses` list (`SectionReview.weaknesses` already supports arbitrary `text` + `severity` + `priority_fix`).

---

## 6. Relationship diagram

```
StarterTemplate.writer_rules  ──merge_config──▶  MergedConfig.writer_rules
                                                             │
                                                             ▼
                                          stages/write_letter.build_prompt
                                          (formats tool_density_max +
                                           banned_phrases into the writer
                                           user message)

WorkflowState.job_context.raw_job_text  ──────▶  stages/hiring_review.build_prompt
                                                  (NEW: prompt now includes
                                                   the original job text)
                                                  + state.config.review_config
                                                  + state.letter_draft.text
                                                  + state.requirements

stages/plan_content.parse_response
        │
        ▼
ContentPlan
├── (existing fields unchanged)
└── role_positioning: RolePositioning | None  ◀── NEW
        ├── primary_role_family
        ├── primary_selling_point
        ├── secondary_selling_points
        ├── topics_to_emphasise
        ├── topics_to_deemphasise
        └── opening_angle
                │
                ▼
stages/write_letter.build_prompt
(formats role_positioning into the
 writer user message so the LLM
 knows how to open and what to
 emphasise/deemphasise)
```

---

## 7. Backward-compatibility audit

- Existing starter-template YAML files: continue to parse — `writer_rules` has a `Field(default_factory=WriterRules)`.
- Existing JSON artefacts that contain a `ContentPlan` without `role_positioning`: continue to load — the field is `| None` with default `None`.
- Existing tests: no schema-shape regressions; the 215-test suite continues to pass without modification.
- Feature 006 observability: unchanged. The new content-plan summary in `utils/summaries.py` already returns a dict; we extend `summarise_content_plan` to add `role_positioning_present: bool` (a one-bit signal, not the actual text — preserves the summary-mode privacy default).
- Feature 007 prompt registry: editing the three prompt files automatically bumps their hashes on the next `jobagent prompts sync` — exactly the intended observable signal.

No migration step.

---

## 8. State transitions (for the new `RolePositioning` lifecycle)

```
[planner LLM call]
        │
        ▼ produces JSON with role_positioning sub-object
[parse_response]
        │
        ▼ validates against ContentPlan schema (auto from Pydantic)
[ContentPlan written to artefacts/content_plan.json]
        │
        ▼ same model_dump as before; positioning rides inside
[writer reads ContentPlan from state]
        │
        ▼ build_prompt formats role_positioning into the user message
[writer produces letter prose aligned with positioning]
        │
        ▼
[hiring_review reads letter + raw_job_text + requirements + dimensions]
        │
        ▼ build_prompt now includes the full job description
[review report; weaknesses tagged with positioning dimensions]
        │
        ▼ existing targeted_rewrite path takes over for flagged sections
```

No new persistence step. No new artefact file. The `artifacts/content_plan.json` writer already serialises the full `ContentPlan` — the new sub-object is included automatically.
