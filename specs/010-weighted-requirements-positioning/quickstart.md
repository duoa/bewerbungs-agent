# Quickstart: Weighted Requirements + Refined Role Positioning

**Feature**: 010-weighted-requirements-positioning
**Audience**: operators who want to understand what becomes visible after this feature merges.

---

## 1. What changes for operators?

Nothing in your daily workflow:
- Same CLI: `jobagent run --job ... --template ...`.
- Same exit codes, same output files, same MLflow tags, same Langfuse trace shape.

What's different is the **structure inside two artefacts**:

- `outputs/<run_id>/artifacts/requirements.json` now contains an additional `requirement_items` array. Each item carries `id` (`R1`, `R2`, ...), `text`, `priority` (`high`/`medium`/`low`), `category` (`core`/`technical`/...), `evidence_needed` (`required`/`preferred`/`optional`), and an optional `source_excerpt` quoting the verbatim job-text fragment that anchored the requirement.

- `outputs/<run_id>/artifacts/content_plan.json` carries a `role_positioning` object whose field names are updated (`role_family`, `emphasise`, `deemphasise`) and which now includes a new `risky_or_gap_areas` list.

The hiring-review evaluation gains awareness of `risky_or_gap_areas` — it knows which topics the planner flagged as risky-to-lean-on, so it doesn't double-flag them as underweighted.

---

## 2. Confirming the new structure lands

```bash
jq '.requirement_items[0]' outputs/*/artifacts/requirements.json
# →
# {
#   "id": "R1",
#   "text": "Design and operate scalable cloud infrastructure for AI/ML workloads",
#   "priority": "high",
#   "category": "core",
#   "evidence_needed": "required",
#   "source_excerpt": "Design and operate scalable cloud infrastructure for AI/ML training and inference, primarily on AWS..."
# }

jq '.role_positioning' outputs/*/artifacts/content_plan.json
# →
# {
#   "role_family": "AI/ML platform engineering",
#   "primary_selling_point": "Built scalable Python ML inference platforms for engineering teams.",
#   "secondary_selling_points": ["Biomedical-ML modelling experience as adjacent context"],
#   "opening_angle": "Lead with infrastructure-builder identity; biomedical briefly.",
#   "emphasise": ["platform reliability", "AI/ML inference scaling"],
#   "deemphasise": ["biomedical domain depth"],
#   "risky_or_gap_areas": ["claims of deep on-call experience without examples"]
# }
```

---

## 3. Backward compatibility in practice

### Legacy `RequirementExtraction` JSON (pre-feature-010)

```bash
# An artifact from a previous run lacks requirement_items entirely.
python -c "
import json
from bewerbungs_agent.models.state import RequirementExtraction
legacy = {'core_requirement': 'Python engineering', 'technical_requirements': ['Python']}
ext = RequirementExtraction.model_validate(legacy)
print('requirement_items:', ext.requirement_items)
print('all_requirements:', ext.all_requirements)
"
# → requirement_items: []
# → all_requirements: [] (the legacy field; preserved as-is)
```

### Feature-008 `RolePositioning` JSON

```bash
python -c "
from bewerbungs_agent.models.state import RolePositioning
old_shape = {
    'primary_role_family': 'AI/ML platform engineering',
    'primary_selling_point': 'Built scalable Python platforms.',
    'topics_to_emphasise': ['platform reliability'],
    'topics_to_deemphasise': ['biomedical domain depth'],
    'opening_angle': 'Lead with infra identity.',
}
rp = RolePositioning.model_validate(old_shape)
print('role_family:', rp.role_family)
print('emphasise:', rp.emphasise)
print('deemphasise:', rp.deemphasise)
print('risky_or_gap_areas:', rp.risky_or_gap_areas)  # defaults to []
"
# → role_family: AI/ML platform engineering
# → emphasise: ['platform reliability']
# → deemphasise: ['biomedical domain depth']
# → risky_or_gap_areas: []
```

Re-saving the loaded model uses the new field names:

