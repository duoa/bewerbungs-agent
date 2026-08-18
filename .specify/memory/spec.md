# Feature Specification: Bewerbungs-Agent – CLI Job Application System

**Feature Branch**: `001-bewerbungs-agent-core`
**Created**: 2026-04-01
**Status**: Draft
**Input**: User description: combined from `application_agent_v2.md` + constitution v1.0.0

## User Scenarios & Testing *(mandatory)*

### User Story 1 – Generate a Factually-Grounded Cover Letter (Priority: P1)

A user provides a job description file and selects a starter template.
The agent loads the user's approved internal knowledge (master profile, CV variants,
personal skills, previous letters, project documents), extracts the job's key
requirements, selects matching evidence, plans the content structure, and
generates a cover letter in the standard or AIDA writing mode as configured.
Every factual claim in the output can be traced back to an approved source.

**Why this priority**: This is the system's core deliverable. Without a correct,
evidence-backed cover letter, no other capability matters.

**Independent Test**: Can be tested with a single fixture job file and a minimal
master profile. The test passes if a cover letter is produced, every claim has a
source reference, and no invented fact appears.

**Acceptance Scenarios**:

1. **Given** a valid job file and a named starter template, **When** the user runs
   `jobagent run --job <file> --template <name>`, **Then** the system produces a
   cover letter and a requirement-to-evidence map in the output directory.

2. **Given** the generated cover letter, **When** each factual claim is
   cross-checked against the requirement-to-evidence map, **Then** every claim
   maps to at least one passage in an approved source document.

3. **Given** a job description that requires a skill absent from the internal
   profile, **When** the agent processes the run, **Then** the cover letter either
   omits the skill or emits it as a known gap — it MUST NOT invent the skill.

4. **Given** any run without an explicit writing-mode override, **When** the
   starter template defaults to `standard`, **Then** the letter follows the
   standard structure: role fit → relevant experience → working style →
   company motivation → closing.

---

### User Story 2 – Generate a Tailored CV Alongside the Letter (Priority: P2)

After producing the cover letter, the agent also produces a tailored CV by
selecting the best-matching CV variant for the role family and adjusting its
emphasis to align with the extracted requirements — without adding any fact
not present in the selected CV variant or master profile.

**Why this priority**: A tailored CV is the second primary output; it shares
the same evidence base as the letter and must be produced in the same run.

**Independent Test**: Run against a fixture job + known CV variant set.
The tailored CV MUST only contain facts present in the base variant or master
profile. Test passes if a diff between base variant and tailored output shows
only emphasis/ordering changes, not new content.

**Acceptance Scenarios**:

1. **Given** a run that produces a cover letter, **When** the run completes,
   **Then** a tailored CV is also present in the output directory.

2. **Given** multiple available CV variants, **When** the system selects a
   variant, **Then** the selected variant MUST be the closest match to the
   role family derived from the job description, unless the user explicitly
   overrides the selection.

3. **Given** the tailored CV, **When** its content is compared to the base
   CV variant and master profile, **Then** no new skills, roles, employers,
   dates, or results may appear that are absent from those approved sources.

---

### User Story 3 – Configure Writing Behaviour with a Starter Template (Priority: P2)

A user selects a named starter template to set persistent baseline defaults
(language, tone, length, writing mode, soft-skill limits, CV selection logic,
output sections). Run-specific overrides may be applied on top of the baseline
without altering the template file itself.

**Why this priority**: Without reusable baseline configuration, users must
re-specify all preferences on every run, defeating the system's purpose as a
recurring workflow tool.

**Independent Test**: Run the same job file with two different starter
templates and verify that the output tone, length range, and writing mode
differ as configured.

**Acceptance Scenarios**:

1. **Given** a starter template that sets `mode: aida`, **When** a run uses
   that template without overrides, **Then** the cover letter follows the
   AIDA structure (Attention / Interest / Desire / Action).

2. **Given** a starter template that sets `language: DE`, **When** a run
   overrides `language: EN`, **Then** the generated output is in English.

3. **Given** a starter template with `soft_skill_max: 2`, **When** the agent
   selects soft skills, **Then** at most 2 soft skills appear in the cover
   letter — regardless of how many are available in `personal_skills.md`.

4. **Given** a run with no language/mode overrides, **When** the run
   completes, **Then** the merged config used for the run is reflected in
   the validation artifact.

