---
description: "Task list for Bewerbungs-Agent – CLI Job Application System"
---

# Tasks: Bewerbungs-Agent – CLI Job Application System

**Input**: Design documents from `/specs/001-bewerbungs-agent-core/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/

**Tests**: Included — required by Constitution Principle VI (TDD mandatory; tests
written and failing before implementation).

**Organization**: Tasks grouped by user story to enable independent implementation
and validation of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5 maps to user stories from spec.md

---

## Phase 1: Setup

**Purpose**: Repository scaffolding and tooling before any source code is written.

- [x] T001 Create `pyproject.toml` with `requires-python = "==3.11.*"`, all runtime deps (langgraph, pydantic, typer, anthropic, pyyaml, pypdf, python-dotenv), dev extras (pytest, pytest-mock, ruff, mypy), and `jobagent = "bewerbungs_agent.cli:app"` entry point
- [x] T002 [P] Create `.gitignore` covering `data/`, `outputs/`, `.venv/`, `.env`, `__pycache__/`, `*.pyc`, `*.egg-info/`
- [x] T003 [P] Create `.env.example` at repo root with `ANTHROPIC_API_KEY=` and `BEWERBUNGS_PROFILE_DIR=./data` (no real secrets)
- [x] T004 [P] Create full `src/bewerbungs_agent/` package tree with empty `__init__.py` files: `src/bewerbungs_agent/`, `config/`, `models/`, `stages/`, `graph/`, `io/`, `utils/`
- [x] T005 [P] Create `tests/` directory tree with empty `__init__.py` and `conftest.py` stubs: `tests/unit/`, `tests/integration/`, `tests/golden/`
- [x] T006 [P] Create `data/examples/` with minimal sample files: `master_profile.json` (2 roles, 3 skills), `personal_skills.md` (3 skills with evidence), `cvs/cv_software.md` (short), `cvs/metadata/cv_software.json`, `templates/default_de_neutral.yaml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that ALL user stories depend on.

**⚠️ CRITICAL**: No user story implementation can begin until this phase is complete.

- [x] T007 Implement all pipeline state Pydantic models in `src/bewerbungs_agent/models/state.py`: `JobContext`, `RequirementExtraction`, `Requirement`, `CVVariantMetadata`, `InternalKnowledge`, `SelectedCV`, `EvidenceItem`, `EvidenceMap`, `SoftSkill`, `SectionPlan`, `ContentPlan`, `LetterDraft`, `CVTailoringChange`, `CVTailoringPlan`, `RuleStatus`, `ValidationResult`, `ValidationReport`, `WorkflowState`
- [x] T008 [P] Implement config Pydantic models in `src/bewerbungs_agent/config/models.py`: `LengthMode` (short/normal/long), `WritingMode` (standard/aida), `CVSelectionMode` (automatic/manual), `StarterTemplate`, `RunInput`, `MergedConfig`
- [x] T009 Implement recursive dict merge in `src/bewerbungs_agent/utils/merge.py`: `merge_config(template: StarterTemplate, overrides: dict) -> MergedConfig`; precedence: template < overrides; validate result into `MergedConfig` (depends on T008)
- [x] T010 [P] Implement document loader in `src/bewerbungs_agent/io/loader.py`: `load_json(path)`, `load_yaml(path)`, `load_markdown(path)`, `load_pdf(path)` (pypdf), `load_cv_variant_metadata(metadata_path)` → `CVVariantMetadata`
- [x] T011 [P] Implement prompt file loader in `src/bewerbungs_agent/utils/prompts.py`: `load_prompt(name: str) -> str` (reads from `prompts/{name}.md`), `load_style(mode: WritingMode) -> str` (reads from `prompts/styles/{mode}.md`)
- [x] T012 Implement injectable LLM client in `src/bewerbungs_agent/utils/llm_client.py`: `LLMClient` protocol with `call(messages, tool_schema) -> dict`; `AnthropicLLMClient` implementation using `anthropic` SDK; `get_llm_client()` factory reading `ANTHROPIC_API_KEY` from env
- [x] T013 [P] Implement artifact writer in `src/bewerbungs_agent/io/writer.py`: `write_artifacts(state: WorkflowState, output_dir: Path)` — creates `outputs/<run_id>/artifacts/` and writes all available state fields as JSON; `write_final_outputs(state, output_dir)` — writes `letter.md` and `cv_tailored.md`
- [x] T014 Implement Typer CLI app skeleton in `src/bewerbungs_agent/cli.py`: `app = typer.Typer()`; `run`, `validate`, `eval`, `list-templates` commands as stubs with correct signatures per `contracts/cli-contract.md`; `load_dotenv()` called at module top
- [x] T015 Implement LangGraph graph skeleton in `src/bewerbungs_agent/graph/workflow.py`: `StateGraph(WorkflowState)` with all 12 stage nodes registered, full edge structure including `should_rewrite` conditional, `compile()` returning a runnable graph (nodes can be no-ops at this stage)
- [x] T016 [P] Create `tests/conftest.py` with: `mock_llm_client` fixture returning a `MagicMock` with configurable `call()` responses; `fixture_job_path` and `fixture_profile_dir` pointing to `data/examples/`; minimal `WorkflowState` factory fixture

