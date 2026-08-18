# Quickstart: Role-Positioned Prompting

**Feature**: 008-role-positioned-prompting
**Audience**: operators who want to see how the new positioning behaviour shows up in a real run.

---

## 1. What changed for operators?

Nothing in your daily workflow:
- Same CLI: `jobagent run --job ... --template ...`.
- Same output files in `outputs/<run_id>/`.
- Same MLflow tags, same Langfuse spans.

What's different is **what the letter looks like**:
- The opening paragraph now leads with the role's primary thesis (not your strongest evidence).
- Tool lists are trimmed; system-level outcomes get more room.
- No "expert-level / world-class / 10x / ..." phrasing.
- Secondary-domain experience appears briefly, not as the lead.

And there's one new visible thing in artefacts:
- `artifacts/content_plan.json` now contains a `role_positioning` block. This is the planner's explicit decision; you can read it to understand why the letter was framed the way it was.

---

## 2. New configuration (optional)

Add to any starter template YAML if you want to tune the writer:

```yaml
writer_rules:
  tool_density_max: 4              # max distinct tool/tech names per paragraph (default 4)
  banned_phrases:                  # never produced by the writer; flagged by the reviewer
    - expert-level
    - deep expertise
    - world-class
    - guru
    - rockstar
    - 10x
    - ninja
```

Defaults are applied automatically when the block is absent.

---

## 3. Demo: the AI/ML infrastructure fixture

A new fixture is shipped to demonstrate the GSK-style regression fix:

```bash
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral
```

The fixture job emphasises scalable cloud infrastructure, efficient compute, robust Python software, AI/ML workloads, and agentic systems. The fixture profile includes both strong infrastructure projects AND a notable biomedical-ML project (under `data/examples/profile/projects/`).

### Before this feature (regression scenario)

The opening paragraph used to lead with biomedical-ML — because that was the candidate's most distinctive evidence. The letter felt off-target for an infrastructure hire.

### After this feature

The planner records:

```json
"role_positioning": {
  "primary_role_family": "AI/ML platform engineering",
  "primary_selling_point": "Built and operated scalable Python-based ML inference platforms for software engineering teams.",
  "secondary_selling_points": [
    "Biomedical-data ML modelling experience as adjacent domain context."
  ],
  "topics_to_emphasise": [
    "platform reliability",
    "Python software quality",
    "AI/ML inference scaling",
    "agentic-system orchestration"
  ],
  "topics_to_deemphasise": [
    "biomedical domain depth"
  ],
  "opening_angle": "Lead with infrastructure-builder identity; biomedical context is a brief secondary asset, not the headline."
}
```

The writer opens with infrastructure framing, mentions biomedical context briefly later, caps tool names per paragraph, and uses none of the banned phrases.

---

## 4. Inspecting positioning in the trace

If Langfuse observability is enabled (feature 006) and the prompt registry is in use (feature 007), each stage span carries the prompt name + version of the prompt that fired. The new prompt content has a new hash, so the next `jobagent prompts sync` will create one new Langfuse version of:

- `bewerbungs-agent/planner` (positioning instructions added)
- `bewerbungs-agent/writer` (positioning consumption + writer rules added)
- `bewerbungs-agent/hiring_reviewer` (full job-text context + 5 new dimensions added)

Until you re-sync, the runtime span carries `prompt_version=unsynced` — exactly the visibility signal designed in feature 007.

```bash
uv run jobagent prompts sync --label staging
# → "Summary: 3 created, 7 unchanged, 0 relabeled, 0 failed."
```

---

## 5. Verifying the regression fix manually

1. Pick a job description for a clearly-positioned role family (e.g., the new ML infra fixture).
2. Run `jobagent run` against your normal profile.
3. Open `outputs/<run_id>/artifacts/content_plan.json` and find the `role_positioning` block.
4. Confirm `primary_role_family` matches the actual role (not your strongest-evidence domain).
5. Confirm `secondary_selling_points` is where your strongest-evidence-but-off-domain experience lives.
6. Open `outputs/<run_id>/letter.md` and confirm the opening paragraph leads with the primary role family.
7. Search the letter for any of the banned phrases — should be zero hits.

The hiring-review report (`artifacts/letter_review.md` or via the trace) explicitly grades the five positioning dimensions. If anything's off, the existing targeted-rewrite stage will have already corrected the flagged sections.

---

## 6. Configuring the ban list per template

Different roles call for different tone vocabularies. Override per-template:

```yaml
# data/templates/default_de_neutral.yaml
writer_rules:
  tool_density_max: 4
  banned_phrases:
    - expert-level
    - deep expertise
    - world-class
    - top-tier        # extending the default list
```

Or relaxed for a creative-industry role:

```yaml
# data/templates/creative_en.yaml
writer_rules:
  tool_density_max: 6   # creative jobs may legitimately mention more tools per paragraph
  banned_phrases:
    - expert-level     # still no overclaiming
```

Operators can also override via the existing run-time `--override` flag:

```bash
uv run jobagent run --job ... --template ... \
  --override '{"writer_rules": {"tool_density_max": 6}}'
```

---

## 7. Smoke test checklist (manual)

```bash
# 1. Verify the fixture exists.
ls data/examples/jobs/sample_ml_infrastructure.md
ls data/examples/profile/projects/biomedical_ml_project.md

# 2. Run end-to-end.
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral

# 3. Inspect positioning.
jq '.role_positioning' outputs/*/artifacts/content_plan.json

# 4. Confirm the opening paragraph leads with infra framing.
head -20 outputs/*/letter.md

# 5. Search for banned phrases (should produce no matches).
grep -iE "(expert-level|deep expertise|world-class|guru|rockstar|10x|ninja)" outputs/*/letter.md && echo "REGRESSION" || echo "OK"

# 6. Push new prompt versions to Langfuse.
uv run jobagent prompts sync --label staging
```

If steps 3 confirms infra-first positioning, step 4 shows infra framing in the first paragraph, and step 5 finds nothing, the feature is working end-to-end.
