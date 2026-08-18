# Implementation Plan: Narrative Strategy & Story Polish

**Branch**: `013-narrative-strategy-polish` | **Date**: 2026-05-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/013-narrative-strategy-polish/spec.md`

## Summary

This feature adds a **NarrativeStrategy** layer upstream of content planning and a **story_polish** stage downstream of letter writing, both wrapped around the existing pipeline without changing retrieval, requirement extraction, or evidence mapping. It also extends `hiring_review` with six new craft-level dimensions and adds a deterministic German over-analogy phrase blocklist enforced as warnings in the validation report.

**Architectural decision (resolves the spec's open question)**: `role_positioning` is split out of `plan_content` into its own dedicated `role_position` stage. The role-positioning *prompt and output shape are unchanged* — only the call site moves. This honors the spec's constraint "do not change role positioning" (the prompt logic and output schema are preserved) while satisfying the `/plan` directive "after role_positioning and before content_plan". The resulting graph reads as a sequence: `role_position → narrative_strategy → plan_content`, with `plan_content` consuming `role_positioning` as input instead of producing it.

**Three new LLM-calling stages** are introduced: `role_position` (one call, extracted), `narrative_strategy` (one new call), `story_polish` (one new call, configurable / skippable). Net cost: +2 LLM calls per run with story_polish enabled, +1 with it disabled.

**Deterministic safety nets**:
- A post-check on `story_polish` extracts the set of tool names, employer names, and numeric tokens from draft vs. polished; polished MUST be a subset, else fall back to the draft.
- A German over-analogy phrase blocklist (`"direkt übertragbar"`, `"direkt vergleichbar"`, `"strukturell eng verwandt"`, `"belastbares Analogon"`) is scanned in the validation layer; matches surface as `warn`-severity findings in the existing validation report (when feature 012 lands) or as a structured `hiring_review` finding otherwise.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml`, mypy strict)
**Primary Dependencies**: existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new runtime dependencies.
**Storage**: Prompt files under `prompts/` (canonical). New file artefacts under `outputs/<run_id>/artifacts/`: `narrative_strategy.json`, `story_polish_output.json`. No new persistence systems. No change to MLflow / Langfuse persistence.
**Testing**: pytest. All new tests use mocked LLM responses (canned dicts); no real Anthropic calls in unit tests.
**Target Platform**: Local CLI (`jobagent run`), Python 3.11 on macOS / Linux.
**Project Type**: Single-project CLI (existing structure under `src/bewerbungs_agent/`).
**Performance Goals**: ≤ 30 s median additional wall-clock per run (two new LLM calls, each batched, parallelisable with existing extended-thinking budgets).
**Constraints**:
- Factual integrity (constitution I): `story_polish` MUST NOT add any new fact, tool, employer, metric, method, or claim. Enforced deterministically AND in the prompt.
- Approved sources only (constitution II): `narrative_strategy` reads only `job_context`, `requirements`, `evidence_map`, `config` — no raw `InternalKnowledge`.
- Backward-compat: legacy `WorkflowState` snapshots without `NarrativeStrategy` or saved `RolePositioning` continue to load.
**Scale/Scope**: ~+450 LOC source code, ~+300 LOC tests, 3 new stage modules, 3 modified stages (`plan_content`, `write_letter`, `hiring_review`), 4 new/modified prompt files, 2 new artefact JSON files.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Factual Integrity (NON-NEGOTIABLE) | ✅ PASS | `story_polish` is the highest-risk stage. Mitigation: deterministic post-check refuses any polished output whose tool/employer/numeric set is not a subset of the draft's, AND the polish prompt is explicit about the forbidden categories. Failure falls back to the unpolished draft — never to invented content. |
| II. Approved Sources Only | ✅ PASS | `narrative_strategy` and `story_polish` consume only already-loaded approved inputs (`job_context`, `requirements`, `evidence_map`, `content_plan`, `letter_draft`, `role_positioning`, `narrative_strategy`). No new source loader, no web access. |
| III. Structured-Before-Generative Workflow | ✅ PASS | The three new stages slot into the existing pipeline in dependency order: `role_position` → `narrative_strategy` → `plan_content` → `write_letter` → `story_polish` → `hiring_review`. Each stage's output is a typed structured object consumed by the next. |
| IV. Separation of Concerns | ✅ PASS | `narrative_strategy` is a *selection* stage (chooses proof points to use/avoid, anti-patterns). `story_polish` is a *tone* stage (improves flow without altering factual selection — enforced by the post-check). These map cleanly onto the constitution's selection/tone separation. |
| V. Deterministic Interfaces & Typed State | ✅ PASS | `NarrativeStrategy` and `StoryPolishOutput` are Pydantic v2 models with `ConfigDict(extra="forbid")`. The seven new hiring-review craft dimensions extend the existing typed structured output additively. No new untyped dicts cross stage boundaries. |
| VI. Test Coverage | ✅ PASS | TDD enforced: schema parsing, stage order, prompt assembly, no-new-claims post-check (mocked story_polish), review findings for over-constructed transfer language — five test classes pinned by the user, supplemented by stage-isolation unit tests per the existing pattern. |