**Checkpoint**: All models, loaders, writers, CLI skeleton, and graph structure in place — user story implementation can now proceed.

---

## Phase 3: User Story 1 – Generate a Factually-Grounded Cover Letter (Priority: P1) 🎯 MVP

**Goal**: Full cover letter generation pipeline from job file + starter template.

**Independent Test**: `jobagent run --job data/examples/jobs/sample.md --template default_de_neutral` produces `letter.md` with every claim traceable to an evidence map entry referencing only `data/examples/` sources.

> **NOTE: Write tests FIRST (T017, T019, T021, T023, T025, T027, T029) — ensure they FAIL before implementing the corresponding stages**

- [x] T017 [P] [US1] Write unit tests for `load_job` in `tests/unit/test_load_job.py`: valid file → `JobContext`; missing file → `FileNotFoundError`; empty file → `ValueError`; optional company file absent → `company_text` is `None`
- [x] T018 [US1] Implement `src/bewerbungs_agent/stages/load_job.py`: `load_job(state) -> dict` reading `config.job_file`, `config.company_file`, `config.storyboard_file` via `loader.load_markdown`; returns `{"job_context": JobContext(...)}`
- [x] T019 [P] [US1] Write unit tests for `extract_requirements` in `tests/unit/test_extract_requirements.py`: `build_prompt` returns message list containing job text; `parse_response` rejects fixture with >2 technical requirements; `parse_response` raises `ValueError` when `core_requirement` is empty
- [x] T020 [US1] Implement `src/bewerbungs_agent/stages/extract_requirements.py`: `build_prompt(state) -> list[dict]`; `parse_response(tool_block) -> RequirementExtraction`; `extract_requirements(state) -> dict` calling injected `llm_client` with `RequirementExtraction` tool schema
- [x] T021 [P] [US1] Write unit tests for `load_profile` in `tests/unit/test_load_profile.py`: missing `master_profile.json` → `FileNotFoundError`; missing `personal_skills.md` → `FileNotFoundError`; no CV variants → `FileNotFoundError`; optional `projects/` absent → empty dict; optional `letters/` absent → empty dict
- [x] T022 [US1] Implement `src/bewerbungs_agent/stages/load_profile.py`: `load_profile(state) -> dict` reading profile dir from `config`; loads `master_profile.json`, all `cvs/metadata/*.json` as `CVVariantMetadata`, `personal_skills.md`, `projects/*.md`, `letters/*.md`; returns `{"knowledge": InternalKnowledge(...)}`
- [x] T023 [P] [US1] Write unit tests for `select_cv_variant` in `tests/unit/test_select_cv_variant.py`: `cv_variant_override` set → skip LLM, use named variant; unknown override id → `ValueError`; no variants available → `ValueError`; `build_prompt` passes variant list + requirements
- [x] T024 [US1] Implement `src/bewerbungs_agent/stages/select_cv_variant.py`: `build_prompt`; `parse_response`; `select_cv_variant(state) -> dict`; if `config.cv_variant_override` is set skip LLM; returns `{"selected_cv": SelectedCV(...)}`
- [x] T025 [P] [US1] Write unit tests for `build_evidence_map` in `tests/unit/test_build_evidence_map.py`: every `EvidenceItem.source_file` in approved dirs → passes; `source_file` outside approved dirs → `ValueError`; job requirement with no matching evidence → appears in `known_gaps`
- [x] T026 [US1] Implement `src/bewerbungs_agent/stages/build_evidence_map.py`: `build_prompt`; `parse_response`; validate each `EvidenceItem.source_file` against approved path prefixes; raise `ValueError` on violation; returns `{"evidence_map": EvidenceMap(...)}`
- [x] T027 [P] [US1] Write unit tests for `plan_content` in `tests/unit/test_plan_content.py`: number of `selected_soft_skills` ≤ `config.soft_skill_max`; every claim in `ContentPlan.sections` exists in `evidence_map.items[].claim`; `build_prompt` does NOT include raw `InternalKnowledge`
- [x] T028 [US1] Implement `src/bewerbungs_agent/stages/plan_content.py`: `build_prompt` constructed from `requirements` + `evidence_map` + `config.soft_skill_max` only (no raw knowledge); `parse_response` validates claims against evidence map; returns `{"content_plan": ContentPlan(...)}`
- [x] T029 [P] [US1] Write unit tests for `write_letter` in `tests/unit/test_write_letter.py`: `build_prompt` contains only serialised `ContentPlan` (not `InternalKnowledge`); `parse_response` returns `LetterDraft` with `char_count > 0`; standard mode prompt references `prompts/styles/standard.md` content
- [x] T030 [US1] Implement `src/bewerbungs_agent/stages/write_letter.py`: `build_prompt(state)` serialises `content_plan` to JSON and loads `prompts/writer.md` + style prompt; `parse_response` → `LetterDraft`; raises `ValueError` if `char_count == 0`
- [x] T031 [US1] Wire US1 stages into `src/bewerbungs_agent/graph/workflow.py`: replace no-op stubs for `load_job → extract_requirements → load_profile → select_cv_variant → build_evidence_map → plan_content → write_letter`
- [x] T032 [US1] Complete `run` command in `src/bewerbungs_agent/cli.py`: parse args, build `RunInput`, load `StarterTemplate`, call `merge_config`, invoke compiled graph, call `write_artifacts` and `write_final_outputs`; print stage-by-stage progress to stdout per `contracts/cli-contract.md`
- [x] T033 [P] [US1] Write `prompts/system.md` (factuality hard rules, evidence enforcement, approved sources list, forbidden inventions)
- [x] T034 [P] [US1] Write `prompts/requirements.md` (requirement extraction instructions: max 6, slot structure, tone signals)
- [x] T035 [P] [US1] Write `prompts/planner.md` (content plan instructions: evidence-only claims, no prose, section structure)
- [x] T036 [P] [US1] Write `prompts/writer.md` (cover letter generation: receive content_plan JSON only, standard/AIDA structure)
- [x] T037 [P] [US1] Write `prompts/styles/standard.md` (standard cover letter structure: role fit, relevant experience, working style, company motivation, closing)

