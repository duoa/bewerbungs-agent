# Quickstart: Narrative Strategy & Story Polish

**Feature**: 013-narrative-strategy-polish
**Date**: 2026-06-05

Operator walkthrough for the new pipeline once feature 013 lands.

---

## 1. What changes for the operator

**The CLI does not change.** No new flags, no new commands. The operator continues to run:

```bash
.venv/bin/jobagent run \
  --job data/aduo/jobs/ds_nb.md \
  --template default_de_neutral \
  --profile-dir data/aduo
```

What's different is **inside the run**:

1. Three new stage lines appear in the progress output:
   ```
   [load_job] done
   [extract_requirements] done
   [load_profile] done
   [select_cv_variant] done
   [build_evidence_map] done
   [role_position] done           ← new (extracted from plan_content)
   [narrative_strategy] done      ← new
   [plan_content] done            ← unchanged surface
   [write_letter] done
   [story_polish] done            ← new (or "[story_polish] skipped" if disabled)
   [hiring_review] done
   [targeted_rewrite] done
   [validate_outputs] done
   ```

2. Two new artefacts appear in `outputs/<run_id>/artifacts/`:
   - `narrative_strategy.json` — the story spine the planner and writer used
   - `story_polish_output.json` — polished text + post-check audit trail (only when story_polish ran)

3. The hiring-review artefact now contains a `craft_dimensions` block with six dimension severities and a `deterministic_findings` block (German over-analogy phrase warnings, when any matched).

4. Wall-clock runtime increases by ~10–30 s (two new LLM calls: narrative_strategy + story_polish).

---

## 2. Inspecting the new artefacts

```bash
jq . outputs/<run_id>/artifacts/narrative_strategy.json
```

Expected shape:

```json
{
  "candidate_story": "Built ML inference platforms for engineering teams, with systems discipline ...",
  "role_story": "Bayer wants a senior engineer who can own the ML platform across multiple product lines ...",
  "bridge": "The candidate's systems-thinking from infrastructure work carries directly into the platform-ownership ...",
  "opening_angle": "Lead with infrastructure-builder identity; bridge to Bayer's platform consolidation goal.",
  "proof_points_to_use": [
    "Built and scaled Python ML inference platform serving 1000 jobs/day",
    "Owned EKS fleets with tight SLOs",
    "..."
  ],
  "proof_points_to_avoid": [
    "Biomedical PhD thesis on gene expression in zebrafish",
    "..."
  ],
  "transfer_framing_guidance": "Mention the research context in one sentence as relevant credibility; do NOT lead with it.",
  "tone_guidance": "Calm, senior, credible, institutional voice. Restrained AIDA — narrative arc only, no marketing copy.",
  "anti_patterns": [
    "Do not open with 'Although my background is...' — defensive framing",
    "Do not use 'direkt übertragbar' — over-constructed transfer phrase"
  ]
}
```

```bash
jq . outputs/<run_id>/artifacts/story_polish_output.json
```

Expected shape on a clean polish:

```json
{
  "polished_text": "Sehr geehrte Damen und Herren, ...",
  "post_check_passed": true,
  "post_check_rationale": "all extracted sets are subsets of draft",
  "used_fallback": false,
  "fallback_reason": null,
  "added_tools": [],
  "added_employers": [],
  "added_numerics": [],
  "diff_char_count": 187
}
```

Expected shape on a fallback (post-check rejected a hallucinated tool):

```json
{
  "polished_text": "<original draft text>",
  "post_check_passed": false,
  "post_check_rationale": "post_check_failed: tools=['Spark'] employers=[] numerics=[]",
  "used_fallback": true,
  "fallback_reason": "post_check_failed: tools=['Spark'] employers=[] numerics=[]",
  "added_tools": ["Spark"],
  "added_employers": [],
  "added_numerics": [],
  "diff_char_count": 0
}
```

Operator action on fallback: inspect the polish-stage Langfuse span to see the LLM's polished output that was rejected. Usually the prompt needs a small tightening or the tool registry needs an additional entry (when the "added" tool is actually present in the draft under a different casing).

---

## 3. Inspecting the extended hiring review

```bash
jq '.craft_dimensions' outputs/<run_id>/artifacts/hiring_review.json
```

Expected:

```json
{
  "story_coherence": {
    "severity": "pass",
    "rationale": "Each paragraph supports the bridge; arc is coherent.",
    "evidence_quote": null
  },
  "transition_smoothness": {
    "severity": "warn",
    "rationale": "Para 2→3 pivots abruptly from infrastructure to biomedical context.",
    "evidence_quote": "Während meiner Promotion in Genexpression ..."
  },
  "over_constructed_language": { "severity": "pass", ... },
  "claim_relevance": { "severity": "pass", ... },
  "aida_restraint": { "severity": "pass", ... },
  "human_readability": { "severity": "pass", ... }
}
```

