# Contract: Schemas, Prompts, and Stage Formatters

**Feature**: 010-weighted-requirements-positioning
**Date**: 2026-05-26

Three contracts: (a) the Pydantic schema additions, (b) the required content changes to the three prompt files, (c) the required `build_prompt` formatter changes in three stages.

---

## 1. Pydantic schema contract (recap from data-model.md)

### 1.1 New enums (`state.py`)

```python
class Priority(str, Enum): high | medium | low
class RequirementCategory(str, Enum): core | technical | collaboration | domain | optional
class EvidenceNeeded(str, Enum): required | preferred | optional
```

### 1.2 New model: `RequirementItem` (`state.py`)

```python
class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1, max_length=16)
    text: str = Field(..., min_length=1)
    priority: Priority
    category: RequirementCategory
    evidence_needed: EvidenceNeeded
    source_excerpt: str | None = Field(default=None, max_length=200)
```

### 1.3 Evolved `RequirementExtraction` (`state.py`)

- New field: `requirement_items: list[RequirementItem] = Field(default_factory=list)` (appended at end)
- New validator (`mode="after"`): enforces unique `id` across `requirement_items`
- New validator (`mode="after"`): back-fills `all_requirements` from `requirement_items` when the legacy list is absent

### 1.4 Evolved `RolePositioning` (`state.py`)

- `model_config = ConfigDict(populate_by_name=True, extra="forbid")`
- Renamed fields with input aliases:
  - `role_family: str = Field(..., alias="primary_role_family")`
  - `emphasise: list[str] = Field(default_factory=list, alias="topics_to_emphasise")`
  - `deemphasise: list[str] = Field(default_factory=list, alias="topics_to_deemphasise")`
- New field: `risky_or_gap_areas: list[str] = Field(default_factory=list)`
- Unchanged: `primary_selling_point: str`, `secondary_selling_points: list[str]`, `opening_angle: str`

---

## 2. `prompts/requirements.md` — required content changes

The requirements prompt MUST be extended to instruct the LLM about `requirement_items`. The existing instructions for the legacy summary fields (`core_requirement`, `technical_requirements`, etc.) MUST remain so the LLM continues to produce them in the same shape.

Required additions:

1. **New section "Weighted requirement items"** explaining:
   - Produce a `requirement_items` array containing every distinct requirement extracted from the job description.
   - For each item provide: a short stable `id` (`R1`, `R2`, ... — your choice, but unique within the response); the verbatim `text` of the requirement; a `priority` from {`high`, `medium`, `low`} based on how strongly the job ad emphasises it; a `category` from {`core`, `technical`, `collaboration`, `domain`, `optional`}; an `evidence_needed` from {`required`, `preferred`, `optional`}; and OPTIONALLY a `source_excerpt` (verbatim ≤200-char fragment from the job text that anchors the requirement).

2. **Priority calibration guidance**:
   - `high` — top one or two responsibilities the job ad emphasises (e.g., listed first, repeated, called "core" or "primary")
   - `medium` — solid mid-tier expectations explicitly listed
   - `low` — nice-to-haves or context-only mentions

3. **Evidence-needed calibration guidance**:
   - `required` — a hiring manager would expect to see clear evidence in the cover letter
   - `preferred` — strong evidence helps but isn't strictly necessary
   - `optional` — a brief mention or acknowledgement suffices

4. **Reminder**: also produce the legacy summary fields (`core_requirement`, `technical_requirements`, ...) so existing downstream consumers continue to work. The legacy `all_requirements` field MAY be left empty — the parser back-fills it from `requirement_items`.

---

## 3. `prompts/planner.md` — required content changes

Two small additions:

1. **Read `requirement_items` when present** — the planner's instructions section already mentions reading job requirements. Add: "When `requirement_items` is provided, treat it as the priority-ordered source of truth. Sections in your plan should cover `high`-priority items first and ensure each `required` evidence_needed item has at least one supporting claim."

2. **Use the new `RolePositioning` field names**:
   - `role_family` (was `primary_role_family`)
   - `emphasise` (was `topics_to_emphasise`)
   - `deemphasise` (was `topics_to_deemphasise`)
   - + a new bullet: `risky_or_gap_areas` — topics the writer should treat carefully or avoid because the candidate has no strong evidence (or alignment is weak in a way that could backfire)

3. **Honest gap rule** (existing): when no evidence supports a `high`-priority requirement, record the gap in `evidence_map.known_gaps` (existing field), NOT by downgrading the requirement. Additionally, list the topic in `RolePositioning.risky_or_gap_areas` so the writer treats it carefully.

The existing source-of-truth ordering, no-prose rule, and previous-letters-are-evidence-not-exemplars instructions are preserved verbatim.

---

## 4. `prompts/hiring_reviewer.md` — required content changes

The reviewer prompt's content-plan summary block (added by feature 009) already surfaces `role_positioning` sub-fields. Two small additions:

1. **Field-name update** — the prompt mentions reading positioning sub-fields; update the example field names to match the new canonical names (`role_family`, `emphasise`, `deemphasise`).

