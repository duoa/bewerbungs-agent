# Phase 0 Research: Weighted Requirements + Refined Role Positioning

**Feature**: 010-weighted-requirements-positioning
**Date**: 2026-05-26

Resolves implementation-relevant unknowns. Does not re-litigate scope decisions documented in `spec.md > Assumptions`.

---

## R1 — Is `RequirementItem` a new model alongside the existing `Requirement`, or a replacement?

**Decision**: **New model alongside**. `RequirementItem` is added as a richer per-requirement record. The existing `Requirement` model (with `label` + `text` + `priority: int`) stays. `RequirementExtraction` gains a NEW field `requirement_items: list[RequirementItem]`; the legacy `all_requirements: list[Requirement]` field stays untouched. A Pydantic `model_validator(mode="after")` populates `all_requirements` from `requirement_items` when the legacy field is absent and the new field is present — so any downstream consumer reading `all_requirements` continues to get a non-empty list without code change.

**Rationale**:
- Backward compatibility is a stated FR (FR-018). Renaming or replacing `Requirement` would break artifacts and downstream code that reads `all_requirements`.
- The two models have non-overlapping shapes (`Requirement.label: str` vs `RequirementItem.category: enum`; `Requirement.priority: int` vs `RequirementItem.priority: enum`). One-to-one aliasing isn't feasible.
- "Alongside" is the smallest possible change for the largest backward-compat surface.

**Alternatives considered**:
- Rename `Requirement` → `RequirementItem` and migrate `all_requirements` to the new shape: rejected — breaks consumers, breaks legacy artifacts, requires a migration step. Outside the scope of "small additive feature".
- Keep only the new model and delete `Requirement`: rejected for the same reason.

---

## R2 — How are the three enums defined?

**Decision**: Three `str` enums in `state.py` (next to the other domain enums there):

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

**Rationale**:
- `str` enums serialise cleanly to JSON, which matters for the LLM tool schema (auto-generated from Pydantic emits the `enum: [...]` constraint to the LLM, which produces the values reliably).
- `RequirementCategory` mirrors the values already used in `Requirement.label` (`"core"`, `"technical"`, `"collaboration"`, `"domain"`, `"optional"`) — a `model_validator` can map old `label` strings to the new enum cleanly.
- `Priority` values are ordinal but not numeric — `high`/`medium`/`low` is clearer in prompts and JSON than `1`/`2`/`3`. (The existing `Requirement.priority: int` field is the LEGACY pathway.)

**Alternatives considered**:
- Numeric priority (1..3 or 1..5): rejected — strings are more readable in trace UIs and in the prompt itself.
- `IntEnum`: rejected — same readability concern.
- A single combined enum for all three: rejected — different semantic spaces.

---

## R3 — How are the new fields surfaced in the LLM tool schema?

**Decision**: Zero manual schema editing. Both `extract_requirements.py` and `plan_content.py` build their tool schemas via `Model.model_json_schema()`. Adding `requirement_items: list[RequirementItem] = []` to `RequirementExtraction` and adding `risky_or_gap_areas: list[str] = []` to `RolePositioning` propagates automatically into the LLM's tool input schema — including the per-enum `enum: [...]` constraints, which Anthropic's tool-use respects strictly.

**Rationale**:
- Pydantic + Anthropic tool-use is the established pattern in this codebase (features 001, 005, 008). Re-using it means the LLM is constrained at schema time to produce only enum-valid values for `priority`, `category`, `evidence_needed`.
- Optional fields with defaults (e.g., `source_excerpt: str | None = None`) appear as optional in the JSON Schema — the LLM may omit them without breaking parse.
- No risk of schema/prompt drift: change the model, the schema updates, the prompt is the only natural-language reminder.

**Alternatives considered**:
- Hand-edit the tool schemas: rejected — duplicates information; risks drift between Pydantic model and the LLM contract.

---

## R4 — Backward-compat strategy for `RolePositioning` field renames

**Decision**: Use Pydantic `Field(..., alias=...)` with `model_config = ConfigDict(populate_by_name=True, extra="forbid")` on the new model. Both the new and old field names load; outputs (via `model_dump`) use the new names.

```python
class RolePositioning(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    role_family: str = Field(..., alias="primary_role_family")
    primary_selling_point: str
    secondary_selling_points: list[str] = Field(default_factory=list)
    opening_angle: str
    emphasise: list[str] = Field(default_factory=list, alias="topics_to_emphasise")
    deemphasise: list[str] = Field(default_factory=list, alias="topics_to_deemphasise")
    risky_or_gap_areas: list[str] = Field(default_factory=list)
```

With `populate_by_name=True`, both `{"role_family": "..."}` AND `{"primary_role_family": "..."}` load into the same field. Feature-008 artifacts continue to parse; new artifacts use the new names.

