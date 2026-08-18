# Phase 1 Data Model: ContentPlan as a Hiring Story

**Feature**: 011-contentplan-hiring-story
**Date**: 2026-05-26

One new Pydantic model (`ParagraphPlan`), two new fields on `ContentPlan` (one top-level + one list-of-`ParagraphPlan`), three model validators on `ContentPlan`. No changes to any other state model. No new state-level field on `WorkflowState`. Legacy `SectionPlan` and `ContentPlan.sections` stay untouched for backward compatibility.

---

## 1. New model: `ParagraphPlan`

Lives in `src/bewerbungs_agent/models/state.py`, placed directly above `ContentPlan`.

```python
class ParagraphPlan(BaseModel):
    """One planned paragraph of the cover letter (feature 011).

    Replacement for the thinner SectionPlan when the planner emits the new
    hiring-story structure. Lives ALONGSIDE SectionPlan for backward
    compatibility — legacy ContentPlan artifacts continue to use `sections`.
    """
    model_config = ConfigDict(extra="forbid")

    # What this paragraph is for in the story
    purpose: str = Field(..., min_length=1)
    main_message: str = Field(..., min_length=1, max_length=300)

    # What the paragraph draws on
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    # Paragraph-level emphasis hints, complementing the plan-level
    # role_positioning.emphasise / .deemphasise from feature 010
    emphasise: list[str] = Field(default_factory=list)
    deemphasise: list[str] = Field(default_factory=list)

    # Density limits — both REQUIRED so the planner consciously picks
    # per-paragraph density rather than relying on a flat global cap
    max_claims: int = Field(..., ge=1, le=8)
    max_tools: int = Field(..., ge=0, le=12)
```

**Field semantics**:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `purpose` | `str` (≥1 char) | required | Free-form short label naming this paragraph's role in the story (e.g., `"opening"`, `"platform_credibility"`, `"working_style"`, `"closing"`). The set of allowed values is open — operators choose any convention. |
| `main_message` | `str` (1..300 chars) | required | The SINGLE core idea the paragraph delivers, as one sentence. Length cap prevents drafting prose here. |
| `requirement_ids` | `list[str]` | `[]` | References `RequirementItem.id` values from the run's `requirement_items` (feature 010). May be empty for purely framing paragraphs (motivation, closing). Validated at stage level. |
| `evidence_refs` | `list[str]` | `[]` | References claim texts from the plan's `evidence_map.items`. Validated at parse time (model-level). |
| `emphasise` | `list[str]` | `[]` | Topics the writer should foreground in THIS paragraph. Complements the plan-level `role_positioning.emphasise`. |
| `deemphasise` | `list[str]` | `[]` | Topics the writer should downplay in THIS paragraph. Complements the plan-level `role_positioning.deemphasise`. |
| `max_claims` | `int` (1..8) | required | Hard upper bound on the number of distinct claims the paragraph may express. Validated at parse time. |
| `max_tools` | `int` (0..12) | required | Hard upper bound on the number of distinct tool/technology names the paragraph may name. OVERRIDES the global `writer_rules.tool_density_max` for this paragraph specifically. `0` is valid (e.g., a motivation paragraph that should name no tools). |

**Validation rules** (field-level):
- `purpose`, `main_message` non-empty.
- `main_message` ≤ 300 chars (forces single sentence).
- `max_claims` ∈ [1, 8].
- `max_tools` ∈ [0, 12].
- `extra="forbid"` — typo fields raise.

(Cross-field validation lives on `ContentPlan`; see §3.)

---

## 2. Evolved `ContentPlan`

Two new fields appended at the end of the existing model. All existing fields unchanged.

```python
class ContentPlan(BaseModel):
    """Structured plan produced before any prose is generated."""

    model_config = ConfigDict(extra="forbid")  # already implicit; restated for clarity

    # ... existing fields unchanged ...
    template_id: str
    selected_cv_variant: str
    mode: WritingMode
    sections: list[SectionPlan] = Field(default_factory=list)
    selected_soft_skills: list[SoftSkill] = Field(default_factory=list)
    evidence_map: EvidenceMap = Field(default_factory=EvidenceMap)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    role_positioning: RolePositioning | None = None

    # NEW (feature 011) — hiring-story structure
    letter_thesis: str | None = Field(default=None, max_length=300)
    paragraphs: list[ParagraphPlan] = Field(default_factory=list)
```

**Backward-compat invariants** (verified by tests):
- Legacy JSON (no `letter_thesis`, no `paragraphs`): loads cleanly. `letter_thesis=None`, `paragraphs=[]`.
- New JSON with both `paragraphs` (populated) AND `sections` (populated): both stored as-is. No conversion in this feature.
- Unknown top-level field: raises `ValidationError` (existing `extra="forbid"` discipline preserved).

