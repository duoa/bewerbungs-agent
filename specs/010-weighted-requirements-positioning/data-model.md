# Phase 1 Data Model: Weighted Requirements + Refined Role Positioning

**Feature**: 010-weighted-requirements-positioning
**Date**: 2026-05-26

Three new enums, one new Pydantic model (`RequirementItem`), and two evolved existing models (`RequirementExtraction` and `RolePositioning`). All changes live in `src/bewerbungs_agent/models/state.py`. No new files; no new state-level fields on `WorkflowState`.

---

## 1. New enums

All three are `str` enums, placed in `state.py` near the existing domain enums.

```python
class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class RequirementCategory(str, Enum):
    core = "core"
    technical = "technical"
    collaboration = "collaboration"
    domain = "domain"
    optional = "optional"


class EvidenceNeeded(str, Enum):
    required = "required"
    preferred = "preferred"
    optional = "optional"
```

Notes:
- `str` enums serialise cleanly to JSON for the Anthropic tool-use schema.
- `RequirementCategory` values match the existing free-form `Requirement.label` convention (see §5 for the back-fill).

---

## 2. New model: `RequirementItem`

```python
class RequirementItem(BaseModel):
    """One weighted requirement extracted from the job description.

    Richer replacement for the legacy ``Requirement`` model — feature 010
    adds the four explicit attributes downstream stages need to reason about
    weighting, categorisation, and evidence anchoring.
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=16)
    text: str = Field(..., min_length=1)
    priority: Priority
    category: RequirementCategory
    evidence_needed: EvidenceNeeded
    source_excerpt: str | None = Field(default=None, max_length=200)
```

**Validation rules**:
- `id`: 1..16 chars, free-form short token (LLM produces `R1`, `R2`, etc.). Uniqueness within a `RequirementExtraction` is enforced at the parent level (see §3.3).
- `text`: required non-empty string. No upper bound — a long job description may produce long requirement text; we trust the LLM not to dump entire paragraphs.
- `priority`, `category`, `evidence_needed`: required enum values.
- `source_excerpt`: optional; when present, ≤ 200 chars. Verbatim job-text fragment cited by the LLM as the source of the requirement.
- `extra="forbid"`: prevents typos and silent drift.

---

## 3. Evolved model: `RequirementExtraction`

The existing model gains one new field. Existing fields stay; backward compat is preserved via a model validator.

```python
class RequirementExtraction(BaseModel):
    """Structured output of the extract_requirements stage."""
    model_config = ConfigDict(extra="forbid")  # already set; restated

    # ... existing fields unchanged ...
    core_requirement: str
    technical_requirements: list[str] = Field(default_factory=list)
    collaboration_requirement: str | None = None
    domain_requirement: str | None = None
    optional_requirement: str | None = None
    tone_signals: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    all_requirements: list[Requirement] = Field(default_factory=list)

    # NEW: weighted-requirement list (feature 010)
    requirement_items: list[RequirementItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_unique_item_ids(self) -> "RequirementExtraction":
        seen: set[str] = set()
        for item in self.requirement_items:
            if item.id in seen:
                raise ValueError(
                    f"Duplicate RequirementItem id: {item.id!r} appears more than once"
                )
            seen.add(item.id)
        return self

    @model_validator(mode="after")
    def _backfill_all_requirements_from_items(self) -> "RequirementExtraction":
        """Populate legacy all_requirements from requirement_items when absent.

        Lets downstream consumers that read ``all_requirements`` continue to
        work without code change once the extractor starts producing
        ``requirement_items``.
        """
        if self.requirement_items and not self.all_requirements:
            priority_map = {
                Priority.high: 1,
                Priority.medium: 2,
                Priority.low: 3,
            }
            self.all_requirements = [
                Requirement(
                    label=item.category.value,
                    text=item.text,
                    priority=priority_map[item.priority],
                )
                for item in self.requirement_items
            ]
        return self
```

**Field placement**: appended at the end so existing serialisation order is preserved.

**Backward-compat invariants**:
- Legacy JSON (no `requirement_items`): `requirement_items` defaults to `[]`; `all_requirements` keeps whatever was in the JSON. Both validators pass. ✓
- New JSON with both `requirement_items` and `all_requirements`: both validators pass; the back-fill validator notices `all_requirements` is non-empty and leaves it alone. ✓
- New JSON with only `requirement_items`: back-fill validator populates `all_requirements` from the items. ✓
- New JSON with duplicate item IDs: parse raises `ValueError`. ✓ (FR-005)

---

## 4. Evolved model: `RolePositioning`

Field renames + one new field. Backward-compat via Pydantic `Field(..., alias=...)` + `populate_by_name=True`.

```python
class RolePositioning(BaseModel):
    """Planner's explicit decision about how to frame the cover letter.

    Feature 010 normalises field names and adds risky_or_gap_areas.
    Feature-008-shape JSON still loads via aliases.
    """
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    role_family: str = Field(..., alias="primary_role_family")
    primary_selling_point: str
    secondary_selling_points: list[str] = Field(default_factory=list)
    opening_angle: str
    emphasise: list[str] = Field(
        default_factory=list, alias="topics_to_emphasise"
    )
    deemphasise: list[str] = Field(
        default_factory=list, alias="topics_to_deemphasise"
    )
    # NEW (feature 010)
    risky_or_gap_areas: list[str] = Field(default_factory=list)
```

