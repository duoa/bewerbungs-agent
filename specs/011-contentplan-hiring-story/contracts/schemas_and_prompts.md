# Contract: Schemas, Prompts, and Stage Formatters

**Feature**: 011-contentplan-hiring-story
**Date**: 2026-05-26

Four contracts: (a) the Pydantic schema additions, (b) the required content changes to `prompts/planner.md` + `prompts/writer.md`, (c) the required `build_prompt` formatter changes in `plan_content.py` + `write_letter.py`, (d) the stage-level cross-reference check that supplements model-level validation.

---

## 1. Pydantic schema contract (recap from data-model.md)

### 1.1 New model: `ParagraphPlan` (`state.py`)

```python
class ParagraphPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(..., min_length=1)
    main_message: str = Field(..., min_length=1, max_length=300)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    emphasise: list[str] = Field(default_factory=list)
    deemphasise: list[str] = Field(default_factory=list)
    max_claims: int = Field(..., ge=1, le=8)
    max_tools: int = Field(..., ge=0, le=12)
```

### 1.2 Evolved `ContentPlan` (`state.py`)

Append two new fields:
```python
letter_thesis: str | None = Field(default=None, max_length=300)
paragraphs: list[ParagraphPlan] = Field(default_factory=list)
```

Plus three new `@model_validator(mode="after")` checks per data-model.md §3:
- `_validate_evidence_refs_within_max_claims`
- `_validate_opening_paragraph_max_claims` (constrains `paragraphs[0].max_claims` to `{1, 2}`)
- `_validate_paragraph_evidence_refs_in_evidence_map`

---

## 2. `prompts/planner.md` — required content additions

The planner prompt MUST be extended to instruct the LLM about the new hiring-story structure. The existing sections (Source-of-truth ordering, Required output: role_positioning, Special cases, Section ordering, Previous letters note, Using weighted requirement items, Rules) MUST remain — the new instructions are additive.

Add a new top-level section "Hiring-story structure (feature 011)":

1. **Letter thesis** — produce a `letter_thesis` field at the top of `ContentPlan`: ONE sentence (≤ 300 chars) stating the candidate's case for THIS role. This is the headline a hiring manager could repeat back. Examples (for an AI/ML infra role): "Built and scaled Python-based ML inference platforms for engineering teams, with the systems discipline to keep on-call rotations boring."

2. **Paragraphs (ordered)** — produce a `paragraphs` array. Each entry is one paragraph the cover letter will contain. The array is ordered; index 0 is the opening paragraph.

3. **Per-paragraph fields**:
   - **purpose**: short label (e.g., `opening`, `platform_credibility`, `infrastructure_experience`, `working_style`, `motivation`, `closing`). Open vocabulary; pick what fits the story.
   - **main_message**: the ONE core idea this paragraph delivers, as one sentence (≤ 300 chars). NOT a list, NOT a paragraph draft. This is what the writer must convey.
   - **requirement_ids**: list of `RequirementItem.id` values from the `# Weighted Requirements` block that this paragraph specifically addresses. May be empty for purely framing paragraphs (motivation, closing). Each id MUST exist in the weighted-requirements input.
   - **evidence_refs**: list of claim texts from the evidence map that anchor this paragraph. Each must equal an existing `evidence_map.items[*].claim`.
   - **emphasise**: list of topic names the writer should foreground IN THIS PARAGRAPH (complements the plan-level `role_positioning.emphasise`).
   - **deemphasise**: list of topic names the writer should downplay IN THIS PARAGRAPH.
   - **max_claims**: integer 1..8. The hard upper bound on distinct claims the paragraph may express. Choose deliberately per purpose:
     - opening: 1 or 2
     - credibility / experience: 2–4
     - working_style: 2–3
     - motivation / closing: 1–2
   - **max_tools**: integer 0..12. The hard upper bound on distinct tool/technology names the paragraph may name. OVERRIDES the global writer rules for this paragraph specifically.
     - opening: usually 0–2 (avoid tool-soup openings)
     - credibility / platform: may be higher (4–6) when the paragraph's job is to name the stack
     - motivation / closing: usually 0

4. **Opening paragraph rule** — `paragraphs[0]` MUST reflect the `role_positioning.role_family` and `role_positioning.opening_angle`. Its `main_message` should reference the role family or the opening angle in substance. `paragraphs[0].max_claims` MUST be 1 or 2.

5. **High-priority requirements get dedicated paragraphs** — every `requirement_items` entry with `priority=high` AND `evidence_needed=required` SHOULD appear in some paragraph's `requirement_ids`. The planner SHOULD give each high-priority requirement its own paragraph when possible, rather than bundling several into one.

