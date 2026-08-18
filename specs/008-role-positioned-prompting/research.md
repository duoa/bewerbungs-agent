# Phase 0 Research: Role-Positioned Prompting

**Feature**: 008-role-positioned-prompting
**Date**: 2026-05-13

Resolves implementation-relevant unknowns. Does not re-litigate spec decisions documented in `spec.md > Assumptions`.

---

## R1 — Can the existing `ContentPlan` carry positioning without a schema change?

**Decision**: No. Add one nested Pydantic sub-object (`RolePositioning`) and one optional field (`role_positioning: RolePositioning | None`) on `ContentPlan`. All other planner output stays in the existing fields.

**Rationale**:
- Inspected `ContentPlan` in `src/bewerbungs_agent/models/state.py`. The closest existing concepts are `sections[*].title` (section labels), `assumptions` (free text), and `open_questions` (free text). None of these have the semantics of "primary role family" / "topics to emphasise" / "opening angle". Encoding positioning as free-form text in `assumptions` would defeat the purpose — the writer needs a structured contract to consume reliably.
- Spec FR-021 explicitly permits this case: "Schema additions are permitted ONLY when the existing structures cannot represent the required positioning information." It is met here.
- One additive optional field on the existing model is the smallest possible schema change. `extra="forbid"` on the sub-object keeps unknown keys from drifting in.

**Alternatives considered**:
- Encode positioning as a magic `assumptions` entry like `"positioning: primary=infra, secondary=biomedical"`: rejected — every downstream consumer would need to string-parse, brittle.
- Inject positioning into `sections[0].title`: rejected — confuses two unrelated concepts (section heading vs. role framing).
- Side-channel string field on `WorkflowState`: rejected — the writer reads `ContentPlan`, not `WorkflowState` directly; the writer doesn't see profile data by design.

---

## R2 — Why is the planner's tool schema auto-updated?

**Decision**: No manual schema edit required for the planner stage. `stages/plan_content.py` line 103 already does `schema = ContentPlan.model_json_schema()`. Adding the field to `ContentPlan` propagates automatically to the LLM tool schema.

**Rationale**:
- The auto-generated schema means the LLM is REQUIRED by `tool_choice` to fill the new field (Pydantic schema → Anthropic tool-use input_schema). This is the right enforcement: a planner response without positioning fails schema validation and the existing `parse_response` path raises.
- We make `role_positioning` optional (`| None`) at the Pydantic level so the parse doesn't blow up if the LLM omits it (graceful degrade). The prompt instructions make it required behaviourally.

**Alternatives considered**:
- Make `role_positioning` strictly required (non-Optional): rejected for safety — a strict requirement could cascade-fail older content plans loaded from artifacts during reruns. Optional + prompt-required is the resilient combination.

---

## R3 — How does the writer access `RolePositioning`?

**Decision**: `stages/write_letter.py::build_prompt` already serialises the entire `ContentPlan` (via `model_dump_json` or equivalent formatting) into the user message. Adding the new sub-object means it appears automatically in the prompt context with no code change to that stage's message builder. The prompt file (`prompts/writer.md`) is what gets updated to instruct the LLM to consume the new fields.

**Rationale**:
- Smallest possible code diff. The writer's `build_prompt` already knows how to format a typed `ContentPlan`; adding a new attribute to the model means the new attribute lands in the serialised JSON automatically.
- The writer's tool-use response schema (`_WRITE_SCHEMA`) only contains `text` + `mode` — unchanged. The writer doesn't need a new output field, just new behaviour from the same output shape.

**Alternatives considered**:
- Custom formatter that inserts positioning at a specific spot in the prompt: rejected — adds code for no benefit. The LLM reads the JSON and the prompt instructions together.

---

## R4 — How does `hiring_review` get the full job description?

**Decision**: `stages/hiring_review.py::build_prompt` reads `state.job_context.raw_job_text` and inserts it into the prompt under a new "## Original Job Description" block, before the existing "## Role Requirements" block. No new constructor argument, no new state field, no new data load — `load_job` already populated `job_context.raw_job_text`.