**Checkpoint**: `jobagent run` produces `letter.md` + `artifacts/requirements.json` + `artifacts/evidence_map.json` + `artifacts/content_plan.json`. Every claim in the letter is in the evidence map. User Story 1 is independently testable.

---

## Phase 4: User Story 2 – Generate a Tailored CV Alongside the Letter (Priority: P2)

**Goal**: Add CV tailoring stage running in parallel with letter writing; output `cv_tailored.md`.

**Independent Test**: After a full run, `cv_tailored.md` exists; diffing it against the base CV variant shows only emphasis/ordering changes — no new skills, roles, employers, or dates.

> **NOTE: Write tests FIRST (T038) — ensure they FAIL before implementing T039**

- [x] T038 [P] [US2] Write unit tests for `tailor_cv` in `tests/unit/test_tailor_cv.py`: `CVTailoringChange.action` restricted to `emphasise | reorder | include | exclude` → others raise `ValueError`; `build_prompt` includes only `selected_cv` text + `requirements` + `evidence_map` (not full `InternalKnowledge`); tailored text contains no string absent from base CV and master profile fixture
- [x] T039 [US2] Implement `src/bewerbungs_agent/stages/tailor_cv.py`: `build_prompt`; `parse_response` validates `CVTailoringChange.action` values; returns `{"cv_tailoring_plan": CVTailoringPlan(...)}` with `tailored_text`
- [x] T040 [US2] Wire `tailor_cv` as parallel branch with `write_letter` in `src/bewerbungs_agent/graph/workflow.py`; both branches feed into `validate_outputs` node
- [x] T041 [US2] Add `cv_tailored.md` and `artifacts/cv_tailoring_plan.json` to `src/bewerbungs_agent/io/writer.py` `write_final_outputs` and `write_artifacts` calls

