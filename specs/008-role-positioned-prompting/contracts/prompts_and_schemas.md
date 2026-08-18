# Contract: Prompts, Stage `build_prompt` Inputs, and Schemas

**Feature**: 008-role-positioned-prompting
**Date**: 2026-05-13

This contract is unusual: the feature is mostly prompt content. So the contracts that matter are (a) what each prompt file MUST instruct the LLM to do, (b) what each stage's `build_prompt` MUST place into the user message, and (c) the two minimal schema additions.

---

## 1. `prompts/planner.md` — required content additions

The planner prompt MUST cover at least these instructions, in addition to its existing factuality / no-prose / claim-traceability rules:

1. **Receive and use the job description text**. The prompt explicitly tells the LLM that it is receiving the full job description text (not only the extracted requirements) in a `## Job Description (verbatim)` block, and that the positioning decision is derived from that text first, the extracted requirements second, and the candidate's evidence last.
2. **Produce a `role_positioning` object**. Tells the LLM that the output JSON MUST include a `role_positioning` object with all six fields: `primary_role_family`, `primary_selling_point`, `secondary_selling_points`, `topics_to_emphasise`, `topics_to_deemphasise`, `opening_angle`.
3. **Source-of-truth ordering for the positioning decision**. The prompt explicitly states: derive `primary_role_family` from the job text; if the candidate's strongest evidence does not match that family, the candidate's strongest evidence goes into `secondary_selling_points`, NOT into `primary_selling_point`.
4. **Gap honesty**. If no evidence supports the primary role family, record the gap in `known_gaps` rather than picking a non-matching `primary_selling_point`.
5. **Section ordering should reflect positioning**. The first section's `key_claims` should support the primary role family; sections drawn from `topics_to_deemphasise` should appear last, briefly, and only when the evidence is naturally relevant.
6. **Previous letters are factual evidence, not stylistic exemplars**. The prompt explicitly states that the candidate's prior letters loaded as evidence are sources of past phrasing/facts, not templates to mimic — the writer in the next stage will apply new style rules.
7. **No prose anywhere in the plan**. Existing rule, retained verbatim.

Output: existing `ContentPlan` JSON shape, augmented with the new `role_positioning` sub-object (auto-required because the field is non-Optional inside `RolePositioning`).

---

## 2. `prompts/writer.md` — required content additions

The writer prompt MUST cover at least these instructions, in addition to its existing factuality / language / structure rules:

1. **Consume `role_positioning`**. The prompt tells the LLM that the input JSON has a `role_positioning` field with six entries and explains what each means.
2. **Open with the primary role thesis**. The opening paragraph MUST reference `primary_role_family` and `opening_angle` within its first 400 characters. The opening paragraph MUST NOT lead with content drawn from `secondary_selling_points` or `topics_to_deemphasise`.
3. **System-level outcomes over tool lists**. Each paragraph prefers responsibility / outcome / measurable impact wording over bare enumerations of tools or technologies. Tool names are mentioned only when necessary to disambiguate the work.
4. **Tool-density cap**. No paragraph may contain more than `{tool_density_max}` distinct tool / technology / framework / platform names. The number is interpolated from `writer_rules.tool_density_max` (default 4) by the build_prompt formatter — the prompt file uses `{tool_density_max}` as a placeholder that the build_prompt fills in.
5. **Banned self-rating phrases**. The prompt lists every entry from `writer_rules.banned_phrases` and instructs the LLM to never produce any of them, in any language (German or English). The list is interpolated by build_prompt.
6. **De-emphasis discipline**. Topics in `topics_to_deemphasise` may appear ONLY as a brief secondary mention — never as a paragraph subject, never inside the opening paragraph, never repeated.
7. **No claims absent from the plan**. Restated explicit factuality rule: any concrete claim (skill, tool, employer, project, metric) must trace to an entry in the plan's `key_claims` or `evidence_refs`.

Output: existing `{text, mode}` JSON. No schema change.