**Backward-compat invariants**:
- Feature-008-shape JSON (`primary_role_family`, `topics_to_emphasise`, `topics_to_deemphasise`, no `risky_or_gap_areas`): loads cleanly; `risky_or_gap_areas` defaults to `[]`. ✓ (FR-019, FR-024)
- New-shape JSON (`role_family`, `emphasise`, `deemphasise`, `risky_or_gap_areas`): loads cleanly. ✓
- Mixed-shape JSON (e.g., `role_family` + `topics_to_emphasise`): both load — Pydantic accepts either name. Acceptable: the operator/LLM picked one form per field.
- Unknown field name (e.g., `role_familly` typo): raises `ValidationError`. ✓ (FR-020, FR-027)
- Output via `model_dump()`: uses canonical (new) field names. The Pydantic alias is for input only.

**Output canonicalisation note**: feature-008 artifacts re-saved by a feature-010 run will be re-canonicalised to the new field names (because `model_dump` uses the model's own field names, not aliases). This is the intended migration: artifacts gradually flow to the new names as runs re-process them.

---

## 5. Existing model preserved: `Requirement`

Unchanged. The legacy `Requirement` (with `label: str`, `text: str`, `priority: int`) stays in `state.py` exactly as it is. The back-fill validator in §3 maps `RequirementItem` instances onto `Requirement` instances for the legacy `all_requirements` field.

---

## 6. Auto-generated tool schemas

Two existing stages build their LLM tool schemas via `Model.model_json_schema()` — both pick up the new fields automatically without manual schema editing:

| Stage | Schema source | Effect of feature 010 |
|---|---|---|
| `extract_requirements` | `RequirementExtraction.model_json_schema()` | The LLM tool input gains `requirement_items: array[RequirementItem]` with full enum constraints on `priority`, `category`, `evidence_needed`. |
| `plan_content` | `ContentPlan.model_json_schema()` (which contains `role_positioning: RolePositioning \| None`) | The LLM tool input shows the new field names (`role_family`, `emphasise`, `deemphasise`, `risky_or_gap_areas`). The aliases are NOT included in the generated schema — the LLM produces the canonical names. Older feature-008 artifacts still LOAD via aliases, but new LLM outputs always use the canonical names. |

The hiring-review stage's tool schema (`_REVIEW_SCHEMA`) is hand-built and unchanged in shape; only the user-message text formatter changes to surface `risky_or_gap_areas` in the content-plan summary block.

---

## 7. Relationship diagram

```
RequirementExtraction (existing model, evolved)
├── core_requirement, technical_requirements, ... (existing — unchanged)
├── all_requirements: list[Requirement]       (legacy — back-fill validator populates)
└── requirement_items: list[RequirementItem]  (NEW — feature 010)
        ├── id (str, ≤16 chars, unique within the list)
        ├── text (str)
        ├── priority: Priority enum
        ├── category: RequirementCategory enum
        ├── evidence_needed: EvidenceNeeded enum
        └── source_excerpt: str | None (≤200 chars)

ContentPlan (existing model from feature 005, evolved by 008)
├── ... (existing fields unchanged)
└── role_positioning: RolePositioning | None
        ├── role_family (renamed from primary_role_family; alias accepts the old name)
        ├── primary_selling_point
        ├── secondary_selling_points
        ├── opening_angle
        ├── emphasise (renamed from topics_to_emphasise; alias accepts the old name)
        ├── deemphasise (renamed from topics_to_deemphasise; alias accepts the old name)
        └── risky_or_gap_areas (NEW — feature 010)
```

---

## 8. Stage-by-stage read patterns

| Stage | Reads | Writes |
|---|---|---|
| `extract_requirements` | `state.job_context.raw_job_text` (and optional `raw_company_text`) | `state.requirements` with `requirement_items` populated by the LLM; legacy summary fields also populated |
| `plan_content` | `state.requirements` (incl. `requirement_items` when present); other existing reads | `state.content_plan` with `role_positioning` using NEW field names |
| `hiring_review` (feature 009 block, evolved by 010) | `state.content_plan.role_positioning` — reads `role_family`, ..., `risky_or_gap_areas` | unchanged shape of `letter_review` |
| `write_letter` | `state.content_plan` (as before) | unchanged |
| All other stages | unchanged | unchanged |

---

## 9. Lifecycle / state transitions

No new state machine. The new fields participate in the existing structured-before-generative flow:

```
extract_requirements → produces requirement_items (and legacy summary fields)
                       │
                       ▼
plan_content         → reads requirement_items (priority-ordered),
                       produces RolePositioning with new field names + risky_or_gap_areas
                       │
                       ▼
write_letter         → reads ContentPlan (incl. RolePositioning); behaviour unchanged per FR-013
                       │
                       ▼
hiring_review        → reads ContentPlan; surfaces risky_or_gap_areas in the existing content-plan block
                       │
                       ▼
targeted_rewrite     → unchanged
                       │
                       ▼
validate_outputs     → unchanged
```

---

## 10. Backward-compatibility audit (summary)

| Artifact / Code Path | Pre-feature-010 behaviour | Post-feature-010 behaviour |
|---|---|---|
| Legacy `RequirementExtraction` JSON (no `requirement_items`) | loaded fine | loads fine; `requirement_items=[]`, legacy fields unchanged |
| New `RequirementExtraction` JSON with `requirement_items` only | n/a | loads; `all_requirements` back-filled from items |
| Feature-008 `RolePositioning` JSON (old field names) | loaded fine | loads via aliases; `risky_or_gap_areas=[]` |
| Feature-010 `RolePositioning` JSON (new field names) | n/a | loads; outputs use the new names |
| Mixed-name `RolePositioning` JSON | n/a | loads (Pydantic accepts both per field); operator-edited artifacts work |
| Unknown field name on either model | raises (existing `extra="forbid"`) | still raises |
| Duplicate `RequirementItem.id` | n/a | raises `ValueError` (new validator) |
| Existing 239-test suite | passes | passes (all legacy paths preserved) |