**Rationale**:
- Pydantic-native, no custom validators needed.
- `populate_by_name=True` is the exact Pydantic v2 mechanism for "accept both names".
- `extra="forbid"` is preserved — typos still raise, only the listed aliases are accepted.

**Important caveat**: `extra="forbid"` + `populate_by_name=True` interact in a specific way — both names are accepted, but unknown names (not the canonical name or the alias) are forbidden. Test coverage explicitly verifies this in FR-027/FR-024.

**Alternatives considered**:
- Custom `model_validator(mode="before")` that rewrites old keys to new keys: rejected — more code; not the canonical Pydantic pattern.
- Two separate models (`RolePositioningV1`, `RolePositioningV2`) with a converter: rejected — operator confusion, two sources of truth.

---

## R5 — Where do `requirement_items` get used downstream?

**Decision**: Three downstream sites surface or consume `requirement_items`:

1. **`plan_content.build_prompt`** — extends the existing `# Job Requirements` block. Currently lists `core_requirement`, `technical_requirements[*]`, etc. as text lines. New behaviour: when `state.requirements.requirement_items` is populated, render those instead (sorted by priority descending), each line tagged with the item's `id` and `evidence_needed`. Example: `[R1, priority=high, evidence=required] design and operate scalable cloud infrastructure`. When `requirement_items` is empty (legacy state), fall back to the existing block — guarantees zero regression for legacy paths.