```bash
python -c "
from bewerbungs_agent.models.state import RolePositioning
rp = RolePositioning.model_validate({
    'primary_role_family': 'X',
    'primary_selling_point': 'Y',
    'topics_to_emphasise': ['a'],
    'topics_to_deemphasise': ['b'],
    'opening_angle': 'Z',
})
import json
print(json.dumps(rp.model_dump(), indent=2))
"
# → output uses role_family, emphasise, deemphasise (canonical names),
#   plus risky_or_gap_areas: []
```

---

## 4. Pushing the prompt edits to Langfuse Prompt Registry (feature 007)

After merging this feature:

```bash
uv run jobagent prompts sync
# → expected: "Summary: 3 created, 7 unchanged, 0 relabeled, 0 failed."
# → the three created prompts are:
#     bewerbungs-agent/requirements
#     bewerbungs-agent/planner
#     bewerbungs-agent/hiring_reviewer
```

If the summary reports more or fewer than 3 created, investigate with `git diff prompts/` — an unintended prompt was modified.

---

## 5. The deterministic regression guard

Feature 008 introduced the AI/ML infrastructure fixture (`data/examples/jobs/sample_ml_infrastructure.md`) and a biomedical-ML profile project. Feature 010 reuses both, but the test assertion is updated to use the new field names:

```python
def test_planner_produces_infrastructure_first_role_family_on_fixture(...) -> None:
    plan = ContentPlan.model_validate(canned_response)
    rp = plan.role_positioning
    assert rp is not None
    # NEW field name (was primary_role_family)
    family_lower = rp.role_family.lower()
    assert "platform" in family_lower or "infrastructure" in family_lower
    assert "biomedical" not in family_lower
    assert "data science" not in family_lower
    # Biomedical-ML still in secondary_selling_points only
    assert any("biomedical" in s.lower() for s in rp.secondary_selling_points)
    assert "biomedical" not in rp.primary_selling_point.lower()
```

This test FAILS if any future change causes the planner to misclassify an infrastructure role as biomedical data science.

---

## 6. Reading the priority-ordered requirements in the planner prompt

If you enable Langfuse observability (feature 006), open a `plan_content` span and inspect the input metadata. The new `# Weighted Requirements (priority-ordered)` block will look like:

```
# Weighted Requirements (priority-ordered)
- [R1, priority=high, evidence=required, category=core] Design and operate scalable cloud infrastructure for AI/ML workloads
  source: "Design and operate scalable cloud infrastructure for AI/ML training and inference, primarily on AWS..."
- [R2, priority=high, evidence=required, category=technical] Build agentic systems for multi-step LLM and tool-use workflows
- [R3, priority=high, evidence=required, category=technical] Write robust, well-tested Python software
- [R4, priority=medium, evidence=preferred, category=technical] Drive efficient compute (vLLM, TGI, batching)
- [R5, priority=medium, evidence=preferred, category=collaboration] Mentor mid-level engineers
- [R6, priority=low, evidence=optional, category=domain] Familiarity with biomedical or life-sciences data
```

The planner's `role_positioning` decision should reflect that ordering: `role_family` matches the `high`-priority items' category (`core`/`technical`), not the `low`-priority biomedical mention.

---

## 7. Smoke test (manual)

```bash
# 1. Run the agent on the AI/ML infrastructure fixture.
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral

# 2. Confirm weighted requirements appear with priorities.
jq '.requirement_items | map({id, priority, category, evidence_needed})' \
  outputs/*/artifacts/requirements.json

# 3. Confirm role_positioning uses the new field names + risky_or_gap_areas.
jq '.role_positioning' outputs/*/artifacts/content_plan.json

# 4. Confirm role_family is infrastructure-flavoured.
jq -r '.role_positioning.role_family' outputs/*/artifacts/content_plan.json | \
  grep -iE "(platform|infrastructure|software)" && echo "OK" || echo "REGRESSION"

# 5. Sync the three updated prompts to Langfuse.
uv run jobagent prompts sync
# → expected: "Summary: 3 created, 7 unchanged, 0 relabeled, 0 failed."
```

If steps 2–4 confirm the weighted structure and the infrastructure-first positioning, and step 5 reports the expected counts, the feature is working end-to-end.
