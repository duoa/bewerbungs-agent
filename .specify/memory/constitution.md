<!--
SYNC IMPACT REPORT
==================
Version change: (unversioned template) → 1.0.0
Principles added:
  - I. Factual Integrity (NON-NEGOTIABLE)
  - II. Approved Sources Only
  - III. Structured-Before-Generative Workflow
  - IV. Separation of Concerns
  - V. Deterministic Interfaces & Typed State
  - VI. Test Coverage
Sections added:
  - Approved Source Registry
  - Development Workflow
  - Governance
Templates reviewed:
  - .specify/templates/plan-template.md  ✅ aligned (Constitution Check section intact)
  - .specify/templates/spec-template.md  ✅ aligned (no mandatory sections conflict)
  - .specify/templates/tasks-template.md ✅ aligned (test phases reflect unit/integration/golden)
  - .specify/templates/commands/         ✅ no command files present (nothing to update)
Deferred TODOs: none
-->

# Bewerbungs-Agent Constitution

## Core Principles

### I. Factual Integrity (NON-NEGOTIABLE)

The system MUST NOT invent, fabricate, or hallucinate any of the following:
skills, tools, technologies, roles, job titles, employers, dates, responsibilities,
achievements, metrics, or results.

Every concrete claim that appears in a generated cover letter, CV section, or
application output MUST be traceable to a specific passage in an approved source
document. If no supporting evidence exists, the claim MUST be omitted.

**Rationale**: Job applications carry legal and reputational weight. A single
fabricated credential or result can constitute fraud. The agent exists to
articulate what the candidate actually is, not to invent a better version.

### II. Approved Sources Only

The system MUST load content exclusively from the following approved internal
sources. No external data, web lookups, or model-generated "background knowledge"
may substitute for or augment these sources:

- `master_profile.md` — canonical identity, career narrative, core values
- CV variants (e.g., `cv_software.md`, `cv_data.md`) — role-specific skill sets
- `personal_skills.md` — validated competencies and proficiency levels
- Project documents (e.g., `projects/*.md`) — concrete project evidence
- Previous cover letters (`letters/*.md`) — validated phrasing and tone examples
- Job description (run-specific input) — target role requirements
- Company information (run-specific input) — employer context
- Storyboard / AIDA input (optional, run-specific) — structural narrative guidance
- Starter-template configuration (`templates/*.yaml` / `templates/*.md`) —
  persistent structural and tonal baselines

Any source not in this list MUST be rejected at load time with a clear error.

**Rationale**: Closed-world sourcing ensures reproducibility, auditability, and
factual correctness across every run.

### III. Structured-Before-Generative Workflow

Every application run MUST execute the following pipeline stages in order. No
generative (LLM) call may occur before all upstream structured stages complete
successfully:

1. **Load configuration** — resolve run parameters and override stack
2. **Extract requirements** — parse job description into structured requirement set
3. **Load internal knowledge** — load and index all approved source documents
4. **Select evidence** — match requirements to evidence passages; fail fast if
   minimum coverage thresholds are unmet
5. **Plan content** — produce a structured outline (sections, claims, evidence
   references) without generating prose
6. **Generate outputs** — produce prose only from the approved structured plan
7. **Validate** — check factual grounding, source coverage, and schema conformance
8. **Rewrite if needed** — targeted regeneration of failing sections only;
   full regeneration is not permitted as a validation bypass

**Rationale**: Separating structured reasoning from generation prevents the model
from filling gaps with invented content, and makes each stage independently
testable and auditable.

### IV. Separation of Concerns

Content selection and tone/style application MUST be implemented as distinct,
independently testable pipeline stages. A tone or style transformation MUST NOT
alter the factual claims or evidence references established in the plan.

- **Selection stage** outputs: which claims to include, which evidence to cite,
  section structure.
- **Tone stage** inputs: the selection output (immutable); outputs: styled prose
  only.

No tone configuration (e.g., formal, assertive, storytelling) may introduce,
remove, or modify factual content.

**Rationale**: Conflating selection and style makes it impossible to test either
in isolation and creates a vector for factual drift during stylistic rewrites.