---

## 3. `prompts/hiring_reviewer.md` — required content additions

The hiring-reviewer prompt MUST cover:

1. **Receive the full job description**. The prompt tells the LLM that it now receives, in addition to the draft letter and the extracted requirements, a `## Original Job Description (verbatim)` block.
2. **Five new positioning-specific dimensions** added to the standard evaluation list:
   - **role_match** — does the letter match the primary role described in the original job ad?
   - **opening_alignment** — does the opening paragraph reflect the job's top requirements?
   - **secondary_topic_dominance** — do secondary-domain topics dominate the main role?
   - **tool_density** — is the tool density too high (more than `{tool_density_max}` distinct tools per paragraph)?
   - **overclaiming** — does any wording risk overclaiming (banned phrases or unsupported strong claims)?
3. **Severity rules**. The prompt instructs the LLM to assign severity ≥ medium to ANY failure on the five new dimensions when the failure would meaningfully damage the application; severity high when the failure is glaring (e.g., letter opens with the wrong domain).
4. **Quote, don't paraphrase**. When flagging overclaiming the priority_fix MUST quote the exact offending phrase from the letter so the targeted-rewrite stage can target it precisely.
5. **Stay structural**. Existing rules: the review evaluates, does not rewrite. No new behaviour.

Output: existing `LetterReviewReport` JSON shape. No schema change. The five positioning dimensions ride as additional weakness entries inside `SectionReview.weaknesses`.

---

## 4. `stages/plan_content.build_prompt` — required input additions

The constructed user message MUST contain, in this order:

1. `Config: language=..., mode=..., tone=..., soft_skill_max=...` (existing line).
2. `# Job Description (verbatim)\n<raw_job_text>` — **NEW**. The full text from `state.job_context.raw_job_text`. If absent, the line says `(unavailable)`.
3. `# Extracted Requirements\n<...>` (existing block, possibly renamed).
4. `# Available Evidence Claims\n<...>` (existing block).
5. `# Why this company\n<...>` (existing block).
6. `# Instructions\n<contents of prompts/planner.md>` (existing).
7. `IMPORTANT: ...` reminders (existing).

No removal of any existing block; the job description is added between config and requirements so the LLM reads positioning context before it reads its tasks.

---

## 5. `stages/write_letter.build_prompt` — required input additions

The constructed user message MUST contain a `# Role Positioning` block formatted from `content_plan.role_positioning` (when present), AND a `# Writer Rules` block formatted from `state.config.writer_rules`:

```
# Role Positioning
- primary_role_family: <value>
- primary_selling_point: <value>
- secondary_selling_points: <bullet list, or "(none)">
- topics_to_emphasise: <bullet list>
- topics_to_deemphasise: <bullet list, or "(none)">
- opening_angle: <value>

# Writer Rules
- tool_density_max: <int>
- banned_phrases: <comma-joined list>
```

These blocks are inserted into the user message before the existing content-plan JSON block, so the LLM reads positioning context first and then the structured plan.

The placeholders `{tool_density_max}` and `{banned_phrases}` inside `prompts/writer.md` are resolved by Python `str.format(...)` in `build_prompt` (or simple string substitution); the prompt file itself uses placeholders so it remains the source of truth and the values come from config.

---

## 6. `stages/hiring_review.build_prompt` — required input additions

The constructed user message MUST add one new block:

```
## Original Job Description (verbatim)
<state.job_context.raw_job_text>
```

inserted between the existing "## Role Requirements" block and "## Evaluation Dimensions" block. The dimensions list MUST include the five new positioning dimensions (`role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`) in addition to whatever dimensions are configured in `config.review_config.dimensions`.

If `state.job_context` is None (test-only path), the block reads `(job description unavailable — base evaluation on requirements only)`.

---

## 7. Schema additions (recap from data-model.md)

