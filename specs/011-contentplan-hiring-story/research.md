# Phase 0 Research: ContentPlan as a Hiring Story

**Feature**: 011-contentplan-hiring-story
**Date**: 2026-05-26

Resolves implementation-relevant unknowns. Does not re-litigate scope decisions in `spec.md > Assumptions`.

---

## R1 — `ParagraphPlan` alongside `SectionPlan`, or replacement?

**Decision**: **Alongside**. `ParagraphPlan` is a new model; `ContentPlan` gains a NEW field `paragraphs: list[ParagraphPlan] = Field(default_factory=list)`. The legacy `sections: list[SectionPlan]` field stays in place untouched.

**Rationale**:
- Backward compatibility (FR-022): legacy `ContentPlan` JSON has `sections` populated and no `paragraphs`. Adding `paragraphs` as a new optional field keeps that path working with zero migration.
- The two models have different shapes (`SectionPlan.title` vs `ParagraphPlan.purpose`; `SectionPlan.key_claims` vs `ParagraphPlan.main_message + evidence_refs + max_claims`). One-to-one renaming/aliasing isn't a clean fit — better to coexist.
- The writer's downstream code can read `paragraphs` when present and fall back to `sections` for legacy plans, gradual rollout without breakage.

**Alternatives considered**:
- Rename `SectionPlan` → `ParagraphPlan` and add new fields: rejected — breaks every existing test fixture that constructs `SectionPlan` directly, and breaks loading of any prior `artifacts/content_plan.json` file.
- Keep only the new `ParagraphPlan` and remove `SectionPlan`: rejected for the same reason; existing 254 tests would break.
- Two separate `ContentPlan` versions (`ContentPlanV1` / `ContentPlanV2`): rejected — operator confusion, two sources of truth, planner stage would need branching.

---

## R2 — Field type for `main_message`: single string vs constrained model

**Decision**: `main_message: str = Field(..., min_length=1, max_length=300)`. A single non-empty bounded string. NOT a list, NOT a structured object.