**No violations.** No entries needed in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/013-narrative-strategy-polish/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output — Pydantic schema additions
├── quickstart.md        # Phase 1 output — operator walkthrough
├── contracts/           # Phase 1 output — schemas, prompts, formatters
│   └── schemas_and_prompts.md
└── tasks.md             # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/bewerbungs_agent/
├── config/
│   └── models.py                       # +NarrativePolishConfig (3 booleans + optional tool_registry override)
├── graph/
│   └── workflow.py                     # MODIFIED: 3 new nodes wired in, 1 edge moved (build_evidence_map → role_position instead of plan_content)
├── models/
│   └── state.py                        # +NarrativeStrategy, +StoryPolishOutput, +CraftDimensions (HiringReviewOutput extension); ContentPlan.role_positioning becomes Optional input from upstream stage
├── stages/
│   ├── role_position.py                # NEW — extracted LLM call producing RolePositioning
│   ├── narrative_strategy.py           # NEW — produces NarrativeStrategy from (job_context, requirements, evidence_map, role_positioning, config)
│   ├── plan_content.py                 # MODIFIED — consumes upstream role_positioning + narrative_strategy; prompt no longer asks for role_positioning; drops paragraphs whose evidence_refs overlap proof_points_to_avoid
│   ├── write_letter.py                 # MODIFIED — adds _format_narrative_strategy_block helper; consumes narrative_strategy
│   ├── story_polish.py                 # NEW — polishes letter draft; deterministic post-check (tool/employer/numeric subset); fallback on failure
│   └── hiring_review.py                # MODIFIED — adds 6 craft dimensions to structured output; deterministic over-analogy phrase scan emits warn findings
├── utils/
│   ├── extractors.py                   # NEW — tool_names_in_text(), employer_names_in_text(), numeric_tokens_in_text() (shared by story_polish post-check)
│   └── prompts.py                      # unchanged (load_prompt continues to handle new prompt files)
└── cli.py                              # unchanged (no new CLI flags this feature)

prompts/
├── role_positioner.md                  # NEW — extracted role-positioning instructions (verbatim from existing planner.md role-positioning section)
├── narrative_strategist.md             # NEW — produces NarrativeStrategy
├── planner.md                          # MODIFIED — role-positioning section removed; consumes narrative_strategy
├── writer.md                           # MODIFIED — paragraph plan consumption section extended to reference narrative_strategy block
├── story_polisher.md                   # NEW — polish prose without adding facts
├── hiring_reviewer.md                  # MODIFIED — adds 6 craft dimensions + restrained AIDA evaluation guidance
└── styles/
    └── aida.md                         # MODIFIED — restrained tone reinforcement

tests/
├── unit/
│   ├── test_role_position.py           # NEW — schema + prompt build for extracted stage
│   ├── test_narrative_strategy.py      # NEW — schema parsing, prompt build, downstream consumption
│   ├── test_story_polish.py            # NEW — schema, prompt build, post-check with mocked outputs (subset/superset cases, fallback path)
│   ├── test_plan_content.py            # EXTENDED — drop-paragraph-on-proof_points_to_avoid test
│   ├── test_write_letter.py            # EXTENDED — narrative_strategy block surfaces in prompt
│   ├── test_hiring_review.py           # EXTENDED — 6 new craft dimensions + over-analogy phrase warnings test
│   └── test_extractors.py              # NEW — tool/employer/numeric extractors (the deterministic post-check building blocks)
├── integration/
│   └── test_full_run.py                # EXTENDED — verifies the new stage order in the graph
└── fixtures/                           # (no new directory) — fixtures inlined in tests as canned dicts
```

**Structure Decision**: Single-project CLI per existing layout. New stages live under `src/bewerbungs_agent/stages/` mirroring the established pattern; new prompts under `prompts/`; new tests under `tests/unit/`. No new top-level directories.

## Complexity Tracking

> No constitution violations to justify. Table omitted.