2. **`hiring_review.build_prompt`** — no change to the `## Role Requirements` block. The hiring review continues to read the existing categorical fields (core/technical/etc.); the new structure is available on `state.requirements.requirement_items` if a future feature needs it, but this feature does NOT consume it from the reviewer (the spec doesn't require it).

3. **Writer** — unchanged. The writer reads `ContentPlan`, not `RequirementExtraction`, so the new field doesn't reach the writer naturally. Per FR-013, writer behaviour is unchanged.

**Rationale**:
- Concentrating new-field consumption in the planner matches the project's "structured-before-generative" principle: the planner is the right place to reason about weighted requirements; the writer just renders the plan.
- The fallback path for legacy states is the minimum-surprise behaviour for any test or operator workflow that doesn't populate `requirement_items`.

**Alternatives considered**:
- Also surface `requirement_items` in the hiring-review prompt: rejected — spec FR-010 doesn't require it, and the review already has the role positioning + extracted-requirement summary. Adding more risks token bloat.
- Plumb to the writer: rejected per FR-013 — out of scope.

---

## R6 — How does `risky_or_gap_areas` reach the hiring review?

**Decision**: One-line addition to `hiring_review.build_prompt`'s content-plan summary builder (added by feature 009). Feature 009's `## Content Plan` block already surfaces `role_positioning` sub-fields (primary_role_family, primary_selling_point, opening_angle, etc.). After the rename, the same builder reads `role_family`, `primary_selling_point`, etc., AND additionally renders `risky_or_gap_areas` as a new sub-line when non-empty.

**Rationale**:
- Localised change: one new conditional `if rp.risky_or_gap_areas: plan_lines.append(...)` line in `hiring_review.build_prompt`.
- The reviewer needs this signal — `risky_or_gap_areas` directly informs the `critical_requirements_underweighted` dimension (feature 009): a topic that's both "underweighted" AND "risky_or_gap" is a different judgement than "underweighted" alone.
- Omitting the line when the list is empty matches the graceful-omission discipline from features 008+009 — no `(none)` placeholders.

**Alternatives considered**:
- Add a new evaluation dimension for risky-or-gap areas: rejected per spec Assumptions ("does NOT introduce new always-on review dimensions beyond what features 008 and 009 already established").

---

## R7 — Should `RequirementItem.id` be deterministic from content, or extractor-chosen?

**Decision**: Extractor-chosen, per-run unique. The LLM produces `id` values like `R1`, `R2`, ..., as short tokens it picks freely. Uniqueness within the response is asserted at parse time by a `model_validator(mode="after")` that raises `ValueError` if duplicate IDs are detected.

**Rationale**:
- Spec FR-005 requires "Within a single run, requirement IDs MUST be unique" — explicit uniqueness invariant.
- Spec Assumptions say "Stability across runs (deterministic from content) is desirable but not required" — so we don't have to hash content.
- Letting the LLM pick the tokens keeps the prompt natural ("Number your requirements R1, R2, R3, ...") and the prompt-side instruction is short.
- A `model_validator` is the lightweight enforcement of FR-005 at parse time.

**Alternatives considered**:
- Compute `id` as SHA-256 prefix of `text`: rejected — overkill; readability worse; not required.
- Sequential numbering enforced by the parser (rewrite IDs to R1..RN regardless of what the LLM produced): rejected — discards information the LLM may have used to cross-reference.

---

## R8 — What does `source_excerpt` cite?

**Decision**: Optional verbatim job-description fragment (≤ 200 chars). The LLM is instructed to copy the exact text that supports each `RequirementItem` (when a clean fragment exists). When the requirement is synthesised from multiple sentences or implicit-but-clear from context, `source_excerpt` is omitted (None).

**Rationale**:
- Spec lists it as optional; the user's plan args also call it "optional".
- Verbatim citation strengthens factuality (Principle I) by giving downstream stages a way to verify the LLM didn't fabricate the requirement.
- 200-char cap prevents the LLM from dumping the whole paragraph; a `Field(max_length=200)` enforces this.
- "When in doubt, omit" rule keeps the LLM honest — better None than a fabricated quote.

**Alternatives considered**:
- Mandatory `source_excerpt`: rejected — forces the LLM to fabricate for synthesised requirements.
- A character span (start+end offset into `raw_job_text`): rejected — adds complexity for no payoff; the LLM doesn't reliably emit character offsets.

---

## R9 — How is the legacy `all_requirements` field populated?

**Decision**: Pydantic `model_validator(mode="after")` on `RequirementExtraction`. When `requirement_items` is populated AND `all_requirements` is empty (or absent in the input JSON), the validator builds a `list[Requirement]` from the items:

```python
@model_validator(mode="after")
def _backfill_all_requirements(self) -> "RequirementExtraction":
    if self.requirement_items and not self.all_requirements:
        priority_map = {Priority.high: 1, Priority.medium: 2, Priority.low: 3}
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

**Rationale**:
- Downstream consumers reading `all_requirements` continue to work without code change.
- Validator runs after parse, so it sees both the new and old fields if both are present.
- The priority enum → int mapping is the obvious one; preserves the existing convention that 1 = highest.

**Alternatives considered**:
- Update every downstream consumer to read `requirement_items`: rejected — wider blast radius; this feature stays focused on the schema + extract + planner sites.
- Synthesise `all_requirements` lazily via a `@property`: rejected — properties don't serialise into `model_dump`, breaking artifact-write paths.

---

## R10 — Test surface mapped to spec FRs

| Test (suggested name) | FR(s) covered | File |
|---|---|---|
| `test_requirement_extraction_parses_mocked_llm_output_with_items` | FR-001, FR-004, FR-021 | `tests/unit/test_extract_requirements.py` |
| `test_requirement_item_defaults_for_missing_optional_fields` | FR-004, FR-021 | same |
| `test_requirement_item_invalid_priority_value_raises` | FR-002, FR-021 | same |
| `test_requirement_extraction_legacy_payload_loads` (no requirement_items field) | FR-018, FR-023 | same |
| `test_requirement_item_duplicate_ids_raise` | FR-005 | same |
| `test_role_positioning_accepts_new_field_names` | FR-007, FR-022 | `tests/unit/test_plan_content.py` |
| `test_role_positioning_accepts_legacy_field_names_via_alias` | FR-019, FR-024 | same |
| `test_role_positioning_risky_or_gap_areas_defaults_to_empty` | FR-019, FR-024 | same |
| `test_role_positioning_unknown_field_forbidden` | FR-020, FR-027 | same |
| `test_planner_build_prompt_renders_requirement_items_in_priority_order` | (planner consumption of US1) | same |
| `test_hiring_review_prompt_surfaces_risky_or_gap_areas_when_present` | FR-010, FR-025 | `tests/unit/test_hiring_review.py` |
| `test_hiring_review_prompt_omits_risky_or_gap_areas_when_empty` | (graceful omission) | same |
| `test_planner_produces_infrastructure_first_role_family_on_fixture` | FR-011, FR-026, SC-005 | `tests/unit/test_plan_content.py` |

13 new tests total. Each covers one spec FR or one structural invariant. The MLflow / Langfuse non-interference invariant (SC-008) is structurally guaranteed and verified by the existing 239-test suite continuing to pass.

---

## Open questions resolved

- "Will adding `requirement_items` to `RequirementExtraction` break the LLM's tool-use schema?" — No. The auto-schema generates a new optional array field; the LLM populates it. If the LLM omits it (older prompt or hallucinated structure), the field defaults to `[]` and the validator's backfill path doesn't fire (because `all_requirements` will also be empty).
- "Does Pydantic `populate_by_name=True` with `extra='forbid'` accept BOTH names but reject unknown names?" — Yes; verified in Pydantic v2 docs.
- "Does the writer need to know about `risky_or_gap_areas`?" — Per FR-013, no behavioural change to the writer. The field rides in the `ContentPlan.role_positioning` that the writer already consumes (it's a list[str] additional sub-field on the positioning object). The writer's existing prompt rules don't reference it; adding it to the writer's prompt context is out of scope.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