| Model | Field | Type | Default | Required at parse |
|---|---|---|---|---|
| `RolePositioning` (NEW) | `primary_role_family` | `str` | — | yes |
| `RolePositioning` | `primary_selling_point` | `str` | — | yes |
| `RolePositioning` | `secondary_selling_points` | `list[str]` | `[]` | no |
| `RolePositioning` | `topics_to_emphasise` | `list[str]` | `[]` | no |
| `RolePositioning` | `topics_to_deemphasise` | `list[str]` | `[]` | no |
| `RolePositioning` | `opening_angle` | `str` | — | yes |
| `ContentPlan` | `role_positioning` | `RolePositioning \| None` | `None` | no |
| `WriterRules` (NEW) | `tool_density_max` | `int (1..20)` | `4` | no |
| `WriterRules` | `banned_phrases` | `list[str]` | 7 entries | no |
| `StarterTemplate` | `writer_rules` | `WriterRules` | factory | no |
| `MergedConfig` | `writer_rules` | `WriterRules` | factory | no |

`extra="forbid"` on `RolePositioning` and `WriterRules`. Both `ContentPlan` and `MergedConfig` already have `extra="forbid"` (existing).

---

## 8. Non-interference contract

The following behaviours MUST be observably unchanged after this feature:

- `jobagent run` exit codes (FR-019).
- MLflow run-level params (`run_id`, `model`, `template_id`, `thinking_enabled_global`, etc.) — same set, same names.
- MLflow per-stage tags — same names. The new prompt-hash values WILL differ (planner.md / writer.md / hiring_reviewer.md edited → hashes change). Tag NAMES unchanged; values reflect the new content. This is the correct, intended observability of the change.
- MLflow metrics (`evidence_count`, `gaps_count`, `letter_char_count`, `validation_passes`, `rewrite_count`) — same names; values reflect new letter content.
- Langfuse trace shape — one parent trace per run, sibling spans for parallel branches, no new spans, no new metadata field names. The `prompt_content_hash` field per span will reflect the new hashes.
- Langfuse prompt-registry (feature 007) — editing prompt files = expected new-version path. Operator runs `jobagent prompts sync` to push.
- The full pipeline graph topology — unchanged.
- The set of output artefacts (`letter.md`, `cv_tailored.md`, `artifacts/*.json`) — unchanged. `artifacts/content_plan.json` continues to contain a `ContentPlan` dump; the dump now includes the new sub-object (additive).

---

## 9. Test surface implied by the contract

| Behaviour to test | Test file | Key assertion |
|---|---|---|
| Planner prompt includes raw job text + positioning instructions | `test_plan_content.py` | substring assertion on build_prompt output |
| Planner parse accepts a content plan whose role_positioning has infra-flavoured primary + biomedical secondary | `test_plan_content.py` | mock LLM JSON → ContentPlan; assert fields |
| Writer prompt includes role_positioning block + writer_rules block | `test_write_letter.py` | substring assertion on build_prompt output |
| Writer parse rejects letter whose opening (first 400 chars) doesn't contain any positioning keyword | `test_write_letter.py` | mock LLM response that misses opening; assert ValueError (or similar) — OR rely on the hiring-review flag (see below) |
| Hiring-review prompt includes the raw job description block | `test_hiring_review.py` | substring assertion on build_prompt output |
| Hiring-review prompt lists the five new dimensions | `test_hiring_review.py` | substring assertion on build_prompt output |
| Hiring-review flags role_match + opening_alignment on mispositioned letter | `test_hiring_review.py` | mock LLM JSON with the two weakness entries; parse → `sections_to_rewrite` contains opening section |
| WriterRules config round-trip via merge_config | `test_config_models.py` | template `writer_rules` overrides survive |
| ContentPlan with `role_positioning=None` still loads (backward compat) | `test_plan_content.py` | construct ContentPlan without the field; should succeed |

Note: writer prompt enforcement of the rules at runtime is via prompt instruction, not via parser rejection — so the writer test focuses on what's in the prompt, not what the parser rejects. The hiring-review stage is the safety net.