**Checkpoint**: Run produces both `letter.md` and `cv_tailored.md`. User Story 2 independently testable.

---

## Phase 5: User Story 3 – Configure Writing Behaviour with a Starter Template (Priority: P2)

**Goal**: Full YAML starter template loading, override merge, AIDA mode, `list-templates` command.

**Independent Test**: Run same fixture job with `default_de_neutral` (standard, DE) vs `aida_light` (AIDA, DE); letter structure differs as configured by each template.

> **NOTE: Write tests FIRST (T042) — ensure they FAIL before implementing T043–T046**

- [x] T042 [P] [US3] Write unit tests for config merge in `tests/unit/test_config_merge.py`: override `language: EN` wins over template default `language: DE`; invalid override key (not in `MergedConfig` schema) raises `ValidationError`; `soft_skill_max` from override propagates to `MergedConfig`; no override → template value used unchanged
- [x] T043 [US3] Complete YAML loading and validation in `src/bewerbungs_agent/io/loader.py`: `load_starter_template(path: Path) -> StarterTemplate` with full Pydantic validation at load time; raise `ValueError` with field name on schema mismatch
- [x] T044 [US3] Complete `src/bewerbungs_agent/utils/merge.py`: deep merge overrides, reject keys absent from `MergedConfig` schema, validate final result
- [x] T045 [US3] Implement AIDA mode in `src/bewerbungs_agent/stages/write_letter.py`: load `prompts/styles/aida.md` when `config.mode == WritingMode.aida`; write `prompts/styles/aida.md` (Attention / Interest / Desire / Action structure, evidence-only storytelling, no invented scenes)
- [x] T046 [US3] Implement `list-templates` CLI command in `src/bewerbungs_agent/cli.py`: scan `<profile_dir>/templates/`, load each as `StarterTemplate`, print table (id, language, mode, length, tone) or JSON per `--json` flag

**Checkpoint**: Both templates produce structurally different outputs (standard vs AIDA). Override `--override '{"language":"EN"}'` overrides template language. `jobagent list-templates` prints available templates. User Story 3 independently testable.

---

## Phase 6: User Story 4 – Validate Output and Rewrite on Failure (Priority: P3)

**Goal**: Full validation of letter + CV against all rules; targeted rewrite loop; `jobagent validate` command.

**Independent Test**: Inject a draft with a known violation (unsupported claim). Run validator → violation reported. Run rewrite → violation resolved without introducing new ones.