---

### User Story 4 – Validate Output and Rewrite on Failure (Priority: P3)

After generating outputs, the agent validates them against a set of rules:
source compliance, evidence coverage, tone match, length bounds, redundancy
limits, soft-skill count, and writing-mode rules. If validation fails, the
agent performs targeted rewriting of the failing sections only and re-validates.

**Why this priority**: Validation is the enforcement mechanism for factual
integrity. Without it, output quality degrades silently.

**Independent Test**: Inject a cover letter draft with a known violation (e.g.,
a claim referencing a technology not in the profile). Run the validator. It
MUST emit a validation failure. Run the rewrite step. The rewritten output MUST
resolve the violation without introducing new ones.

**Acceptance Scenarios**:

1. **Given** a generated draft with a claim unsupported by any approved source,
   **When** the validator runs, **Then** a validation failure is emitted
   identifying the unsupported claim.

2. **Given** a validation failure, **When** the rewrite step runs, **Then**
   only the failing section is rewritten; passing sections remain unchanged.

3. **Given** a letter that exceeds the configured length ceiling, **When**
   the validator runs, **Then** a length violation is reported and the rewrite
   step reduces length to within bounds.

4. **Given** a letter with more soft skills than the configured maximum,
   **When** the validator runs, **Then** a soft-skill violation is reported.

---

### User Story 5 – Inspect Structured Intermediate Artifacts (Priority: P3)

Each run persists typed intermediate artifacts so the user can audit the
pipeline: requirement extraction, evidence map, content plan, tone application
record, and validation report. These artifacts allow the user to understand
exactly what the agent decided and why at each step.

**Why this priority**: Auditability is essential for trust. The user must be
able to verify that the agent's reasoning is grounded in approved sources.

**Independent Test**: Run the agent on a fixture job. Verify that all listed
artifact types are present in the output directory, are valid according to their
expected schema, and that the evidence map contains no references outside the
approved source list.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the user inspects the output directory,
   **Then** the following artifacts are present: requirement extraction,
   evidence map, content plan, tone application record, validation report,
   known gaps / open questions.

2. **Given** the evidence map artifact, **When** each entry is checked,
   **Then** every referenced source path exists within the approved source
   directories.

3. **Given** the known gaps artifact, **When** the job required a skill not
   in the profile, **Then** that gap is explicitly listed rather than silently
   omitted or invented.

---

### Edge Cases

- What happens when the job file is malformed or empty?
- What happens when no CV variant matches the role family?
- What happens when `personal_skills.md` is absent?
- What happens when a rewrite loop fails to fix a violation after the maximum
  allowed iterations?
- What happens when a run override references a key not defined in the starter
  template schema?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-01**: The system MUST load a named starter template from the configured
  templates directory at the start of every run.
- **FR-02**: The system MUST merge starter-template defaults with run-specific
  overrides before any pipeline stage executes.
- **FR-03**: The system MUST load the job description and optional company
  information from user-specified files.
- **FR-04**: The system MUST extract at most 6 prioritised requirements from
  the job description: 1 core, 2 technical, 1 collaboration, 1 domain,
  1 optional.
- **FR-05**: The system MUST load the approved internal knowledge base
  (master profile, CV variants, personal skills, project documents,
  previous letters) from the configured profile directory.
- **FR-06**: The system MUST select the best-matching CV variant for the role
  family unless the user overrides the selection.
- **FR-07**: The system MUST map every selected factual claim to at least one
  passage in an approved source document before generating prose.
- **FR-08**: The system MUST produce a structured content plan (claim list,
  evidence references, section structure, selected soft skills, writing mode)
  before generating any prose.
- **FR-09**: The system MUST generate the cover letter exclusively from the
  approved content plan.
- **FR-10**: The system MUST tailor the selected CV variant to the role using
  only facts present in that variant and the master profile.
- **FR-11**: The system MUST validate final outputs against: source compliance,
  evidence coverage, tone match, length bounds, redundancy limits,
  soft-skill count, and writing-mode rules.
- **FR-12**: The system MUST support targeted section-level rewriting when
  validation fails; full-document regeneration as a validation bypass is
  not permitted.
- **FR-13**: The system MUST persist typed intermediate artifacts for every
  pipeline stage: requirement extraction, evidence map, content plan,
  tone application, validation report, known gaps.
