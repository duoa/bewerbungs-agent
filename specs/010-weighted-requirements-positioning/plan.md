# Implementation Plan: Weighted Requirements + Refined Role Positioning

**Branch**: `010-weighted-requirements-positioning` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-weighted-requirements-positioning/spec.md`

## Summary

A schema-evolution + prompt-update feature. Two new typed structures land alongside the existing ones:

1. **`RequirementItem`** — a richer per-requirement record carrying `id`, `text`, `priority` (enum), `category` (enum), `evidence_needed` (enum), and an optional `source_excerpt`. Added as `RequirementExtraction.requirement_items: list[RequirementItem]`. The legacy `all_requirements: list[Requirement]` field stays in place for backward compatibility; a Pydantic `model_validator` populates it from `requirement_items` on parse so older consumers continue to work.

2. **Refined `RolePositioning`** — the feature 008 model evolves: three fields are renamed (`primary_role_family` → `role_family`, `topics_to_emphasise` → `emphasise`, `topics_to_deemphasise` → `deemphasise`) and one new optional field is added (`risky_or_gap_areas`). Backward compatibility for feature-008-shaped artifacts is preserved via Pydantic `Field(..., alias=...)` plus `populate_by_name=True` so JSON written under either field-name set parses cleanly.

Three prompt files change content to surface the new structure to the LLM and to the reviewer:
- `prompts/requirements.md` — instruct the model to produce `requirement_items` with the four new attributes
- `prompts/planner.md` — accept (and emit) the renamed `RolePositioning` fields plus `risky_or_gap_areas`
- `prompts/hiring_reviewer.md` — surface `risky_or_gap_areas` in the existing content-plan summary block (feature 009)

Retrieval (`build_evidence_map`, CV-variant selection, profile loading), the final writer behaviour (modulo the additive `risky_or_gap_areas` exposure), and all observability surfaces (MLflow tag/metric names, Langfuse trace shape, feature 007 prompt registry) are unchanged. Per-prompt content hashes flip naturally for the three edited prompts — that's the intended signal.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml`, mypy strict)
**Primary Dependencies**: existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new dependencies.
**Storage**: existing only — prompt files, file artefacts, MLflow store, Langfuse remote.
**Testing**: `pytest>=8.0`, `pytest-mock>=3.0` (existing). New tests added to three existing test files (`test_extract_requirements.py`, `test_plan_content.py`, `test_hiring_review.py`); no new test files required.
**Target Platform**: macOS / Linux CLI; Python 3.11.
**Project Type**: Single-project CLI.
**Performance Goals**: prompt-token overhead per stage is negligible (per-requirement structure adds ~20 tokens × N requirements; positioning gains one new field of ~50 tokens); no measurable per-stage latency change.
**Constraints**:
- Existing 239-test baseline (post-feature-009) MUST keep passing.
- MLflow log shape unchanged (FR-015, SC-008). The per-stage `prompt_hash` tag VALUES for `requirements`, `planner`, and `hiring_reviewer` will flip naturally because the prompt files change — that's the correct signal of the edit, not a regression.
- Langfuse trace structure unchanged (FR-016, SC-008).
- CLI contract unchanged (FR-017).
- Backward compat: pre-feature-010 JSON artifacts for `RequirementExtraction` and feature-008-shape `RolePositioning` MUST load (FR-018, FR-019).
- `extra="forbid"` discipline preserved on both new and existing models (FR-020).
- Retrieval and final writer behaviour unchanged (FR-012, FR-013); the new `risky_or_gap_areas` field flows additively through the writer's existing positioning-consumption path.