> **NOTE: Write tests FIRST (T047, T049) — ensure they FAIL before implementing T048, T050**

- [x] T047 [P] [US4] Write unit tests for `validate` in `tests/unit/test_validate.py`: inject `source_compliance` violation → `ValidationResult.status == fail` with offending excerpt; inject text exceeding `length` → fail; inject 4 soft skills with `soft_skill_max: 3` → fail; inject `must_not_mention` term → fail; clean draft → all pass
- [x] T048 [US4] Implement `src/bewerbungs_agent/stages/validate.py`: deterministic rules (`source_compliance`, `length`, `redundancy`, `soft_skill_count`, `must_not_mention`) in pure Python; optional LLM-assisted rules (`tone`, `mode_rules`) behind `validation_rules` config flag; returns `{"letter_validation": ..., "cv_validation": ...}`
- [x] T049 [P] [US4] Write unit tests for `rewrite` in `tests/unit/test_rewrite.py`: only sections with violations are in rewrite prompt; passing sections text unchanged; `rewrite_count` incremented each call; when `rewrite_count >= max_rewrites` returns state without re-invoking LLM
- [x] T050 [US4] Implement `src/bewerbungs_agent/stages/rewrite.py`: extract failing section names from `ValidationReport.violations`; build targeted rewrite prompt with only those sections + `ContentPlan`; update `letter_draft.text` or `cv_tailoring_plan.tailored_text` for failing sections only; increment `rewrite_count`
- [x] T051 [US4] Wire `validate_outputs → should_rewrite → rewrite_if_needed → validate_outputs` conditional back-edge in `src/bewerbungs_agent/graph/workflow.py` using `should_rewrite` function per `contracts/pipeline-contract.md`
- [x] T052 [US4] Implement `jobagent validate` CLI command in `src/bewerbungs_agent/cli.py`: load draft file + job file, reconstruct minimal state, run `validate` stage, print per-rule pass/fail with excerpts; exit code 0 = all pass, 1 = failures
- [x] T053 [P] [US4] Write `prompts/validator.md` (LLM-assisted tone and mode-rules validation instructions)

**Checkpoint**: Running `jobagent run` triggers validation automatically; violations are rewritten. `jobagent validate --draft ... --job ...` reports per-rule status. User Story 4 independently testable.

---

## Phase 7: User Story 5 – Inspect Structured Intermediate Artifacts (Priority: P3)

**Goal**: All intermediate artifacts present, schema-valid, and written to output directory after every run.

**Independent Test**: Run agent on fixture job. Inspect `outputs/<run_id>/artifacts/` — all 6 artifact files present and loadable as their Pydantic types; `evidence_map.json` contains no source paths outside `data/examples/`.

- [x] T054 [US5] Complete `src/bewerbungs_agent/io/writer.py` `write_artifacts`: persist `requirements.json`, `evidence_map.json`, `content_plan.json`, `cv_tailoring_plan.json`, `validation_letter.json`, `validation_cv.json` as Pydantic `.model_dump()` JSON; skip fields that are `None`
- [x] T055 [US5] Add `known_gaps` extraction in `write_artifacts`: emit `evidence_map.known_gaps` as `artifacts/known_gaps.json` (list of strings); if empty, write empty list (not omit)

**Checkpoint**: All artifact files present after every complete run. `evidence_map.json` entries reference only approved source paths. User Story 5 independently testable.

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end integration, final wiring, tooling validation.