**Rationale**:
- The data is already on `WorkflowState` (loaded by stage 1). The review stage simply reads what it needs.
- The existing isolation rule (review doesn't see profile / CV variants / evidence map) is preserved: only the job text is added, and it's the same text the `extract_requirements` stage already worked from.
- Documented in spec Assumptions; no new data flow as far as the pipeline graph is concerned.

**Alternatives considered**:
- Pass `raw_job_text` via a new constructor argument or a thin wrapper: rejected — `state` is the carrier for everything in this codebase; deviating from that for one field would be inconsistent.
- Re-load the job file inside `hiring_review`: rejected — that would touch the filesystem at review time and would couple the stage to the loader. The state model is the right channel.

---

## R5 — Where do `tool_density_max` and `banned_phrases` live?

**Decision**: A new `WriterRules` Pydantic model attached to both `StarterTemplate` and `MergedConfig`. Default values match spec defaults (FR-007, FR-008). Operators can override per-template YAML. The `utils/merge.py` `base` dict gains a `"writer_rules": template.writer_rules` entry (the now-familiar `extra="forbid"` propagation gotcha from ENGINEERING.md §15).

```python
class WriterRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_density_max: int = Field(default=4, ge=1, le=20)
    banned_phrases: list[str] = Field(default_factory=lambda: [
        "expert-level", "deep expertise", "world-class",
        "guru", "rockstar", "10x", "ninja",
    ])
```

**Rationale**:
- Per FR-022, the lists MUST NOT be hard-coded in prompt files — operators may have a different tone or different industry needs (e.g., a creative-industry candidate may legitimately use phrases banned in tech).
- A nested config model matches the existing `ReviewConfig` and `ObservabilityConfig` patterns; no new convention introduced.
- `tool_density_max` is bounded to a reasonable range so a misconfigured template can't disable the check by setting it to 0 or 9999.

**Alternatives considered**:
- Put writer rules under `review_config`: rejected — they're writer constraints, not review constraints. Conflating would obscure the boundary.
- Top-level `MergedConfig` fields (no sub-model): rejected — would pollute the top-level namespace; a sub-model is consistent with how thinking / tracking / review_config / observability are organised.

---

## R6 — Will the writer mechanically enforce tool density, or only via prompt?

**Decision**: Primary enforcement is via prompt instruction (the LLM is told the cap explicitly). Optional deterministic post-check is OUT of scope for this feature; it can be added later as a validation rule. The hiring-review stage catches violations at severity ≥ medium (FR-012c), which routes through the existing targeted-rewrite path.

**Rationale**:
- Spec Assumptions explicitly say: "The writer's 'no paragraph contains more than N tool names' rule is enforced primarily by prompt instruction. Deterministic post-validation (counting tool names per paragraph) is a useful safety net but is not required for v1."
- Implementing a deterministic tool-name detector well requires a sizeable tool-name corpus + per-language NLP; out of scope for "minimal prompt-and-context feature".
- The review-then-rewrite loop is the existing mechanism for catching writer regressions; we lean on it.

**Alternatives considered**:
- Add a `tool_density` deterministic rule to `validate.py` now: rejected — out of scope per spec Assumptions; deferring keeps the diff focused.

---

## R7 — How is the GSK-style regression test framed without an LLM?

**Decision**: Three test layers, all using mocked LLM:

| Test | What it asserts | LLM mock |
|---|---|---|
| Planner `build_prompt` test | The constructed prompt for the AI/ML infrastructure fixture contains the full job description text, references the positioning instructions, and includes the biomedical-ML evidence as one of many available claims (not the only one). | None — pure prompt-content assertion. |
| Planner `parse_response` test | Given a mocked LLM response with `role_positioning` filled with infrastructure-first values, the parser produces a `ContentPlan` whose `role_positioning.primary_role_family` does not contain "biomedical". | Mock returns canned JSON. |
| Hiring-review `build_prompt` test | The constructed prompt includes `state.job_context.raw_job_text` AND the 5 new positioning dimensions in the dimensions list. | None — pure prompt-content assertion. |
| Hiring-review `parse_response` test | Given a mocked review response that flags the role-match and opening-alignment weaknesses with severity medium, the resulting `LetterReviewReport.sections_to_rewrite` includes the opening section. | Mock returns canned JSON. |

**Rationale**:
- The feature is fundamentally a prompt-content change. Asserting on the constructed prompts (not on LLM behaviour) is what TDD-able and CI-cheap. The behavioural assertion (the LLM actually picks infrastructure-first) needs human eyeballs on real runs, which the operator can do via `jobagent run` on the new fixture — and the Langfuse trace will show the positioning explicitly.
- This pattern matches every other stage test in the codebase: separate `TestBuildPrompt` and `TestParseResponse` classes; no real LLM calls in unit tests.

**Alternatives considered**:
- An integration test that hits the real Anthropic API on the new fixture: rejected — flaky, expensive, not deterministic for CI. The operator runs this manually via the quickstart smoke test.

---

## R8 — Will Langfuse prompt-registry hashes pick up the prompt-file changes automatically?

**Decision**: Yes, with no extra code. Feature 007's `_compute_prompt_hash(prompt_name)` reads the file content at call time; editing `planner.md` / `writer.md` / `hiring_reviewer.md` changes the bytes, hashes change, and the next `jobagent prompts sync` creates one new Langfuse version of each (FR-007 of feature 007, verified by the existing test surface). Runtime stage spans pick up the new hash on the next process start (cache is process-local).

**Rationale**:
- Feature 007's design intentionally treats prompt edits as the trigger for new versions. Feature 008 is exactly the kind of edit it was built for.
- No operator action beyond `jobagent prompts sync` is needed after merging this feature. The runtime resolver will report `prompt_version=<new>` once the synced version exists; it reports `prompt_version=unsynced` between the prompt edit and the sync — which is the correct, visible signal that a sync is owed.

**Alternatives considered**:
- Automate `prompts sync` from a Git hook: out of scope; the user controls when to push to Langfuse.

---

## R9 — Are previous-letter examples in the profile a contamination risk?

**Decision**: The writer prompt explicitly addresses this: it instructs the LLM to follow the new positioning rules even when prior-letter examples (loaded by feature 001 into `InternalKnowledge.previous_letters`) display the now-banned phrasings. Note: the writer never actually sees `InternalKnowledge` — it only sees the `ContentPlan`. So previous-letter contamination can only enter via the *planner*, which DOES see knowledge. The planner prompt is updated to treat previous letters as factual evidence of past phrasing, NOT as exemplars to mimic.

**Rationale**:
- Verified architecturally: the writer's input is `ContentPlan` JSON only. `InternalKnowledge.previous_letters` cannot reach the writer.
- The planner reads previous letters (via `build_evidence_map` → evidence items) as factual support, not stylistic templates. Adding one line to `planner.md` clarifying this is enough.
- This is consistent with spec edge case "A previous run wrote a letter that violates the new constraints, and that letter is now in the profile as a previous_letter example".

**Alternatives considered**:
- Programmatically strip previous-letter exemplars from the evidence: rejected — they're legitimate evidence; the right place to address this is in instructions, not deletion.

---

## R10 — Test surface mapped to spec FRs

| Test | FR(s) covered | File |
|---|---|---|
| `test_planner_prompt_includes_positioning_instructions_and_job_text` | FR-001, FR-002, FR-023 | `tests/unit/test_plan_content.py` |
| `test_planner_parse_accepts_role_positioning_subobject` | FR-001 | same |
| `test_planner_positions_infrastructure_first_on_ml_infra_fixture` | FR-024, SC-001, SC-002 | same (uses canned mock response asserting parse handles it) |
| `test_writer_prompt_includes_positioning_and_writer_rules` | FR-006, FR-007, FR-008 | `tests/unit/test_write_letter.py` |
| `test_writer_opening_leads_with_primary_role_on_canned_response` | FR-006, FR-026, SC-003 | same (asserts the parse rejects/accepts based on opening content) |
| `test_hiring_review_prompt_includes_raw_job_text` | FR-011, FR-020 | `tests/unit/test_hiring_review.py` |
| `test_hiring_review_prompt_lists_positioning_dimensions` | FR-012 | same |
| `test_hiring_review_flags_role_match_and_opening_when_mispositioned` | FR-013, FR-014, FR-025, SC-007 | same |
| `test_writer_rules_config_round_trip` | FR-022 | `tests/unit/test_config_models.py` (extension) |

The Langfuse/MLflow non-interference invariant (SC-008) is structurally guaranteed (no MLflow tag names change; no Langfuse span shape change) — the existing 215-test suite continuing to pass IS the proof.

---

## Open questions resolved

- "Does adding a Pydantic optional field break LangGraph state updates?" — No; LangGraph passes partial dicts through `model_copy(update=...)` which tolerates missing keys.
- "Does the planner LLM reliably emit nested objects when the schema requires them?" — Yes; tested in the existing `plan_content` integration test using `ContentPlan.model_json_schema()` as the tool input.
- "Is `state.job_context.raw_job_text` guaranteed to be non-None when `hiring_review` runs?" — Yes; `load_job` is the first stage and `raw_job_text` is its primary output. The graph topology guarantees ordering.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