6. **Reminder**: the legacy `sections` field MAY be left empty when `paragraphs` is populated — the writer prefers `paragraphs`. Producing both is also acceptable (gradual migration).

---

## 3. `prompts/writer.md` — required content additions

The writer prompt MUST be extended to describe the new `# Paragraph Plan` block (rendered by `write_letter.build_prompt`, see §5). All existing rules (role-first opening, system-level outcomes, tool-density cap, banned phrases, no-claim-outside-plan, de-emphasis discipline, language/tone, salutation/closing) remain.

Add a new section "Paragraph plan consumption (feature 011)":

1. **When a `# Paragraph Plan` block is present**, write the letter as the planner's paragraphs in order. Each paragraph in the output corresponds to one entry in the block. Do NOT add extra paragraphs not in the plan; do NOT collapse two planned paragraphs into one.

2. **For each paragraph**:
   - The `main_message` is what your prose for this paragraph MUST deliver. Treat it as the topic sentence's intent.
   - You MAY use up to `max_claims` distinct claims (from `evidence_refs`); fewer is fine, more is forbidden.
   - You MAY use up to `max_tools` distinct tool/technology/framework/platform names in this paragraph. If `max_tools` is 0, name NO tools in this paragraph. This OVERRIDES the global `writer_rules.tool_density_max` for THIS paragraph.
   - Develop topics from the paragraph's `emphasise` list; treat topics in its `deemphasise` list as brief mentions or omit.
   - Anchor your prose to `evidence_refs`; their claim texts trace to passages in the plan's evidence_map.

3. **Letter thesis** — the `letter_thesis` value (when present) is the overall story this letter is telling. Use it to keep the paragraphs cohesive: each paragraph supports the thesis from a different angle.

4. **When the `# Paragraph Plan` block is ABSENT** (legacy plan with only `sections`), fall back to the existing behaviour: read `sections` from the JSON content plan and produce prose per the existing rules. No behaviour change for legacy plans.

The opening rule from feature 008 (opening paragraph references `role_family` + `opening_angle` within first 400 chars) is REINFORCED by the new structure: when `paragraphs[0]` is present, its `main_message` already captures this — the writer's opening prose should faithfully render that message.

---

## 4. `stages/plan_content.py::build_prompt` — required changes

No code change to `build_prompt`. The auto-generated tool schema picks up the new fields (per research §R8). The new planner instructions in `planner.md` are loaded via the existing `load_prompt("planner")` call.

The existing reminder line at the end of the user message (`"You MUST populate the role_positioning object..."`) is UPDATED to also mention the new hiring-story fields:

```python
# OLD:
f"You MUST populate the `role_positioning` object with all seven fields; "
f"derive `role_family` from the job description text first."

# NEW:
f"You MUST populate the `role_positioning` object with all seven fields; "
f"derive `role_family` from the job description text first. "
f"Additionally produce `letter_thesis` (one sentence) and `paragraphs` "
f"(ordered list, each with purpose / main_message / max_claims / max_tools "
f"and the supporting fields). The opening paragraph MUST reflect "
f"role_positioning.role_family and opening_angle."
```

---

## 5. `stages/plan_content.py::parse_response` — required additions

After `ContentPlan.model_validate(data)` succeeds, the stage performs the `requirement_ids` cross-reference check that the model validators cannot do (because `requirement_items` lives on `RequirementExtraction`, not `ContentPlan`).

The check happens INSIDE `plan_content()` (the LangGraph node) rather than `parse_response()` because `parse_response` doesn't receive `WorkflowState`. The node calls `parse_response(response, soft_skill_max=...)` first, then validates `requirement_ids` against `state.requirements.requirement_items`:

```python
def plan_content(state: WorkflowState) -> dict[str, Any]:
    # ... existing LLM call + parse_response ...
    plan = parse_response(response, soft_skill_max=state.config.soft_skill_max)

    # Feature 011: cross-validate paragraph requirement_ids against the
    # workflow's requirement_items.
    if plan.paragraphs and state.requirements is not None:
        valid_ids = {item.id for item in state.requirements.requirement_items}
        if valid_ids:  # only check when requirement_items is populated
            for i, p in enumerate(plan.paragraphs):
                for rid in p.requirement_ids:
                    if rid not in valid_ids:
                        raise ValueError(
                            f"Paragraph {i} ({p.purpose!r}) references "
                            f"requirement_id {rid!r} which is not in the run's "
                            f"requirement_items."
                        )

    # ... existing tracker logging + return ...
    return {"content_plan": plan}
```

