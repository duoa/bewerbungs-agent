# Implementation Plan: Role-Positioned Prompting

**Branch**: `008-role-positioned-prompting` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-role-positioned-prompting/spec.md`

## Summary

A prompt-and-context feature, with one minimal schema addition. The planner gets a new `RolePositioning` sub-object on `ContentPlan` (the existing structure cannot represent the six positioning fields). `prompts/planner.md` is rewritten to require the model to fill it. `prompts/writer.md` is rewritten to consume it: lead with the primary role family in the opening paragraph, cap tool density per paragraph (configurable), forbid self-rating phrases (configurable), and inject nothing not in the plan. `prompts/hiring_reviewer.md` is rewritten to evaluate five positioning-specific dimensions and is supplied with the original `state.job_context.raw_job_text` alongside the existing structured requirements and draft letter. Pipeline wiring is untouched except that `hiring_review.build_prompt` now reads `state.job_context` (which `load_job` already populated). The new `writer_rules` config block carries the tool-density cap and ban list. Langfuse trace shape, MLflow logs, Langfuse prompt-registry behaviour (feature 007), and the CLI contract are all unchanged — the new prompt content automatically bumps the registry hashes on the next `prompts sync`, which is exactly the intended observability outcome.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml`, mypy strict)
**Primary Dependencies**: existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new dependencies.
**Storage**: prompt files under `prompts/` (canonical) + local file artefacts. No new persistence. No change to MLflow / Langfuse persistence.
**Testing**: `pytest>=8.0`, `pytest-mock>=3.0` (existing). New fixture files under `data/examples/jobs/` and `data/examples/profile/projects/`. New / extended tests in `tests/unit/test_plan_content.py`, `tests/unit/test_write_letter.py`, `tests/unit/test_hiring_review.py`.
**Target Platform**: macOS / Linux CLI; Python 3.11.
**Project Type**: Single-project CLI.
**Performance Goals**: no measurable change to per-stage latency vs. pre-feature; positioning fields add ~50 tokens to the plan output and ~200 tokens to the planner instructions — comfortably within the existing prompt budget.
**Constraints**:
- Existing 215 tests MUST keep passing without modification (where not directly extended).
- MLflow log shape unchanged (same params/tags/metrics; FR-017, SC-008).
- Langfuse trace structure unchanged (same per-stage spans; same metadata fields; new positioning summary fields ride inside the existing content-plan summary; FR-018).
- Feature 007 prompt-registry behaviour unchanged: editing the three prompt files automatically bumps their content hashes; next `jobagent prompts sync` creates one new version per edited file.
- Final CLI contract unchanged (FR-019).
- Outputs remain byte-identical when both runs use the same inputs AND the prompts are unchanged. After this feature lands, prompts change → letter content will differ; that is the intended observable improvement, not a regression.

**Scale/Scope**: ~7 files touched (3 prompts + state + config + 2 stages); 3 test files extended; 1 fixture job + 1 fixture project added.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Factual Integrity (NON-NEGOTIABLE) | PASS | The writer's new rules (no banned phrases, no claims absent from the plan) STRENGTHEN the existing factuality invariant — they make the failure mode "subtle overclaim" explicitly catchable by the reviewer. |
| II. Approved Sources Only | PASS | No new sources. The hiring-review stage gains `raw_job_text` access, but `job_context` was already loaded by `load_job` from the approved job source. |
| III. Structured-Before-Generative Workflow | PASS | Stage order unchanged. The structured planner stage gains explicit positioning output before any prose; the generative writer/reviewer consume it. This DEEPENS the principle. |
| IV. Separation of Concerns | PASS | Positioning is a planner output. Writer applies it to prose. Reviewer evaluates alignment. Each stage's role is clean; no factual selection happens inside the writer or reviewer. |
| V. Deterministic Interfaces & Typed State | PASS | One new Pydantic sub-object (`RolePositioning`) added to `ContentPlan` with `extra="forbid"`. One new Pydantic sub-object (`WriterRules`) added to `StarterTemplate`/`MergedConfig`. No untyped dicts cross stage boundaries. |
| VI. Test Coverage | PASS | Spec FR-024..FR-027 enumerate the required tests; TDD: failing tests first, then prompt + minimal-schema changes that make them pass. The GSK-style regression fixture is the durable guarantee. |

**Result**: All gates pass. Complexity Tracking table empty.

## Project Structure

### Documentation (this feature)

```text
specs/008-role-positioned-prompting/
├── plan.md              # this file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── prompts_and_schemas.md
├── checklists/
│   └── requirements.md  # from /speckit.specify
└── tasks.md             # generated by /speckit.tasks (NOT in this command)
```

### Source Code (repository root)

Single-project layout reused. New files marked **[NEW]**; modified files marked **[MOD]**.

```text
src/bewerbungs_agent/
├── config/
│   └── models.py                       [MOD] add WriterRules (Pydantic, extra="forbid") + writer_rules field on StarterTemplate + MergedConfig
├── models/
│   └── state.py                        [MOD] add RolePositioning Pydantic model + role_positioning: RolePositioning | None on ContentPlan
├── stages/
│   ├── plan_content.py                 [MOD] build_prompt formats positioning instructions + the job description text into the planner context
│   ├── write_letter.py                 [MOD] build_prompt formats role_positioning + writer_rules constraints
│   └── hiring_review.py                [MOD] build_prompt includes state.job_context.raw_job_text + the 5 new evaluation dimensions
└── utils/
    └── merge.py                        [MOD] add writer_rules to base dict (extra="forbid" gotcha from ENGINEERING.md §15)

prompts/
├── planner.md                          [MOD] require explicit role positioning, message hierarchy, primary/secondary framing
├── writer.md                           [MOD] role-first opening, system-level outcomes, tool-density cap, ban list, no-unsupported-claims
└── hiring_reviewer.md                  [MOD] evaluate against full job description; 5 positioning-specific dimensions

data/examples/
├── jobs/
│   └── sample_ml_infrastructure.md     [NEW] AI/ML infrastructure SWE fixture — scalable cloud infra, efficient compute, robust Python software, AI/ML workloads, agentic systems; biomedical context as secondary
└── profile/
    └── projects/
        └── biomedical_ml_project.md    [NEW] notable biomedical-ML project file so the profile has BOTH strong infra evidence AND a salient biomedical-ML angle

tests/
└── unit/
    ├── test_plan_content.py            [MOD] add test_planner_positions_infrastructure_first_on_ml_infra_fixture (FR-024)
    ├── test_write_letter.py            [MOD] add test_writer_opening_leads_with_primary_role + tool-density + ban-phrase tests (FR-026)
    └── test_hiring_review.py           [MOD] add test_review_flags_role_match_and_opening_when_letter_mispositioned (FR-025)
```

**Structure Decision**: One nested Pydantic sub-object on `ContentPlan` (positioning) plus one nested Pydantic sub-object on `MergedConfig` (writer rules) — the only schema changes, both required because the existing structures genuinely cannot represent the positioning decision or the per-template constraints (FR-021 met). All other behaviour change lives in the three prompt files. No new pipeline stage, no new artefact, no new CLI command, no Langfuse/MLflow shape change.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