**Field placement**: appended at the end so existing serialisation order is preserved for downstream consumers that may have hand-parsed JSON.

---

## 3. Model validators on `ContentPlan`

Three Pydantic `@model_validator(mode="after")` checks. Each raises a clear `ValueError` on violation; Pydantic surfaces these as `ValidationError` with field paths.

### 3.1 `_validate_evidence_refs_within_max_claims`

```python
@model_validator(mode="after")
def _validate_evidence_refs_within_max_claims(self) -> "ContentPlan":
    for i, p in enumerate(self.paragraphs):
        if len(p.evidence_refs) > p.max_claims:
            raise ValueError(
                f"Paragraph {i} ({p.purpose!r}) lists {len(p.evidence_refs)} "
                f"evidence_refs but max_claims is {p.max_claims}; the plan cannot "
                f"promise more claims than the paragraph allows."
            )
    return self
```

Covers FR-010, FR-027.

### 3.2 `_validate_opening_paragraph_max_claims`

```python
@model_validator(mode="after")
def _validate_opening_paragraph_max_claims(self) -> "ContentPlan":
    if self.paragraphs:
        opening = self.paragraphs[0]
        if opening.max_claims not in (1, 2):
            raise ValueError(
                f"Opening paragraph (index 0, purpose={opening.purpose!r}) has "
                f"max_claims={opening.max_claims}; opening paragraphs must use "
                f"1 or 2 claims to keep the opening tight."
            )
    return self
```

Covers FR-012. The field-level bound `ge=1, le=8` already guarantees the value is in [1, 8]; this stricter rule applies only to index 0.

### 3.3 `_validate_paragraph_evidence_refs_in_evidence_map`

```python
@model_validator(mode="after")
def _validate_paragraph_evidence_refs_in_evidence_map(self) -> "ContentPlan":
    if not self.paragraphs:
        return self
    valid_claims = {item.claim for item in self.evidence_map.items}
    if not valid_claims:
        # Empty evidence_map: skip (matches existing SectionPlan parse_response behaviour)
        return self
    for i, p in enumerate(self.paragraphs):
        for claim in p.evidence_refs:
            bare = claim.split(" [source:")[0].strip()
            if bare not in valid_claims:
                raise ValueError(
                    f"Paragraph {i} ({p.purpose!r}) references claim "
                    f"{bare!r} which is not in the evidence map."
                )
    return self
```

Mirrors the existing `plan_content.parse_response` check for `SectionPlan.evidence_refs`. Surfaces stale references at parse time.

### What is NOT validated at parse time

- **`requirement_ids` cross-reference against `requirement_items`** — NOT validated at the `ContentPlan` model level because `requirement_items` lives on `RequirementExtraction`, not `ContentPlan`. Validated at stage level inside `plan_content.parse_response` (see §6 below). Required by FR-005, FR-030.

---

## 4. Backward-compatibility audit

| Concern | Pre-feature-011 behaviour | Post-feature-011 behaviour |
|---|---|---|
| Legacy `ContentPlan` JSON (no `letter_thesis`, no `paragraphs`) | loaded fine | loads fine; `letter_thesis=None`, `paragraphs=[]` |
| New `ContentPlan` JSON with `letter_thesis` and `paragraphs` | n/a | loads; validators run |
| `ContentPlan` with `paragraphs` containing invalid `evidence_refs` (count > max_claims) | n/a | raises `ValidationError` (3.1) |
| `ContentPlan` with `paragraphs[0].max_claims=5` | n/a | raises `ValidationError` (3.2) |
| `ContentPlan` with `paragraphs[*].evidence_refs` referencing claims not in `evidence_map` | n/a | raises `ValidationError` (3.3) |
| `ContentPlan` with unknown top-level field | raised | still raises |
| Existing 254-test suite | passes | passes (new fields default, validators no-op when paragraphs=[]) |
| `plan_content.parse_response` for `SectionPlan.evidence_refs` validation | runs at stage level | unchanged |

---

## 5. Auto-generated tool schema (planner)

`stages/plan_content.py` line 103 already calls `ContentPlan.model_json_schema()`. After adding `letter_thesis: str | None` and `paragraphs: list[ParagraphPlan]`:

- The LLM's tool input schema gains `letter_thesis` (optional, string, max 300 chars) and `paragraphs` (array of `ParagraphPlan` objects).
- Each `ParagraphPlan` requires `purpose`, `main_message`, `max_claims`, `max_tools`; optional `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise`.
- Field constraints (`ge=1, le=8` on `max_claims`; `ge=0, le=12` on `max_tools`; `max_length=300` on `main_message` and `letter_thesis`) emit as `minimum`/`maximum` and `maxLength` in JSON Schema. Anthropic tool-use respects them.