- **FR-14**: The system MUST emit a known-gaps artifact listing any job
  requirement for which no supporting evidence was found in the approved
  sources.
- **FR-15**: The CLI MUST expose at minimum: `run`, `validate`, `eval`,
  `list-templates`.
- **FR-16**: The system MUST reject any run that references an unapproved
  source; the error MUST identify the offending source.
- **FR-17**: Soft-skill usage MUST be limited to the maximum configured in
  the active starter template, and each soft skill MUST be expressed through
  observable behaviour or outcomes, never as a bare adjective.
- **FR-18**: The AIDA writing mode MUST be available and MUST only be activated
  when explicitly enabled by the starter template or a run override.

### Key Entities

- **StarterTemplate**: A reusable baseline configuration defining language,
  tone, length range, writing mode, CV selection behaviour, soft-skill limits,
  output sections, and validation defaults. Identified by a name/ID.
- **RunInput**: The per-run inputs: job file path, optional company file,
  optional overrides, prioritised projects, must-not-mention list,
  why-company notes, optional storyboard hints.
- **MergedConfig**: The resolved configuration for a run: starter template
  defaults merged with run overrides. All pipeline stages operate on this.
- **RequirementExtraction**: Structured output of the extraction stage:
  core requirement, technical requirements, collaboration requirement,
  domain requirement, optional requirement, tone signals, must-include,
  must-avoid.
- **EvidenceMap**: Ordered list of claim → source mappings, where each source
  is an approved document path and passage reference.
- **ContentPlan**: The structured outline produced before prose generation:
  selected facts, evidence references, selected soft skills, section structure,
  writing mode, open questions, assumptions.
- **ValidationReport**: Per-rule pass/fail results with offending excerpts for
  each failure: source compliance, evidence coverage, tone, length, redundancy,
  soft-skill count, mode rules.
- **KnownGaps**: List of job requirements for which no evidence was found in
  the approved sources.
- **WorkflowState**: The typed container passed between all pipeline stages,
  accumulating the outputs of each completed stage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-01**: A user can complete a full application run (cover letter + tailored
  CV) from a job file and starter template in a single CLI command.
- **SC-02**: 100% of factual claims in every generated output are traceable to
  an entry in the run's evidence map, which references only approved sources.
- **SC-03**: Zero invented skills, roles, employers, results, or dates appear
  in any generated output across the test suite.
- **SC-04**: The validator correctly identifies all injected policy violations
  in the test suite (coverage: source compliance, length, redundancy,
  soft-skill count, mode rules).
- **SC-05**: The rewrite loop resolves basic validation failures (single-rule
  violations) without introducing new violations.
- **SC-06**: Running the same job file twice with the same starter template and
  no overrides produces structurally equivalent outputs (same sections, same
  evidence references, same writing mode).
- **SC-07**: A user can override any starter-template value for a single run
  without modifying the template file.
- **SC-08**: All mandatory intermediate artifacts are present and schema-valid
  after every successful run.
- **SC-09**: Unit tests cover all parsing, config-merge, CV-selection,
  evidence-mapping, and validation logic; integration tests cover at least
  one end-to-end workflow on fixture inputs.

## Assumptions

- The user maintains the approved source files (master profile, CV variants,
  `personal_skills.md`, project documents, previous letters) outside the
  agent's source code, in a configurable profile directory.
- The job description and optional company information are provided as local
  files (Markdown or plain text) per run; the agent does not scrape the web.
- CV variants exist as pre-authored documents with associated metadata; the
  agent tailors them but does not generate a CV from scratch.
- At least one starter template will be provided at initial project setup;
  the system does not generate starter templates automatically.
- The output language (German / English) is controlled by the starter template
  and per-run overrides; the agent does not auto-detect the target language.
- The AIDA writing mode is opt-in only and does not activate unless the active
  configuration explicitly enables it.
- RAG over previous letters is out of scope for the MVP; previous letters are
  loaded as full-text and used for tone reference only.
- GUI, web interface, autonomous job scraping, email sending, and automatic
  submission workflows are out of scope.
- Multiple-draft ranking and automatic draft comparison are out of scope for MVP.
- The eval layer (Promptfoo or equivalent) is a separate concern from the core
  pipeline and is treated as a future testing enhancement.