2. **Mention `risky_or_gap_areas`** — extend the "Six positioning-specific dimensions" section's `critical_requirements_underweighted` bullet (added by feature 009) to note: "When a critical requirement is listed in the plan's `risky_or_gap_areas`, the reviewer should evaluate whether the letter handles it appropriately (brief, factual acknowledgement OR omission) — not flag it as underweighted."

The five other dimensions and the existing severity/strict-constraint sections are preserved verbatim.

---

## 5. `stages/extract_requirements.py::build_prompt` and `parse_response`

`build_prompt` is unchanged in code — it loads the (newly-edited) `requirements.md` prompt and constructs the user message. No code edit.

`parse_response`: unchanged in signature; the validators on `RequirementExtraction` enforce uniqueness and back-fill on parse. The existing assertion that `core_requirement` is non-empty stays. One additive guard:

```python
def parse_response(data: dict[str, Any]) -> RequirementExtraction:
    core = data.get("core_requirement", "")
    if not core or not core.strip():
        raise ValueError("core_requirement is empty — LLM must extract a core job requirement.")
    return RequirementExtraction.model_validate(data)  # validators run inside
```

Backward compat: legacy payloads without `requirement_items` parse cleanly because the field defaults to `[]`; both new validators are no-ops when the items list is empty.

---

## 6. `stages/plan_content.py::build_prompt`

Two contract additions:

### 6.1 Render `requirement_items` (when present) in priority order

The existing `# Job Requirements` block is built from `requirements.core_requirement`, `requirements.technical_requirements`, etc. Add: when `state.requirements.requirement_items` is non-empty, prepend (or replace) a new block:

```
# Weighted Requirements (priority-ordered)
- [R1, priority=high, evidence=required, category=core] Design and operate scalable cloud infrastructure for AI/ML workloads
  source: "Design and operate scalable cloud infrastructure..."
- [R2, priority=high, evidence=required, category=technical] Build agentic systems that orchestrate multi-step LLM and tool-use workflows
- [R3, priority=medium, evidence=preferred, category=collaboration] Mentor mid-level engineers
- [R4, priority=low, evidence=optional, category=domain] Familiarity with biomedical or life-sciences data
```

Sort by `priority` (high → low) then by id. Include `source_excerpt` (when present) on a continuation line, quoted, truncated to 200 chars.

When `requirement_items` is empty (legacy state), keep the existing `# Job Requirements` block as the fallback — guarantees zero regression for tests and legacy paths.

### 6.2 No change to RolePositioning emission

The planner's tool schema is `ContentPlan.model_json_schema()` — it picks up the new field names automatically. No code change in `plan_content.py` for positioning emission.

---

## 7. `stages/hiring_review.py::build_prompt`

One additive line in the existing content-plan summary block (feature 009).

The current builder emits (within the `## Content Plan` block):

```
Role Positioning:
- primary_role_family: <value>          ← UPDATE the label string to "role_family"
- primary_selling_point: <value>
- secondary_selling_points: <list>       (when non-empty)
- opening_angle: <value>
- topics_to_emphasise: <list>            ← UPDATE label to "emphasise"
- topics_to_deemphasise: <list>          ← UPDATE label to "deemphasise"
```

Add ONE new conditional line:

```
- risky_or_gap_areas: <list>             ← NEW; omit entirely when list is empty
```

Label-string updates are required so the prompt mentions the canonical field names the LLM should reason about. The graceful-omission discipline from feature 009 is preserved — empty optional lists are silently dropped from the prompt.

---

## 8. Non-interference contract

Unchanged from features 008/009:

- `jobagent run` exit codes unchanged.
- MLflow tag / metric NAMES unchanged. The per-stage `prompt_hash` VALUES for `requirements`, `planner`, and `hiring_reviewer` will flip naturally because those three prompt files change — expected, correct signal.
- Langfuse trace topology unchanged. The same three prompt-content-hashes flip on the corresponding stage spans.
- Langfuse prompt-registry: next `jobagent prompts sync` reports `3 created, 7 unchanged` — the created ones are `bewerbungs-agent/requirements`, `bewerbungs-agent/planner`, `bewerbungs-agent/hiring_reviewer`.
- Pipeline graph topology, the set of output artefacts, the writer / `targeted_rewrite` / `validate` stages: all unchanged.

---

## 9. Test surface implied by the contract (recap from research.md §R10)

13 new tests across three existing test files:

| File | Tests |
|---|---|
| `tests/unit/test_extract_requirements.py` | 5 tests (mocked-LLM parsing, defaults, invalid priority, legacy payload, duplicate IDs) |
| `tests/unit/test_plan_content.py` | 5 tests (RolePositioning new field names, RolePositioning aliases, risky_or_gap_areas defaults, unknown field forbidden, planner build_prompt renders weighted items + AI/ML-infra fixture regression test) |
| `tests/unit/test_hiring_review.py` | 2 tests (build_prompt surfaces risky_or_gap_areas when present; omits when empty) |
| (extension to feature 009's existing `test_role_positioning_includes_role_positioning_when_present`) | update the assertion strings to reference new field names |