No manual schema editing needed. The planner stage's existing `_validate_paragraph_evidence_refs_in_evidence_map`-style check (inside `parse_response`) remains and is supplemented by the new `ContentPlan`-level validators that ALSO check the same and more — defensive double-coverage that operators benefit from on artifact replay paths.

---

## 6. Stage-level addition to `plan_content.parse_response`

After the existing model validation succeeds, the stage performs the `requirement_ids` cross-reference check that the model-level validators CANNOT do:

```python
def parse_response(data: dict[str, Any], soft_skill_max: int = 3) -> ContentPlan:
    # ... existing soft-skill cap + claim-not-in-evidence-map checks ...

    plan = ContentPlan.model_validate(data)

    # Feature 011: cross-validate paragraph requirement_ids against the
    # workflow's requirement_items. This check sits at stage level (not on
    # the model) because requirement_items lives on RequirementExtraction.
    # The stage knows about the parent workflow context via the calling
    # plan_content stage; pure model replay (loading a ContentPlan JSON in
    # isolation) skips this check, which is acceptable per research §R4.
    # The actual cross-reference happens in the plan_content() function
    # rather than parse_response() because parse_response doesn't take
    # WorkflowState as input. See contracts/schemas_and_prompts.md §5.

    return plan
```

The cross-reference happens in `plan_content()` (the LangGraph node), AFTER `parse_response` returns, by reading `state.requirements.requirement_items` and looking up each `paragraphs[*].requirement_ids` entry.

---

## 7. Relationship diagram

```
ContentPlan (existing model, evolved by feature 011)
├── template_id, selected_cv_variant, mode (existing — unchanged)
├── sections: list[SectionPlan]                  (legacy — unchanged, still populated by planner)
├── selected_soft_skills: list[SoftSkill]        (existing — unchanged)
├── evidence_map: EvidenceMap                    (existing — unchanged)
├── open_questions: list[str]                    (existing — unchanged)
├── assumptions: list[str]                       (existing — unchanged)
├── role_positioning: RolePositioning | None     (added feature 008, evolved feature 010 — unchanged here)
├── letter_thesis: str | None  (NEW — feature 011)
└── paragraphs: list[ParagraphPlan]              (NEW — feature 011)
        │
        ▼
ParagraphPlan (NEW model, feature 011)
├── purpose: str (required, non-empty)
├── main_message: str (1..300 chars)
├── requirement_ids: list[str] = []              (validated at stage level against RequirementExtraction.requirement_items)
├── evidence_refs: list[str] = []                (validated at model level against ContentPlan.evidence_map.items)
├── emphasise: list[str] = []                    (paragraph-level; complements RolePositioning.emphasise)
├── deemphasise: list[str] = []                  (paragraph-level; complements RolePositioning.deemphasise)
├── max_claims: int (1..8, required)             (opening paragraph constrained to {1, 2} by model validator)
└── max_tools: int (0..12, required)             (OVERRIDES writer_rules.tool_density_max for this paragraph)
```

---

## 8. Stage-by-stage read patterns (post-feature-011)

| Stage | Reads (new behaviour vs feature 010) | Writes |
|---|---|---|
| `extract_requirements` | unchanged | unchanged (produces `RequirementExtraction.requirement_items`) |
| `plan_content` | `state.requirements.requirement_items` (existing); produces `ContentPlan` with `letter_thesis` + `paragraphs` populated | `state.content_plan` |
| `write_letter` | reads `state.content_plan.paragraphs` when non-empty (feature 011); falls back to `state.content_plan.sections` when `paragraphs` is empty (legacy plan) | `state.letter_draft` |
| `hiring_review` | UNCHANGED — content-plan summary block from feature 009 serialises the whole plan, automatically including the new fields | unchanged |
| `targeted_rewrite` | unchanged | unchanged |
| `validate_outputs` | unchanged | unchanged |

---

## 9. Lifecycle / state transitions

No new state machine. The new fields participate in the existing structured-before-generative flow exactly as the legacy `sections` field does:

```
extract_requirements → produces RequirementExtraction (with requirement_items per feature 010)
                       │
                       ▼
plan_content         → produces ContentPlan with letter_thesis + paragraphs
                       (paragraphs cross-validated against requirement_items + evidence_map)
                       │
                       ▼
write_letter         → reads ContentPlan; prefers paragraphs (when non-empty) over sections;
                       respects per-paragraph max_claims / max_tools
                       │
                       ▼
hiring_review        → reads ContentPlan; new fields surface automatically in content-plan summary
                       │
                       ▼
targeted_rewrite     → unchanged
                       │
                       ▼
validate_outputs     → unchanged
```
