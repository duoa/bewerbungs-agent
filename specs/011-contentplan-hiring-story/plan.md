# Implementation Plan: ContentPlan as a Hiring Story

**Branch**: `011-contentplan-hiring-story` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-contentplan-hiring-story/spec.md`

## Summary

A schema-evolution + prompt-update feature, additive to features 008/010. One new Pydantic model (`ParagraphPlan`) lands on `ContentPlan` alongside the legacy `SectionPlan` list, plus a top-level `letter_thesis: str | None`. Each paragraph carries `purpose`, `main_message`, `requirement_ids`, `evidence_refs`, `emphasise`, `deemphasise`, `max_claims` (1..8), and `max_tools` (0..12). Two model validators enforce the cross-field invariants: (a) `len(evidence_refs) <= max_claims` per paragraph; (b) the opening paragraph (`paragraphs[0]`) has `max_claims ∈ {1, 2}` AND its `requirement_ids` reference only IDs that exist in the run's `requirement_items` from feature 010. A third validator enforces evidence_refs trace to claims in `evidence_map.items`. The planner prompt is rewritten to instruct the LLM to produce the new story structure; the planner `build_prompt` is unchanged (auto-schema propagation does the work). The writer prompt and `build_prompt` gain a new `# Paragraph Plan` block that surfaces per-paragraph constraints (purpose, main_message, max_claims, max_tools, emphasise, deemphasise) so the writer can produce paragraph-aware prose. The writer's existing global rules (tool-density from `writer_rules`, banned phrases, role-first opening) stay in force; per-paragraph `max_tools` OVERRIDES the global cap when stricter. Retrieval, evidence mapping, requirement extraction, hiring review, MLflow, Langfuse, and CLI behaviour are all unchanged. Per-prompt content hashes flip naturally for `planner.md` + `writer.md` — exactly two new versions on the next `jobagent prompts sync`.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml`, mypy strict)
**Primary Dependencies**: existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new dependencies.
**Storage**: existing only — prompt files, file artefacts, MLflow store, Langfuse remote.
**Testing**: `pytest>=8.0`, `pytest-mock>=3.0` (existing). New tests added to `tests/unit/test_plan_content.py` and `tests/unit/test_write_letter.py`; no new test files required.
**Target Platform**: macOS / Linux CLI; Python 3.11.
**Project Type**: Single-project CLI.
**Performance Goals**: prompt-token overhead per run is bounded — `letter_thesis` ≤ 300 chars, `main_message` ≤ 300 chars × ≤ 6 paragraphs ≈ ~2000 tokens total addition across planner output and writer input. No measurable per-stage latency change vs. feature 010.
**Constraints**:
- Existing 254-test baseline (post-feature-010) MUST keep passing without modification (the new fields default safely; legacy `SectionPlan`-only artifacts continue to load).
- MLflow log shape unchanged (FR-019, SC-007). Per-stage prompt-hash tag VALUES for `planner` and `writer` flip naturally because the prompt files change — that's the correct signal.
- Langfuse trace structure unchanged (FR-020). Same span shape; same metadata field names; only `prompt_content_hash` values flip on the two edited prompts.
- Backward compat: legacy `ContentPlan` JSON (no `letter_thesis`, no `paragraphs`) MUST load cleanly with defaults; existing tests using minimal plans continue to pass (FR-022, SC-005).
- `extra="forbid"` discipline preserved on `ContentPlan` AND new `ParagraphPlan` (FR-023).
- Writer isolation invariant from feature 001: writer reads ONLY `ContentPlan`; no raw profile / CV / evidence-map passages reach it (FR-015). The new fields ride on the existing typed object.
- Retrieval, evidence mapping, requirement extraction (feature 010 owns), hiring review (features 005/008/009 own), targeted_rewrite (feature 005 owns), validate_outputs (feature 001 owns) — all UNCHANGED (FR-017, FR-018).