---

## 6. `stages/write_letter.py::build_prompt` — required additions

A new helper `_format_paragraphs_block(plan: ContentPlan) -> str` renders the per-paragraph plan, called inside the existing `build_prompt`. Pattern matches the existing `_format_positioning_block` / `_format_writer_rules_block` style.

```python
def _format_paragraphs_block(plan: ContentPlan) -> str:
    """Render the per-paragraph plan when populated; empty string otherwise."""
    if not plan.paragraphs:
        return ""

    lines: list[str] = []
    if plan.letter_thesis:
        lines.append(f"Letter thesis: {plan.letter_thesis}\n")
    lines.append("# Paragraph Plan")
    for i, p in enumerate(plan.paragraphs, start=1):
        lines.append(f"\n## Paragraph {i}: {p.purpose}")
        lines.append(f"- main_message: {p.main_message}")
        if p.requirement_ids:
            lines.append(f"- requirement_ids: {list(p.requirement_ids)}")
        if p.evidence_refs:
            lines.append(f"- evidence_refs: {list(p.evidence_refs)}")
        if p.emphasise:
            lines.append(f"- emphasise: {list(p.emphasise)}")
        if p.deemphasise:
            lines.append(f"- deemphasise: {list(p.deemphasise)}")
        lines.append(f"- max_claims: {p.max_claims}")
        lines.append(f"- max_tools: {p.max_tools}")
    return "\n".join(lines) + "\n\n"
```

The block is inserted into the user message BETWEEN the existing `# Writer Rules` block and the `# Writing Mode Instructions` block:

```python
content = (
    f"Write a cover letter from the structured content plan below.\n\n"
    f"Configuration: language={config.language}, tone={config.tone}, "
    f"mode={config.mode.value}\n\n"
    f"{positioning_block}\n"
    f"{rules_block}\n"
    f"{_format_paragraphs_block(content_plan)}"   # NEW (feature 011)
    f"# Writing Mode Instructions\n{style_instructions}\n\n"
    f"# Writer Instructions\n{writer_instructions}\n\n"
    f"# Content Plan (USE ONLY THESE FACTS)\n```json\n{plan_json}\n```\n\n"
    # ... existing trailer ...
)
```

When `plan.paragraphs` is empty (legacy plan), `_format_paragraphs_block` returns `""` and the prompt structure is identical to feature 010's prompt — zero regression for legacy paths.

---

## 7. Non-interference contract (recap)

Unchanged from features 008/009/010:

- `jobagent run` exit codes unchanged.
- MLflow tag / metric NAMES unchanged. Per-stage `prompt_hash` VALUES flip for `planner` and `writer` only (NOT for `hiring_reviewer` — feature 011 does NOT edit that prompt).
- Langfuse trace topology unchanged. `prompt_content_hash` values flip on the corresponding two stage spans only.
- Langfuse prompt-registry: next `jobagent prompts sync` reports `2 created, 8 unchanged`. The two created are `bewerbungs-agent/planner` and `bewerbungs-agent/writer`.
- Pipeline graph topology, output artefacts, all other stages: unchanged.

---

## 8. Test surface (recap from research.md §R10)

| Behaviour | Test | File |
|---|---|---|
| `main_message` is a single non-empty string ≤ 300 chars | `test_paragraph_plan_main_message_is_single_string` | `tests/unit/test_plan_content.py` |
| Opening paragraph references role_family / opening_angle | `test_opening_paragraph_main_message_references_role_family` | same |
| `evidence_refs > max_claims` raises | `test_paragraph_plan_evidence_refs_exceeding_max_claims_raises` | same |
| Opening `max_claims` ∈ {1, 2} | `test_opening_paragraph_max_claims_must_be_one_or_two` | same |
| Unknown field on ParagraphPlan raises | `test_paragraph_plan_unknown_field_forbidden` | same |
| Unknown requirement_id in stage-level check raises | `test_paragraph_requirement_ids_unknown_id_raises` | same |
| Legacy ContentPlan loads with defaults | `test_legacy_content_plan_without_paragraphs_loads_with_defaults` | same |
| Writer prompt surfaces per-paragraph max_claims + max_tools | `test_writer_prompt_surfaces_paragraph_max_claims_and_max_tools` | `tests/unit/test_write_letter.py` |
| Writer prompt omits paragraph block when paragraphs empty | `test_writer_prompt_omits_paragraph_block_when_paragraphs_empty` | same |

9 new tests total. Existing 254-test suite continues to pass (verifies SC-005 + SC-007 structurally).
