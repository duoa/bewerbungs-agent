# Implementation Plan: Evidence Passage Grounding

**Branch**: `003-evidence-passage-grounding` | **Date**: 2026-04-15 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/003-evidence-passage-grounding/spec.md`

## Summary

Replace head-based document truncation in `build_evidence_map` with full-document passage extraction, where the LLM is instructed to quote specific verbatim passages for each claim. Extend `EvidenceItem` with a `relevance_note` field and `SectionPlan` with an `anchor_passages` field, so approved passages flow through the ContentPlan and are available to the letter writer. The writer already receives only the ContentPlan JSON (isolation is intact); this feature enriches that JSON with concrete anchor text. No LangGraph topology changes; no new pipeline stages; four files change.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: LangGraph 0.2+, Pydantic v2, Anthropic SDK (claude-sonnet-4-6 via tool-use)  
**Storage**: Local files only — JSON, YAML, Markdown  
**Testing**: pytest, pytest-mock; unit + integration (no golden fixture evaluation in this iteration)  
**Target Platform**: macOS / Linux CLI  
**Project Type**: CLI pipeline tool  
**Performance Goals**: No new LLM calls introduced; full-document context passed to existing `build_evidence_map` call (documents are 2–8 KB each, well within context limits)  
**Constraints**: Must not break existing tests; must not alter LangGraph graph topology; changes confined to four source files + corresponding test files  
**Scale/Scope**: Single-user local tool; evidence maps contain ≤ 20 items in practice

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Factual Integrity | PASS | Feature strengthens this principle — passages are now verbatim, not paraphrased |
| II. Approved Sources Only | PASS | `_is_approved_source` validation unchanged; only approved source files are passed |
| III. Structured-Before-Generative | PASS | Pipeline order unchanged; `build_evidence_map` runs before `plan_content` |
| IV. Separation of Concerns | PASS | Selection (evidence/plan) and generation (write_letter) remain separate stages |
| V. Deterministic Interfaces & Typed State | PASS | New fields added with Pydantic defaults; all stage contracts remain typed |
| VI. Test Coverage | PASS | Unit tests updated for changed stages; integration test updated for richer model |

No violations. Complexity Tracking table not needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-evidence-passage-grounding/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

No `contracts/` directory — this is a purely internal pipeline change with no external-facing interface.

### Source Code (changed files only)

```text
src/bewerbungs_agent/
├── models/
│   └── state.py                    # +relevance_note on EvidenceItem; +anchor_passages on SectionPlan
└── stages/
    ├── build_evidence_map.py       # build_prompt: remove truncation, add full-doc + passage instruction
    │                               # parse_response: drop empty-passage items → known_gaps
    ├── plan_content.py             # build_prompt: include verbatim passages in claims list
    └── write_letter.py             # build_prompt: add one-line anchor instruction

tests/
├── unit/
│   ├── test_build_evidence_map.py  # assert passage populated; assert empty-passage items → known_gaps
│   ├── test_plan_content.py        # assert anchor_passages propagated into sections
│   └── test_write_letter.py        # assert prompt does not reference raw profile text
└── integration/
    └── test_pipeline.py            # update fixture to provide passages; assert end-to-end passage flow
```

**Structure Decision**: Single project, existing layout. Only the four stage files and their test counterparts change.