**Scale/Scope**: 3 source files modified (`models/state.py`, `stages/plan_content.py`, `stages/write_letter.py`) + 2 prompt files modified (`planner.md`, `writer.md`) + 2 test files extended. ~8 new tests. No new files. No new pipeline stage.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Factual Integrity (NON-NEGOTIABLE) | PASS | The richer plan strengthens factuality: per-paragraph `requirement_ids` AND `evidence_refs` cross-validate at parse time against the run's `requirement_items` and `evidence_map`, surfacing stale references that would otherwise reach the writer silently. Per-paragraph `max_claims` caps prevent the writer from inventing extra anchors beyond what the planner approved. |
| II. Approved Sources Only | PASS | No new sources. All new fields are derived from the same job description text + evidence map the existing planner already reads. |
| III. Structured-Before-Generative Workflow | PASS | The structured planner produces a richer plan; the generative writer reads it. This DEEPENS the principle — paragraph-level structure exists before any prose. |
| IV. Separation of Concerns | PASS | Changes confined to the planner + writer stages (their prompts + their build_prompt formatters) and the `ContentPlan`/`ParagraphPlan` Pydantic models. Hiring review, validate, targeted_rewrite are untouched. |
| V. Deterministic Interfaces & Typed State | PASS | One new Pydantic model (`ParagraphPlan`) with `extra="forbid"`; two new optional fields on `ContentPlan` (`letter_thesis: str \| None`, `paragraphs: list[ParagraphPlan]`); three model validators enforce cross-field invariants at parse time. Stronger typing throughout. |
| VI. Test Coverage | PASS | Spec FR-024..FR-030 enumerate seven required tests; TDD: failing tests first, then schema + prompt changes that make them pass. The AI/ML-infra fixture regression test (FR-025) reuses the feature 008 fixture. |

**Result**: All gates pass. Complexity Tracking table empty.

## Project Structure

### Documentation (this feature)

```text
specs/011-contentplan-hiring-story/
├── plan.md              # this file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── schemas_and_prompts.md
├── checklists/
│   └── requirements.md  # from /speckit.specify
└── tasks.md             # generated by /speckit.tasks (NOT in this command)
```

### Source Code (repository root)

Single-project layout. No new files. Three source files modified + two prompt files modified + two test files extended.

```text
src/bewerbungs_agent/
├── models/
│   └── state.py                        [MOD] add ParagraphPlan model; add ContentPlan.letter_thesis + ContentPlan.paragraphs; add 3 model_validators (evidence_refs ≤ max_claims, opening max_claims ∈ {1,2}, requirement_ids + evidence_refs cross-validate against run's requirement_items + evidence_map)
└── stages/
    ├── plan_content.py                 [MOD] no signature change; auto-schema picks up new fields. parse_response remains a thin model_validate wrapper — the new validators on ContentPlan do the work
    └── write_letter.py                 [MOD] _format_positioning_block (or new helper) renders a new # Paragraph Plan block with one row per ParagraphPlan; per-paragraph max_tools overrides the global writer_rules.tool_density_max in the prompt instruction text

prompts/
├── planner.md                          [MOD] add new section explaining the hiring-story output: letter_thesis first, then ordered paragraphs each with purpose / main_message / requirement_ids / evidence_refs / emphasise / deemphasise / max_claims / max_tools; opening paragraph reflects role_positioning; high-priority requirements get their own paragraph
└── writer.md                           [MOD] explain how to consume the # Paragraph Plan block; emphasise that per-paragraph max_tools / max_claims OVERRIDE the global writer_rules cap for that paragraph specifically; preserve all existing rules (role-first opening, banned phrases, no-claim-outside-plan)

tests/
└── unit/
    ├── test_plan_content.py            [MOD] add ~6 tests: ParagraphPlan schema validation, main_message single-string assertion, opening paragraph reflects role_positioning (AI/ML-infra fixture regression), evidence_refs ≤ max_claims violation raises, opening max_claims ∈ {1,2} validator, unknown-field forbidden on ParagraphPlan, requirement_ids referencing unknown id raises, legacy ContentPlan loads cleanly
    └── test_write_letter.py            [MOD] add ~2 tests: writer prompt surfaces per-paragraph max_claims + max_tools when paragraphs populated; writer prompt falls back to global writer_rules.tool_density_max when paragraphs empty
```

**Structure Decision**: One nested Pydantic model (`ParagraphPlan`) plus two additive fields on `ContentPlan` — the only schema changes. Both are required because the existing `SectionPlan` model genuinely cannot represent per-paragraph density limits, main_message singularity, or the cross-field validation against `requirement_items`. The planner's tool schema is auto-generated from `ContentPlan.model_json_schema()` — no manual schema edit. The writer's tool schema (`{text, mode}`) is unchanged; the new fields are surfaced to the writer via the prompt-content path. The legacy `sections: list[SectionPlan]` field stays in place untouched (FR-022 backward compat). Hiring review automatically benefits because feature 009's content-plan summary block serialises the entire `ContentPlan` — no review code change.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