- [x] T056 [P] Add fixture job file `data/examples/jobs/sample_software_engineer.md` (realistic 300-word job ad) and update `tests/conftest.py` `fixture_job_path` to point to it
- [x] T057 Write `tests/integration/test_full_run.py`: invoke compiled graph with `fixture_job_path` + `data/examples/templates/default_de_neutral.yaml` + mock LLM client returning fixture responses; assert `letter.md` exists, `evidence_map.json` loads as `EvidenceMap`, all 6 artifact files present, no source path outside `data/examples/`
- [x] T058 [P] Compile pinned lockfiles: `uv pip compile pyproject.toml -o requirements.txt` and `uv pip compile pyproject.toml --extra dev -o requirements-dev.txt`; commit both files
- [x] T059 [P] Run `ruff check src/ tests/` and `mypy src/` — fix all reported errors
- [x] T060 Run full test suite `pytest tests/unit/ tests/integration/ -v` — all tests must pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately, all tasks parallelisable
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — no dependencies on US2–US5
- **US2 (Phase 4)**: Depends on US1 (needs evidence map + content plan in state)
- **US3 (Phase 5)**: Depends on Foundational — can proceed in parallel with US1/US2
- **US4 (Phase 6)**: Depends on US1 + US2 (validates both letter and CV outputs)
- **US5 (Phase 7)**: Depends on Foundational — artifact writer is a separate concern; can proceed with US1
- **Polish (Phase N)**: Depends on US1–US5 completion

### User Story Dependencies

- **US1 (P1)**: No story dependencies — start after Foundational
- **US2 (P2)**: Needs `selected_cv` and `evidence_map` from US1 pipeline
- **US3 (P2)**: No story dependencies — can proceed in parallel with US1/US2
- **US4 (P3)**: Needs letter draft (US1) and tailored CV (US2) to validate
- **US5 (P3)**: Needs artifact writer (T013 foundational); otherwise independent

### Within Each User Story

- Test tasks MUST be written and confirmed failing BEFORE corresponding implementation
- `build_prompt` / `parse_response` pure functions before stage node wiring
- Stage implemented before graph wiring
- Graph wiring before CLI command completion
- All story tasks complete before moving to next phase

### Parallel Opportunities

- All Setup tasks: fully parallel
- T007 (state models) and T008 (config models): parallel (different files)
- T010, T011, T013: parallel (different files, no inter-dependencies)
- Within US1: odd-numbered test tasks (T017, T019, T021, T023, T025, T027, T029) parallel with each other; each implementation task (T018, T020, …) follows its own test
- T033–T037 (prompt files): fully parallel with each other and with T031/T032 graph wiring
- US2 and US3: can proceed in parallel after US1 completes
- T058, T059: parallel (independent tools)

---

## Parallel Example: User Story 1

```bash
# Write all US1 test stubs in parallel (all different files):
Task T017: tests/unit/test_load_job.py
Task T019: tests/unit/test_extract_requirements.py
Task T021: tests/unit/test_load_profile.py
Task T023: tests/unit/test_select_cv_variant.py
Task T025: tests/unit/test_build_evidence_map.py
Task T027: tests/unit/test_plan_content.py
Task T029: tests/unit/test_write_letter.py

# Write all US1 prompts in parallel:
Task T033: prompts/system.md
Task T034: prompts/requirements.md
Task T035: prompts/planner.md
Task T036: prompts/writer.md
Task T037: prompts/styles/standard.md
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (cover letter generation end-to-end)
4. **STOP and VALIDATE**: `jobagent run` produces `letter.md` with full evidence map
5. Every claim traceable → MVP delivered

### Incremental Delivery

1. Setup + Foundational → skeleton in place
2. US1 (P1) → cover letter MVP, independently runnable
3. US2 (P2) → tailored CV added to same run
4. US3 (P2) → template config + AIDA mode enabled
5. US4 (P3) → validation + rewrite loop enforcing factual integrity
6. US5 (P3) → full artifact audit trail
7. Polish → integration tests, lockfiles, linting

---

## Notes

- `[P]` = different files, no incomplete-task dependencies — safe to parallelise
- `[US#]` label maps each task to its user story for traceability
- Tests MUST fail before implementation (TDD — Constitution Principle VI)
- Evidence enforcement is the most critical invariant: the writer stage MUST receive only `ContentPlan`, never raw `InternalKnowledge`
- Commit after each task or checkpoint
- Stop at any checkpoint to validate the story independently