### V. Deterministic Interfaces & Typed State

All pipeline stage interfaces MUST be defined with explicit Python type
annotations (Pydantic models or dataclasses). Stages communicate exclusively via
typed structured objects — no untyped dicts, free-form strings, or implicit
globals between stages.

- Every workflow node MUST accept a typed input model and return a typed output
  model.
- Configuration MUST be validated at load time against a declared schema; invalid
  configuration MUST raise an error before any pipeline stage runs.
- The CLI MUST expose a deterministic, scriptable interface: given the same inputs
  and configuration, it MUST produce structurally equivalent outputs.

**Rationale**: Typed interfaces catch integration bugs at development time,
enable confident mocking in tests, and make the pipeline auditable by inspection.

### VI. Test Coverage

The project MUST maintain the following test layers:

- **Unit tests**: every pipeline stage tested in isolation with mocked
  adjacent stages; coverage target ≥ 80 % of stage logic.
- **Integration tests**: end-to-end pipeline runs against a fixture set of
  approved source documents and a sample job description; output validated for
  schema conformance and source grounding.
- **Golden tests** *(deferred to later milestone)*: captured reference outputs
  compared on each run to detect unintended output drift; explicitly opt-in per
  test case.

Tests MUST be written before implementation (TDD). A failing test suite MUST
block merge.

**Rationale**: An agent that cannot be tested cannot be trusted. Test coverage
enforces the factual-integrity and separation-of-concerns principles mechanically.

## Approved Source Registry

This section lists the canonical paths and roles of each approved source type.
Actual paths are resolved relative to the run's `--profile-dir` argument.

| Source type | Default path pattern | Required? |
|---|---|---|
| Master profile | `profile/master_profile.md` | REQUIRED |
| CV variants | `profile/cv_*.md` | ≥ 1 REQUIRED |
| Personal skills | `profile/personal_skills.md` | REQUIRED |
| Project documents | `profile/projects/*.md` | OPTIONAL |
| Previous letters | `profile/letters/*.md` | OPTIONAL |
| Job description | `run/job_description.md` | REQUIRED |
| Company info | `run/company_info.md` | OPTIONAL |
| Storyboard/AIDA | `run/storyboard.md` | OPTIONAL |
| Starter templates | `templates/*.{yaml,md}` | ≥ 1 REQUIRED |

Sources marked REQUIRED MUST be present; the pipeline MUST fail at load time
with a descriptive error if any REQUIRED source is missing.

## Development Workflow

- New features MUST begin with a spec (`/speckit.specify`) before any code.
- Implementation MUST NOT start until the plan (`/speckit.plan`) is approved.
- Each pipeline stage MUST be implemented as an independent Python module under
  `src/bewerbungs_agent/stages/`.
- CLI entry point lives in `src/bewerbungs_agent/cli.py`.
- All configuration schemas live in `src/bewerbungs_agent/config/`.
- Tests mirror the source tree under `tests/`.
- The project uses `pyproject.toml` for packaging; no `setup.py`.
- Commits MUST reference the task ID from `tasks.md`.

## Governance

This constitution supersedes all other development guidance. Any practice,
shortcut, or tool behaviour that contradicts a principle in this document MUST be
treated as a defect and corrected before the work is considered done.

**Amendment procedure**:
1. Propose the amendment in a spec or PR description.
2. Increment the version according to the semantic versioning rules below.
3. Update `LAST_AMENDED_DATE` to the date of merge.
4. Run the consistency propagation checklist (Principle alignments across
   templates) and record results in the Sync Impact Report.
5. Merge only after propagation is complete.

**Versioning policy**:
- MAJOR bump: removal or backward-incompatible redefinition of any principle.
- MINOR bump: new principle or section added, or material expansion of guidance.
- PATCH bump: clarifications, wording fixes, non-semantic refinements.

**Compliance review**: Every PR MUST include a "Constitution Check" confirming
no principle is violated. If a violation is necessary, it MUST be documented in
the plan's Complexity Tracking table with explicit justification.

**Version**: 1.0.0 | **Ratified**: 2026-04-01 | **Last Amended**: 2026-04-01
