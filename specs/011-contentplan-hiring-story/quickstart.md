# Quickstart: ContentPlan as a Hiring Story

**Feature**: 011-contentplan-hiring-story
**Audience**: operators who want to understand what changes after this feature merges.

---

## 1. What changes for operators?

Nothing in your daily workflow:
- Same CLI: `jobagent run --job ... --template ...`.
- Same exit codes, same output files.
- Same MLflow tags, same Langfuse trace shape.

What's different is the **structure inside `outputs/<run_id>/artifacts/content_plan.json`**:

```bash
jq '.letter_thesis' outputs/*/artifacts/content_plan.json
# → "Built and scaled Python-based ML inference platforms for engineering
#    teams, with the systems discipline to keep on-call rotations boring."

jq '.paragraphs | length' outputs/*/artifacts/content_plan.json
# → 5  (or however many paragraphs the planner chose)

jq '.paragraphs[0]' outputs/*/artifacts/content_plan.json
# → {
#     "purpose": "opening",
#     "main_message": "I build the AI/ML infrastructure your software engineers ship on top of.",
#     "requirement_ids": ["R1"],
#     "evidence_refs": ["Built scalable Python ML inference platforms"],
#     "emphasise": ["platform reliability"],
#     "deemphasise": ["biomedical domain depth"],
#     "max_claims": 1,
#     "max_tools": 0
#   }
```

The legacy `sections` field is also still there for backward compat; new runs populate both `paragraphs` (canonical going forward) and may leave `sections` empty or populated depending on the planner's behaviour.

---

## 2. Confirming the new structure lands

```bash
.venv/bin/pytest tests/unit/test_plan_content.py -v
.venv/bin/pytest tests/unit/test_write_letter.py -v
```

For a live check with Langfuse (requires credentials set up by features 006/007):

```bash
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral
# → opens the printed langfuse trace URL
# → click the plan_content span; the input metadata shows the planner prompt with
#   the new hiring-story instructions; the output shows letter_thesis + paragraphs
# → click the write_letter span; the input metadata shows the new # Paragraph Plan block
```

---

## 3. The opening-paragraph rule in practice

Feature 008 introduced `role_positioning.role_family` and `role_positioning.opening_angle`. Feature 011 wires the opening paragraph to reflect those values:

```bash
# Run on the AI/ML infrastructure fixture
uv run jobagent run --job data/examples/jobs/sample_ml_infrastructure.md --template default_de_neutral

# Confirm role_family is infrastructure-flavoured (feature 010 invariant)
jq -r '.role_positioning.role_family' outputs/*/artifacts/content_plan.json
# → "AI/ML platform engineering"

# Confirm the opening paragraph's main_message references it
jq -r '.paragraphs[0].main_message' outputs/*/artifacts/content_plan.json
# → "I build the AI/ML infrastructure ..." (or similar — must contain
#   "infrastructure" or "platform" or "AI/ML")
```

The deterministic regression guard `test_opening_paragraph_main_message_references_role_family` asserts on this substring presence.

---

## 4. Per-paragraph density limits

The planner sets `max_claims` and `max_tools` per paragraph. The writer respects them. The hiring-review `tool_density` dimension (feature 008) evaluates the rendered letter against the PER-paragraph caps (visible in the trace via feature 009's content-plan summary).

| Paragraph purpose | Typical `max_claims` | Typical `max_tools` |
|---|---|---|
| `opening` | 1 or 2 | 0–2 |
| `platform_credibility` | 2–3 | 4–6 |
| `infrastructure_experience` | 2–4 | 3–6 |
| `working_style` | 2–3 | 0–2 |
| `motivation` | 1–2 | 0 |
| `closing` | 1–2 | 0 |

Operators can audit the planned caps directly:

```bash
jq '.paragraphs | map({purpose, max_claims, max_tools})' \
  outputs/*/artifacts/content_plan.json
```

---

## 5. Backward compatibility in practice

### Legacy `ContentPlan` JSON (pre-feature-011)

```bash
python -c "
import json
from bewerbungs_agent.models.state import ContentPlan
legacy = {
    'template_id': 't',
    'selected_cv_variant': 'cv_x',
    'mode': 'standard',
    'sections': [{'title': 'role_fit', 'key_claims': ['a'], 'evidence_refs': []}],
}
plan = ContentPlan.model_validate(legacy)
print('letter_thesis:', plan.letter_thesis)
print('paragraphs:', plan.paragraphs)
print('sections:', plan.sections)
"
# → letter_thesis: None
# → paragraphs: []
# → sections: [SectionPlan(...)]  (preserved as-is)
```

Existing tests that construct minimal `ContentPlan` instances continue to pass without modification — the new fields default safely.

### Writer fallback to `sections` when `paragraphs` is empty

When the planner produces a legacy-shape plan (or when an older artifact is reloaded), the writer's `_format_paragraphs_block` returns an empty string and the writer's prompt is structurally identical to the feature 010 prompt. No regression, no change in behaviour for legacy paths.

---

## 6. Pushing the prompt edits to Langfuse Prompt Registry (feature 007)

After merging this feature:

```bash
uv run jobagent prompts sync
# → expected: "Summary: 2 created, 8 unchanged, 0 relabeled, 0 failed."
# → the two created prompts are:
#     bewerbungs-agent/planner  (new hiring-story instructions)
#     bewerbungs-agent/writer   (new # Paragraph Plan consumption instructions)
```

`hiring_reviewer` stays at its previous version — feature 011 does NOT edit it. Same for the other 7 prompts.

---

## 7. Smoke test (manual)

```bash
# 1. Run the agent on the AI/ML infrastructure fixture.
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral

# 2. Confirm letter_thesis is populated.
jq '.letter_thesis' outputs/*/artifacts/content_plan.json
# → a single-sentence string, NOT null

# 3. Confirm paragraphs structure.
jq '.paragraphs | map({purpose, main_message, max_claims, max_tools})' \
  outputs/*/artifacts/content_plan.json

# 4. Confirm opening paragraph references infrastructure framing.
jq -r '.paragraphs[0].main_message' outputs/*/artifacts/content_plan.json | \
  grep -iE "(infrastructure|platform|AI/ML|software)" && echo "OK" || echo "REGRESSION"

# 5. Confirm opening max_claims is 1 or 2.
jq '.paragraphs[0].max_claims' outputs/*/artifacts/content_plan.json
# → 1 or 2 (other values raise at parse time and the run would have failed)

# 6. Push two new prompt versions to Langfuse.
uv run jobagent prompts sync
# → "Summary: 2 created, 8 unchanged, 0 relabeled, 0 failed."

# 7. Confirm the rendered letter has the expected number of paragraphs.
paragraph_count=$(grep -cE '^\S' outputs/*/letter.md)  # rough — counts non-blank-leading lines
echo "Letter paragraphs: $paragraph_count (planned: $(jq '.paragraphs | length' outputs/*/artifacts/content_plan.json))"
```

If steps 2–5 confirm the new structure and the infrastructure-first opening, and step 6 reports `2 created, 8 unchanged`, the feature is working end-to-end.