**Scale/Scope**: 3 prompt files + 1 state-model file + 2 stage files + 3 test files = 9 files modified. No new files. No new dependencies. No new fixtures (reuse the feature 008 AI/ML infrastructure fixture).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Factual Integrity (NON-NEGOTIABLE) | PASS | The richer structure feeds downstream stages with more grounded weights; the writer's no-claim-outside-plan rule (feature 008) is unchanged. `RequirementItem.source_excerpt` (optional) lets the extractor cite the verbatim job-text fragment that supports each requirement — STRENGTHENS traceability, doesn't relax it. |
| II. Approved Sources Only | PASS | No new sources. All new fields are derived from the same job description text the extractor already reads. |
| III. Structured-Before-Generative Workflow | PASS | The new structure lives in the existing structured stage (`extract_requirements`) and the planner's structured content plan; generation order unchanged. |
| IV. Separation of Concerns | PASS | Changes confined to the data models (`models/state.py`) and three prompt+formatter sites (extract_requirements, plan_content, hiring_review). Writer code is not edited; the writer continues to read positioning via the content plan it already consumes. |
| V. Deterministic Interfaces & Typed State | PASS | Stronger typing: `priority`, `category`, `evidence_needed` become enums (was free-form ints/strings); `RolePositioning` field names are normalised. Backward-compat aliases are explicit Pydantic-supported mechanisms — not free-form string hacks. |
| VI. Test Coverage | PASS | Spec FR-021..FR-027 enumerate seven required tests; TDD: failing tests first, then minimal schema + prompt changes that make them pass. The AI/ML infrastructure fixture regression test (FR-026) is the durable guarantee that misclassification doesn't return. |

**Result**: All gates pass. Complexity Tracking table empty.

## Project Structure

### Documentation (this feature)

```text
specs/010-weighted-requirements-positioning/
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

Single-project layout reused. No new files. Six source files modified plus three test files extended.

```text
src/bewerbungs_agent/
├── models/
│   └── state.py                        [MOD] add RequirementItem + Priority/Category/EvidenceNeeded enums; add RequirementExtraction.requirement_items + populator validator; rename RolePositioning fields with backward-compat aliases; add risky_or_gap_areas
└── stages/
    ├── extract_requirements.py         [MOD] parse_response handles the new requirement_items field; no signature change
    ├── plan_content.py                 [MOD] build_prompt formats requirement_items in priority order so the planner sees weighting; outputs the renamed RolePositioning fields (existing schema flows through Pydantic auto-schema)
    └── hiring_review.py                [MOD] build_prompt surfaces RolePositioning.risky_or_gap_areas in the existing content-plan summary block (feature 009)

prompts/
├── requirements.md                     [MOD] instruct the LLM to produce requirement_items with id/text/priority/category/evidence_needed (+ optional source_excerpt); keep legacy field instructions for the existing core/technical/etc. summary
├── planner.md                          [MOD] use the new RolePositioning field names (role_family, emphasise, deemphasise, risky_or_gap_areas); read requirement_items as the priority-ordered input
└── hiring_reviewer.md                  [MOD] surface risky_or_gap_areas in the content-plan summary block per FR-007; no new evaluation dimension

tests/
└── unit/
    ├── test_extract_requirements.py    [MOD] add 4 tests: parse mocked LLM output with requirement_items; missing optional fields default; invalid priority enum value raises; legacy payload (no requirement_items) loads
    ├── test_plan_content.py            [MOD] add 2 tests: build_prompt surfaces requirement_items in priority order; parse_response accepts RolePositioning under both old and new field names (backward compat)
    └── test_hiring_review.py           [MOD] add 2 tests: build_prompt surfaces risky_or_gap_areas in content-plan summary; build_prompt does NOT surface risky_or_gap_areas when the list is empty
```

**Structure Decision**: All changes flow through the existing `RequirementExtraction` and `RolePositioning` Pydantic models — no new modules, no new pipeline stages, no new artefacts. The auto-generated tool schemas in `extract_requirements.py` and `plan_content.py` pick up the new fields automatically because both stages call `Model.model_json_schema()` to build the LLM tool input schema. The hiring-review stage uses a hand-built `_REVIEW_SCHEMA` for its output but its INPUT prompt is text-formatted — so the new positioning field surfaces via a one-line addition to the content-plan summary builder added in feature 009.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
