# Implementation Plan: Hiring Review with Full Job Context

**Branch**: `009-review-full-job-context` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-review-full-job-context/spec.md`

## Summary

A small context-passing feature, additively built on feature 008. Feature 008 added the verbatim `raw_job_text` and five positioning dimensions to the hiring-review prompt. This feature finishes the job: the prompt additionally surfaces the parsed structured `job_context` fields (job title, company name, optional company info text, optional storyboard text), a structured summary of the `content_plan`, and a sixth always-on dimension `critical_requirements_underweighted`. All changes are confined to `prompts/hiring_reviewer.md` and `stages/hiring_review.py::build_prompt`. No new pipeline stage, no new artefact, no new CLI command, no schema change, no edits to any other prompt file. The existing review Pydantic schema (`LetterReviewReport`/`SectionReview`/`WeaknessEntry`) is unchanged; the new dimension routes via the same weakness-text tagging convention feature 008 established. Backward-compat for legacy paths (`state.job_context is None`, `state.content_plan is None`) is preserved via graceful omission of optional blocks.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml`, mypy strict)
**Primary Dependencies**: existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new dependencies.
**Storage**: existing only — prompt files, file artefacts, MLflow store, Langfuse remote.
**Testing**: `pytest>=8.0`, `pytest-mock>=3.0` (existing). Three new tests in `tests/unit/test_hiring_review.py` plus a small fixture extension to verify the new combined-context shape preserves the feature 008 secondary-domain regression catch.
**Target Platform**: macOS / Linux CLI; Python 3.11.
**Project Type**: Single-project CLI.
**Performance Goals**: prompt-token overhead per review is ~200–800 tokens (parsed-field labels + content-plan summary), well within the existing Anthropic call budget; no measurable per-stage latency change vs. feature 008.
**Constraints**:
- Existing 230-test baseline (from feature 008) MUST keep passing.
- MLflow log shape unchanged (FR-016, SC-009). The per-stage `prompt_hash` for `hiring_reviewer` will flip naturally because the prompt file changes — that's the correct signal of the edit, not a regression.
- Langfuse trace structure unchanged (FR-017, SC-009). Same per-stage span shape; same metadata fields; only the recorded `prompt_content_hash` value flips.
- Feature 005 non-blocking behaviour preserved: any LLM-call failure in `hiring_review` still emits one warning and returns `{}` so the pipeline proceeds.
- Feature 007 prompt-registry will record exactly ONE new version of `bewerbungs-agent/hiring_reviewer` on the next `jobagent prompts sync`; the other 9 prompts must stay unchanged.
- Feature 008's five always-on positioning dimensions stay always-on (FR-008/FR-014).
- The review continues to evaluate the LETTER only (FR-007): the content plan is read-only reference, never a target.

**Scale/Scope**: 2 source files modified (1 prompt + 1 stage), 1 test file extended (~5 new tests + 1 new fixture-state helper). No new files. Bounded diff.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Factual Integrity (NON-NEGOTIABLE) | PASS | The reviewer reads more context but evaluates only the letter (FR-007). The new `critical_requirements_underweighted` dimension STRENGTHENS factuality by surfacing under-coverage of job-stated needs that a generic review might miss. The reviewer is explicitly forbidden from flagging gaps already in `evidence_map.known_gaps` (FR-011) so honest gaps don't become false positives. |
| II. Approved Sources Only | PASS | No new content source: all new context (parsed `job_context` fields + `content_plan` summary) is already on `WorkflowState`, loaded by `load_job` and `plan_content` respectively. No external lookup. |
| III. Structured-Before-Generative Workflow | PASS | Review is a post-generation evaluation stage; this feature enriches its input set without changing pipeline order or earlier stages. |
| IV. Separation of Concerns | PASS | All changes inside the hiring-review stage's prompt + `build_prompt` formatter. Writer, planner, targeted_rewrite, and validate are not touched (FR-012). |
| V. Deterministic Interfaces & Typed State | PASS | Zero schema additions (FR-015). The new dimension reuses `WeaknessEntry.text` tagging — the same routing convention feature 008 established. Backward-compat invariants for None optional fields are explicit (FR-003/FR-004/FR-005). |
| VI. Test Coverage | PASS | Spec FR-020..FR-025 enumerate six required tests; TDD: failing tests first, then prompt + build_prompt edits that make them pass. The three specifically-named tests (prompt-contains-job-text, legacy-no-job-context-works, mocked-review-flags-secondary-opening) map directly to FR-020/FR-021/FR-023. |

**Result**: All gates pass. Complexity Tracking table empty.

## Project Structure

### Documentation (this feature)

```text
specs/009-review-full-job-context/
├── plan.md              # this file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── hiring_review_prompt.md
├── checklists/
│   └── requirements.md  # from /speckit.specify
└── tasks.md             # generated by /speckit.tasks (NOT in this command)
```

### Source Code (repository root)

Single-project layout reused. No new files. Two source files modified, one test file extended.

```text
src/bewerbungs_agent/
└── stages/
    └── hiring_review.py                [MOD] build_prompt formats parsed job_context structured fields + content plan summary; _POSITIONING_DIMENSIONS gains "critical_requirements_underweighted"

prompts/
└── hiring_reviewer.md                  [MOD] new ## Parsed Job Context block, ## Content Plan block, expanded "Six positioning-specific dimensions" section (adds critical_requirements_underweighted); reminder that the reviewer evaluates the LETTER only

tests/
└── unit/
    └── test_hiring_review.py           [MOD] add 5 new tests: prompt includes parsed structured fields; prompt includes content plan summary; prompt builds when job_context is None; prompt builds when content_plan is None; prompt active-dims list includes critical_requirements_underweighted; mocked review with secondary-domain opening lands "opening" in sections_to_rewrite at severity high
```

**Structure Decision**: No new module, no new schema. The data-model.md file in Phase 1 documents how the existing entities are read (no entities are created). The contracts/ file documents the prompt and `build_prompt` contract — that is the entire feature interface.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