**Rationale**:
- The spec's central claim is "each paragraph has ONE main message" — a single string trivially enforces "one" via the type system. A list field would allow zero or many; an object would over-engineer.
- ≤ 300 chars keeps the message a single sentence (the spec's intent) rather than letting it sprawl into a draft paragraph.
- ≥ 1 char enforces non-empty at parse time.

**Alternatives considered**:
- `main_message: list[str] = Field(min_length=1, max_length=1)`: rejected — convoluted way to express "exactly one"; the string form is the obvious idiom.
- Free-form `str` (no length bound): rejected — observed risk that the LLM dumps a paragraph-length intent here; the cap forces the planner to actually pick one idea.

---

## R3 — Cross-field validators: how do they reference `requirement_items` and `evidence_map`?

**Decision**: All three validators live on `ContentPlan` (NOT on `ParagraphPlan`) because they need to compare paragraph fields to fields elsewhere on the parent model. Pydantic v2 `@model_validator(mode="after")` runs after parsing; `self` carries both `paragraphs` and `evidence_map` (and we need to look up `requirement_items` — see R4).

**Three validators**:

1. **`_validate_evidence_refs_within_max_claims`** — for each paragraph, assert `len(p.evidence_refs) <= p.max_claims`. Raises a clear error naming the paragraph index and counts on violation.

2. **`_validate_opening_max_claims`** — when `paragraphs` is non-empty, assert `paragraphs[0].max_claims in {1, 2}`. Pydantic's `Field(ge=1, le=8)` already bounds the value; this additional check enforces the OPENING-specific rule.

3. **`_validate_evidence_refs_trace_to_evidence_map`** — for each paragraph, every entry in `p.evidence_refs` must equal the `claim` field of some entry in `self.evidence_map.items`. (Same convention the existing planner `parse_response` uses for section `evidence_refs`.) Raises with the paragraph index and offending claim text.

**Rationale**:
- Cross-field validation is the canonical Pydantic-v2 model-validator use case.
- Running at parse time (not later, in `plan_content.parse_response`) means any consumer that loads a `ContentPlan` JSON gets the same guarantees — including artifact replay, hiring-review re-runs, debugging scripts.
- Validators raise `ValueError` which Pydantic surfaces as `ValidationError` with field paths — operators see exactly which paragraph and field violated.

**Important note on `requirement_ids` validation**: spec FR-030 requires `requirement_ids` to reference IDs that exist in the run's `requirement_items`. But `requirement_items` lives on `RequirementExtraction`, NOT on `ContentPlan`. A model validator on `ContentPlan` doesn't have access to the workflow state. See R4 for the chosen approach.

**Alternatives considered**:
- All three checks in `plan_content.parse_response`: rejected — replay/debugging paths that load `ContentPlan` artifacts directly would bypass the checks. Validators-on-model is the more durable place.
- Run validators on `ParagraphPlan` independently: rejected — `ParagraphPlan` doesn't have access to `evidence_map` or sibling paragraphs.

---

## R4 — How is `requirement_ids` validated against `requirement_items`?

**Decision**: Validation happens at TWO levels, both lightweight:

- **Schema level** (parse time on `ContentPlan`): no cross-reference check. `paragraphs[*].requirement_ids` accept any short string. This keeps the model decoupled from `RequirementExtraction`.
- **Stage level** (`plan_content.parse_response`): after `ContentPlan.model_validate(data)` succeeds, the stage additionally verifies each `paragraphs[*].requirement_ids` entry exists in `state.requirements.requirement_items` (when both are present). On mismatch, raises `ValueError` with the paragraph index and the offending ID. This is the same defensive-check pattern the existing parse_response uses for `sections[*].evidence_refs` against `evidence_map.items`.

**Rationale**:
- Avoids coupling `ContentPlan` to `RequirementExtraction` (they're separate models on separate state fields).
- Spec FR-030 is satisfied: stale references RAISE — operators see clearly which paragraph and which ID. The error message format mirrors the existing claim-not-in-evidence-map error.
- Replay/debugging paths that load `ContentPlan` JSON directly skip the stage-level check (no `state.requirements` available) — acceptable because they're not running the pipeline, just inspecting the artifact.

**Alternatives considered**:
- Embed the full `requirement_items` set inside `ContentPlan` (so the model validator has access): rejected — duplicates state across two models, breaks the existing pattern.
- Pass `requirement_items` via a Pydantic context: rejected — context-based validation is fragile and uncommon in this codebase.
- Skip the check entirely: rejected — spec FR-030 explicitly requires the test.

---

## R5 — Field defaults for `max_claims` and `max_tools`

**Decision**: Both are required (no default) on `ParagraphPlan`. The planner LLM MUST emit them per paragraph based on the paragraph's purpose. Field constraints: `max_claims: int = Field(..., ge=1, le=8)`; `max_tools: int = Field(..., ge=0, le=12)`.

**Rationale**:
- Required fields force the planner to think about the appropriate density per paragraph (instead of letting it ride on a flat global cap). This is the central value of the feature.
- The schema-time bounds (1..8 for claims, 0..12 for tools) catch out-of-range values immediately.
- The opening-paragraph constraint `max_claims ∈ {1, 2}` is enforced by the `ContentPlan`-level validator (R3), not the field bound — the field allows 1..8 for non-opening paragraphs.

**Alternatives considered**:
- Default `max_claims=3`, `max_tools=4` (matching `writer_rules.tool_density_max`): rejected — would let the planner skip thinking about appropriate density per paragraph.
- Optional fields that fall back to `writer_rules` global cap: rejected for the same reason.

---

## R6 — Writer-prompt format: how is the per-paragraph plan surfaced?

**Decision**: A new helper `_format_paragraphs_block(plan: ContentPlan) -> str` in `stages/write_letter.py` renders one block per `ParagraphPlan`, formatted as:

```
# Paragraph Plan
## Paragraph 1: opening
- main_message: Lead with infrastructure-builder identity backed by scaled-platform results.
- requirement_ids: [R1, R3]
- evidence_refs: [Built scalable Python ML inference platforms]
- emphasise: [platform reliability]
- deemphasise: [biomedical domain depth]
- max_claims: 1
- max_tools: 0

## Paragraph 2: platform_credibility
- main_message: ...
- ...

(letter_thesis when set: "<thesis text>")
```

The block is emitted ONLY when `plan.paragraphs` is non-empty. When empty (legacy plan), the block is omitted; the writer falls back to the existing `# Role Positioning` block and the serialised `ContentPlan` JSON content (current behaviour from feature 008/010).

**Rationale**:
- Mirrors the existing `_format_positioning_block` (feature 008) and `_format_writer_rules_block` (feature 008) idioms in `write_letter.py` — operators reading the constructed prompt see a consistent shape.
- Per-paragraph rendering means the LLM reads paragraph N's plan immediately before its own task to produce paragraph N's prose.
- `max_claims` and `max_tools` listed per paragraph are explicit, not buried in the JSON dump — the LLM can pick them up reliably.
- Omitting the block when `paragraphs` is empty is the graceful-degradation path for legacy `ContentPlan` artifacts (FR-022).

**Alternatives considered**:
- Render the new fields inside the existing `# Content Plan` JSON dump only: rejected — the LLM is less reliable at extracting per-field values from deeply-nested JSON than from a plain text block.
- Add a new tool-call schema for paragraph-by-paragraph generation: rejected — overkill for this feature; the writer remains a single `{text, mode}` call.

---

## R7 — Per-paragraph `max_tools` override of `writer_rules.tool_density_max`

**Decision**: Per-paragraph `max_tools` always OVERRIDES the global cap for that paragraph, regardless of which is stricter. The writer prompt explicitly states: "When a paragraph's plan specifies `max_tools`, that value is the cap for THIS paragraph; the global `writer_rules.tool_density_max` does NOT apply."

**Rationale**:
- Spec FR-009: "OVERRIDING the global writer_rules.tool_density_max for this paragraph specifically."
- The planner has paragraph context (purpose, requirement, emphasise/deemphasise); a global cap can't reflect that.
- Symmetric in both directions: a "platform_credibility" paragraph may legitimately need `max_tools=6`; a "motivation" paragraph may need `max_tools=0`. The global cap can't accommodate both.
- The hiring review's `tool_density` dimension (feature 008) continues to evaluate the rendered letter — but it sees the planned `max_tools` per paragraph (via the content-plan summary, feature 009) and judges adherence to the PER-paragraph cap rather than the global one.

**Alternatives considered**:
- Use `min(per_paragraph, global)`: rejected — defeats the planner's per-paragraph reasoning when the planner wants a higher cap (e.g., a deliberately-detailed credibility paragraph).
- Use `max(per_paragraph, global)`: rejected — defeats the planner's reasoning when the planner wants a stricter cap (e.g., opening with `max_tools=0`).

---

## R8 — Auto-schema propagation and the planner tool schema

**Decision**: Zero manual schema editing. The planner stage already calls `ContentPlan.model_json_schema()` at line 103 of `stages/plan_content.py`. Adding `paragraphs: list[ParagraphPlan]` to `ContentPlan` propagates automatically into the LLM's tool input schema — including the field constraints on `max_claims` and `max_tools` (Pydantic emits `minimum`/`maximum` in JSON Schema).

**Rationale**:
- The pattern is established (features 008/010 both used auto-schema propagation successfully).
- Anthropic's tool-use respects JSON Schema constraints strictly — `max_claims < 1` or `> 8` from the LLM raises at parse time via the field's `ge=1, le=8`.
- Optional fields with `Field(default_factory=list)` or `| None` defaults emit as optional in the schema — the LLM may omit them without breaking parse.

**Alternatives considered**:
- Hand-edit the tool schema: rejected — duplicates information; risks drift between Pydantic model and the LLM contract.

---

## R9 — Hiring-review interaction: does any code change?

**Decision**: No hiring-review code changes. Feature 009's content-plan summary block in `hiring_review.build_prompt` already serialises the `ContentPlan` object (titles, key_claims, role_positioning, known_gaps). With `paragraphs` and `letter_thesis` added to the model, the summary block could OPTIONALLY surface them too — but the spec (FR-018) explicitly says hiring review is unchanged. Operators benefit from the richer plan visible in the trace span's input metadata (Langfuse) when observability is enabled — that visibility flows automatically without code change because the entire ContentPlan model is dumped into the existing span input.

**Rationale**:
- Spec FR-018 is explicit: "Hiring-review behaviour MUST be unchanged in shape."
- Adding the new fields to the hiring-review prompt's summary block would be an enhancement, but it's out of scope for this feature.
- The hiring-review prompt content STAYS THE SAME — its prompt-hash does NOT flip in `jobagent prompts sync`. Only `planner.md` and `writer.md` flip. (Predicted output: "2 created, 8 unchanged".)

**Alternatives considered**:
- Extend hiring_review.build_prompt to surface `letter_thesis` and per-paragraph `main_message`: rejected — out of scope per FR-018. Reserve for a follow-up feature if reviewer judgements would benefit.

---

## R10 — Test surface mapped to spec FRs

| Test (suggested name) | FR(s) covered | File |
|---|---|---|
| `test_paragraph_plan_main_message_is_single_string` | FR-004, FR-024 | `tests/unit/test_plan_content.py` |
| `test_opening_paragraph_main_message_references_role_family` | FR-011, FR-025, SC-003 | same |
| `test_paragraph_plan_evidence_refs_exceeding_max_claims_raises` | FR-010, FR-027 | same |
| `test_opening_paragraph_max_claims_must_be_one_or_two` | FR-012 | same |
| `test_paragraph_plan_unknown_field_forbidden` | FR-023, FR-029 | same |
| `test_paragraph_requirement_ids_unknown_id_raises_in_parse_response` | FR-005, FR-030 | same (stage-level test) |
| `test_legacy_content_plan_without_paragraphs_loads_with_defaults` | FR-022, FR-028 | same |
| `test_writer_prompt_surfaces_paragraph_max_claims_and_max_tools` | FR-016, FR-026, SC-006 | `tests/unit/test_write_letter.py` |
| `test_writer_prompt_omits_paragraph_block_when_paragraphs_empty` | FR-022 backward compat for writer | same |

9 new tests total. Each maps to one or more spec FRs. The MLflow / Langfuse non-interference invariant (SC-007) is structurally guaranteed and verified by the existing 254-test suite continuing to pass.

---

## Open questions resolved

- "Does Pydantic v2 `@model_validator(mode='after')` see all parsed fields?" — Yes; `self` is the fully-parsed model instance.
- "Will the auto-generated tool schema correctly emit `ge=1, le=8` field bounds?" — Yes; Pydantic v2 emits these as `minimum`/`maximum` in the JSON Schema, which Anthropic's tool-use respects.
- "Does adding `paragraphs: list[ParagraphPlan]` to `ContentPlan` break the writer's existing `model_dump_json()` call?" — No; the new field serialises additively. The writer's prompt block layout adds the paragraph plan rendering on top of the existing JSON dump.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