```bash
jq '.deterministic_findings' outputs/<run_id>/artifacts/hiring_review.json
```

Expected on a clean letter:

```json
[]
```

Expected when an over-analogy phrase is present:

```json
[
  {
    "check_id": "over_analogy_phrase_de",
    "severity": "warn",
    "phrase": "direkt übertragbar",
    "char_start": 421,
    "char_end": 439,
    "context_snippet": "...ist mein Hintergrund direkt übertragbar auf die Anforderungen..."
  }
]
```

When `transition_smoothness` or `aida_restraint` is `warn` or `error`, the aggregate `verdict` will be at minimum `needs_minor_revision` (cannot remain `pass`).

---

## 4. Configuration

The template config gains a new optional block:

```yaml
# templates/default_de_neutral.yaml (excerpt)
narrative_polish:
  narrative_strategy_enabled: true   # default true
  story_polish_enabled: true         # default true
  restrained_aida: true              # default true (only matters for AIDA mode templates)
  tool_registry: null                # optional list[str]; null = use built-in seed
```

When the block is absent, defaults apply (all enabled, restrained AIDA on, built-in tool registry).

### Cost-control: disabling story_polish

For runs where the +1 LLM call is unacceptable:

```yaml
narrative_polish:
  story_polish_enabled: false
```

The hiring reviewer then sees the writer's draft unchanged. Craft dimensions and deterministic findings still run on the unpolished draft.

### Reverting AIDA to pre-feature-013 style

```yaml
narrative_polish:
  restrained_aida: false
```

The `narrative_strategy.tone_guidance` no longer constrains AIDA to the restrained register. The `aida_restraint` craft dimension still evaluates, but rates more permissively.

---

## 5. Langfuse trace inspection

In the Langfuse UI for a feature-013 run, the trace has these new spans:

- `role_position` — prompt + response + thinking budget
- `narrative_strategy` — prompt (with the role positioning block embedded) + response
- `story_polish` — prompt (with the full draft embedded) + response + post-check attributes

The `story_polish` span attributes include:

- `post_check_passed` (true/false)
- `used_fallback` (true/false)
- `fallback_reason` (string when set)
- `diff_char_count` (int)
- `added_tools_count`, `added_employers_count`, `added_numerics_count` (ints)

The `hiring_review` span attributes include:

- `craft_<dim>_severity` for each of the six dimensions
- `deterministic_findings_count` (int)
- `over_analogy_phrases_count` (int)

---

## 6. Failure-mode rehearsal

### 6.1 `narrative_strategy` LLM fails

The stage logs a warning and falls back to a deterministic minimal `NarrativeStrategy` derived from `role_positioning` + the top-6 evidence claims. The run continues. `narrative_strategy.json` is still written.

### 6.2 `story_polish` LLM hallucinates a new tool

Post-check rejects the output. Pipeline falls back to the draft. `story_polish_output.json` records `used_fallback=true` and lists the added tool(s) in `added_tools`. The hiring reviewer sees the original draft (the polish never reaches it).

### 6.3 `narrative_strategy.proof_points_to_avoid` vetoes every paragraph

The planner stage raises `ValueError("narrative_strategy.proof_points_to_avoid vetoed every paragraph — the strategy is incompatible with the plan.")`. This is a planner-bug crash, not a graceful fallback — the run fails. Operator action: inspect `narrative_strategy.json` and `content_plan.json` (the saved planner output before filtering) to see why the strategy is self-vetoing.

### 6.4 Legacy `WorkflowState` snapshot replayed through the new pipeline

Load proceeds (new fields default to `None`). Stages produce the missing fields fresh. The replay succeeds.

---

## 7. Manual smoke test (post-implementation)

After all tasks land:

```bash
.venv/bin/jobagent run \
  --job data/aduo/jobs/ds_nb.md \
  --template default_de_neutral \
  --profile-dir data/aduo

# Inspect the new artefacts
ls outputs/<run_id>/artifacts/
# expect: narrative_strategy.json, story_polish_output.json (in addition to existing artefacts)

jq '.bridge' outputs/<run_id>/artifacts/narrative_strategy.json
# expect: a single sentence linking candidate background to the role

jq '.post_check_passed' outputs/<run_id>/artifacts/story_polish_output.json
# expect: true on a happy-path run

jq '.craft_dimensions | keys' outputs/<run_id>/artifacts/hiring_review.json
# expect: ["aida_restraint","claim_relevance","human_readability","over_constructed_language","story_coherence","transition_smoothness"]

jq '.deterministic_findings | length' outputs/<run_id>/artifacts/hiring_review.json
# expect: 0 on a clean letter, >0 when the writer slipped in an over-analogy phrase
```

The reference letter from feature 012's biomedical-vs-AI-infra fixture (when that feature is shipped) is a good smoke test for the German over-analogy scan, since the failure mode it targets is exactly where over-analogy phrases tend to creep in.
