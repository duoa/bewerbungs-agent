# Bewerbungs-Agent — Engineering Reference

This document describes the architecture, pipeline, data models, configuration
system, and extension points of the `bewerbungs-agent` tool. It is intended as
the primary reference for understanding what was built and how to improve it.

---

## 1. What it does

`bewerbungs-agent` is a CLI tool that generates factually-grounded cover letters
and tailored CVs for job applications. Given a job description and a personal
profile directory, it runs a multi-stage LLM pipeline that:

1. Extracts structured requirements from the job description
2. Maps those requirements to evidence from approved personal sources (CV, profile, projects)
3. Plans the letter content (no prose, only a structured plan)
4. Generates the letter from the plan only — never from raw profile data
5. Tailors the CV variant in parallel
6. Validates both outputs against deterministic rules
7. Rewrites failing sections if needed

The key design invariant: **the LLM that writes the letter never sees the raw
profile.** It only receives a JSON content plan derived from the evidence map.
This prevents hallucination of facts not in the approved sources.

---

## 2. Repository layout

```
bewerbungs-agent/
├── src/bewerbungs_agent/
│   ├── cli.py                  # Typer CLI (jobagent command)
│   ├── config/
│   │   └── models.py           # StarterTemplate, RunInput, MergedConfig
│   ├── graph/
│   │   └── workflow.py         # LangGraph StateGraph definition
│   ├── io/
│   │   ├── loader.py           # File loaders (JSON, YAML, Markdown, PDF)
│   │   └── writer.py           # Artifact and final output writers
│   ├── models/
│   │   └── state.py            # All Pydantic state models (18 classes)
│   ├── stages/                 # One file per pipeline stage
│   │   ├── load_job.py
│   │   ├── extract_requirements.py
│   │   ├── load_profile.py
│   │   ├── select_cv_variant.py
│   │   ├── build_evidence_map.py
│   │   ├── plan_content.py
│   │   ├── write_letter.py
│   │   ├── tailor_cv.py
│   │   ├── validate.py
│   │   └── rewrite.py
│   └── utils/
│       ├── llm_client.py       # Anthropic client + injectable Protocol
│       ├── merge.py            # Template + override merge logic
│       └── prompts.py          # Prompt file loader
├── prompts/                    # Markdown prompt files (loaded at runtime)
│   ├── system.md               # Factuality rules (sent as system prompt)
│   ├── requirements.md         # Requirement extraction instructions
│   ├── planner.md              # Content plan instructions
│   ├── writer.md               # Letter generation instructions
│   ├── tailor_cv.md            # CV tailoring instructions
│   ├── validator.md            # LLM-assisted validation instructions
│   └── styles/
│       ├── standard.md         # Standard letter structure
│       └── aida.md             # AIDA letter structure
├── data/
│   └── examples/               # Sample profile for testing
│       ├── profile/
│       │   ├── master_profile.json
│       │   ├── personal_skills.md
│       │   └── projects/
│       ├── cvs/
│       │   ├── cv_software.md
│       │   └── metadata/
│       │       └── cv_software.json
│       ├── templates/
│       │   └── default_de_neutral.yaml
│       └── jobs/
│           └── sample_software_engineer.md
├── tests/
│   ├── unit/                   # Pure function tests (no LLM calls)
│   └── integration/            # Full graph run with mock LLM
├── specs/001-bewerbungs-agent-core/   # Design docs
│   ├── spec.md
│   ├── plan.md
│   ├── data-model.md
│   ├── tasks.md
│   └── contracts/
└── pyproject.toml
```

---

## 3. Pipeline stages

The pipeline runs as a LangGraph `StateGraph`. Each node receives the full
`WorkflowState` and returns a partial dict of updates.

```
load_job
    ↓
extract_requirements
    ↓
load_profile
    ↓
select_cv_variant
    ↓
build_evidence_map
    ↓
plan_content
    ↓
    ├── write_letter ──┐   (equal-depth parallel branches — required for
    └── tailor_cv ─────┘    LangGraph fan-in to work correctly)
                       ↓
               hiring_review
                       ↓
            targeted_rewrite
                       ↓
               validate_outputs
                       ↓
            ┌── should_rewrite? ──┐
            │ fail + rewrites left │ pass (or max reached)
            ↓                      ↓
      rewrite_if_needed           END
            ↓
      validate_outputs (loop)
```

### Stage by stage

| Stage | Input from state | Output to state | LLM? |
|-------|-----------------|-----------------|------|
| `load_job` | `config.job_file`, `company_file`, `storyboard_file` | `job_context` | No |
| `extract_requirements` | `job_context` | `requirements` | Yes |
| `load_profile` | `config.profile_dir` | `knowledge` | No |
| `select_cv_variant` | `knowledge.cv_variants`, `requirements` | `selected_cv` | Yes (or override) |
| `build_evidence_map` | `requirements`, `selected_cv`, `knowledge` (excerpts only) | `evidence_map` | Yes |
| `plan_content` | `requirements`, `evidence_map`, `config` | `content_plan` | Yes |
| `write_letter` | `content_plan` (JSON only) | `letter_draft` | Yes |
| `tailor_cv` | `selected_cv`, `requirements`, `evidence_map` | `cv_tailoring_plan` | Yes |
| `hiring_review` | `letter_draft`, `requirements`, `config.review_config` | `letter_review` | Yes |
| `targeted_rewrite` | `letter_draft`, `letter_review`, `requirements` | `letter_draft` (overwritten) | Yes |
| `validate_outputs` | `letter_draft`, `content_plan`, `config` | `letter_validation`, `cv_validation` | No |
| `rewrite_if_needed` | `letter_draft`, `letter_validation`, `content_plan` | `letter_draft`, `rewrite_count` | Yes |

**Critical isolation rules:**
- `write_letter` receives **only** `ContentPlan` JSON — never `InternalKnowledge`
- `build_evidence_map` receives full CV text, full personal skills, and up to 5 project documents from knowledge — no raw knowledge beyond these
- `plan_content` receives **only** `requirements + evidence_map` — no raw knowledge
- `hiring_review` and `targeted_rewrite` receive **only** `letter_draft.text + requirements` — no profile, knowledge, content plan, or evidence map
- Source files in `EvidenceItem` are validated against approved prefixes: `profile/`, `cvs/`, `letters/`

---

## 4. Data models (`models/state.py`)

All inter-stage communication is typed via Pydantic v2 models. `WorkflowState`
is the single accumulator threaded through every node.

```
WorkflowState
├── config: MergedConfig          ← from config merge, immutable for the run
├── job_context: JobContext        ← raw text + parsed fields from job files
├── requirements: RequirementExtraction
│   ├── core_requirement: str
│   ├── technical_requirements: list[str]
│   ├── collaboration_requirement: str | None
│   ├── domain_requirement: str | None
│   ├── tone_signals: list[str]
│   ├── must_include: list[str]
│   └── must_avoid: list[str]
├── knowledge: InternalKnowledge
│   ├── master_profile: dict       ← from master_profile.json
│   ├── cv_variants: list[CVVariantMetadata]
│   ├── personal_skills: str       ← from personal_skills.md
│   ├── project_docs: dict[str, str]
│   └── previous_letters: dict[str, str]
├── selected_cv: SelectedCV
│   ├── variant_id: str
│   ├── full_text: str
│   └── selection_reason: str
├── evidence_map: EvidenceMap
│   ├── items: list[EvidenceItem]
│   │   ├── claim: str             ← the factual claim
│   │   ├── source_type: str       ← "cv_variant" | "master_profile" | ...
│   │   ├── source_file: str       ← relative path under profile_dir
│   │   └── passage: str           ← verbatim excerpt from source
│   └── known_gaps: list[str]      ← requirements with no evidence
├── content_plan: ContentPlan
│   ├── sections: list[SectionPlan]
│   │   ├── title: str
│   │   ├── key_claims: list[str]  ← bullets, not prose
│   │   └── evidence_refs: list[str]
│   └── selected_soft_skills: list[SoftSkill]
├── letter_draft: LetterDraft
│   ├── text: str                  ← Markdown prose
│   ├── char_count: int
│   ├── mode: WritingMode
│   └── content_plan_hash: str     ← SHA-256 of ContentPlan used
├── cv_tailoring_plan: CVTailoringPlan
│   ├── changes: list[CVTailoringChange]
│   │   ├── section: str
│   │   ├── action: str            ← "emphasise"|"reorder"|"include"|"exclude"
│   │   └── rationale: str
│   └── tailored_text: str
├── letter_review: LetterReviewReport | None
│   ├── sections: list[SectionReview]
│   │   ├── section_name: str
│   │   ├── strengths: list[str]
│   │   ├── weaknesses: list[WeaknessEntry]
│   │   │   ├── text: str
│   │   │   ├── severity: WeaknessSeverity   ← low | medium | high
│   │   │   └── priority_fix: str
│   │   └── assessment: str
│   ├── overall_assessment: str
│   └── sections_to_rewrite: list[str]       ← pre-computed from rewrite_threshold
├── letter_validation: ValidationReport
├── cv_validation: ValidationReport
├── rewrite_count: int
└── max_rewrites: int              ← default 2
```

---

## 5. Configuration system (`config/models.py`)

Configuration flows through three layers:

```
StarterTemplate (YAML file)
    +
RunInput (CLI args)
    ↓
merge_config()
    ↓
MergedConfig (used by all stages)
```

**StarterTemplate** (`data/<profile>/templates/<name>.yaml`) sets baseline
behaviour: language, length mode, writing mode (standard/aida), tone,
soft_skill_max, cv_tailoring, output_sections, validation_rules.

**RunInput** carries per-run values: job file path, optional company/storyboard
files, overrides dict, must_not_mention list, why_company bullets, cv_variant_override.

**`merge_config()`** deep-merges `run.overrides` on top of the template dict,
then validates the result through `MergedConfig`. `MergedConfig` has
`extra="forbid"`, so unknown override keys raise `ValidationError` immediately.

**Override example** (CLI):
```bash
jobagent run --job job.md --template default_de_neutral \
  --override '{"language":"EN","soft_skill_max":2}'
```

---

## 6. LLM client (`utils/llm_client.py`)

All LLM calls use the **tool-use** pattern — every call supplies a JSON Schema
and forces the model to return structured output via `tool_choice: {type: tool}`.

```python
class LLMClient(Protocol):
    def call(messages, tool_schema, system="") -> dict: ...
```

`AnthropicLLMClient` uses `claude-sonnet-4-6`. To swap in a different model or
provider, implement the `LLMClient` protocol and pass it to stages directly or
patch `get_llm_client()`.

In tests, `get_llm_client` is monkeypatched per-stage or replaced with a
schema-dispatching mock in integration tests.

---

## 7. Prompt system (`utils/prompts.py`)

Prompts live as plain Markdown files under `prompts/`. They are loaded at
runtime by `load_prompt(name)` and `load_style(mode)`.

```
prompts/
├── system.md        → always sent as the system prompt
├── requirements.md  → appended to the extract_requirements user message
├── planner.md       → appended to the plan_content user message
├── writer.md        → appended to the write_letter user message
├── tailor_cv.md     → appended to the tailor_cv user message
├── validator.md     → for LLM-assisted validation (future)
└── styles/
    ├── standard.md  → loaded when mode=standard, appended to writer prompt
    └── aida.md      → loaded when mode=aida, appended to writer prompt
```

Override the prompts directory with the env var `BEWERBUNGS_PROMPTS_DIR`.
This lets you iterate on prompts without touching source code.

---

## 8. Stage implementation pattern

Every stage follows the same pure-function structure:

```python
def build_prompt(state: WorkflowState) -> list[dict[str, Any]]:
    """Assembles the message list. Pure function — no LLM calls."""
    ...

def parse_response(data: dict[str, Any]) -> SomeModel:
    """Validates the LLM response dict. Raises ValueError on constraint violations."""
    ...

def stage_name(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node. Calls LLM, delegates to build_prompt and parse_response."""
    client = get_llm_client()
    messages = build_prompt(state)
    response = client.call(messages, SCHEMA, system=load_prompt("system"))
    return {"state_field": parse_response(response)}
```

`build_prompt` and `parse_response` are the testable units — they have no side
effects and can be tested without any mocking.

---

## 9. Validation rules (`stages/validate.py`)

Validation is **deterministic** (pure Python, no LLM). Rules run after both
`write_letter` and `tailor_cv` complete.

| Rule | What it checks | Fails when |
|------|---------------|------------|
| `source_compliance` | `letter_draft.content_plan_hash` matches SHA-256 of current `content_plan` | Hash mismatch (letter not from pipeline) or missing hash |
| `length` | `letter_draft.char_count` within mode range | short: 1200–1800, normal: 2000–3000, long: 3200–4000 |
| `soft_skill_count` | `content_plan.selected_soft_skills` count | Exceeds `config.soft_skill_max` |
| `must_not_mention` | Letter text contains forbidden terms | Any term from `config.must_not_mention` found (case-insensitive) |

`ValidationReport.passed = False` triggers the `should_rewrite` conditional
edge. Up to `max_rewrites` (default 2) rewrite attempts are made.

`prompts/validator.md` defines additional **LLM-assisted rules** (`tone`,
`mode_rules`) that are not yet wired — they are the next extension point.

---

## 10. Output artifacts

After every run, outputs are written to `outputs/<run_id>/`:

```
outputs/<run_id>/
├── letter.md                  ← final cover letter (Markdown)
├── cv_tailored.md             ← tailored CV (Markdown)
└── artifacts/
    ├── requirements.json      ← RequirementExtraction
    ├── evidence_map.json      ← EvidenceMap (all claims + sources)
    ├── known_gaps.json        ← list of requirements with no evidence
    ├── content_plan.json      ← ContentPlan (the pre-prose blueprint)
    ├── cv_tailoring_plan.json ← CVTailoringPlan (changes + full text)
    ├── validation_letter.json ← ValidationReport for the letter
    └── validation_cv.json     ← ValidationReport for the CV
```

**Debugging tip:** if the letter quality is poor, read `evidence_map.json` and
`content_plan.json` first. The letter can only be as good as the evidence the
LLM found and the plan it built from it. `known_gaps.json` shows which job
requirements had no matching evidence in your profile.

---

## 11. Profile directory structure

```
<profile_dir>/               (set via --profile-dir or BEWERBUNGS_PROFILE_DIR)
├── profile/
│   ├── master_profile.json  ← required: biographical facts, roles, education
│   ├── personal_skills.md   ← required: skills with observable evidence
│   └── projects/            ← optional: one .md per project
├── cvs/
│   ├── cv_software.md       ← full CV text (Markdown or PDF)
│   └── metadata/
│       └── cv_software.json ← variant metadata (variant_id, role_families, skills)
├── letters/                 ← optional: previous cover letters as examples
└── templates/
    └── default_de_neutral.yaml
```

**CV variant metadata** (`cvs/metadata/*.json`):
```json
{
  "variant_id": "cv_software",
  "file_path": "cv_software.md",
  "role_families": ["software-engineering", "backend"],
  "skills": ["Python", "Kubernetes"],
  "summary": "8 years Python backend + data pipelines."
}
```
`file_path` is relative to the `cvs/` directory.

---

## 12. CLI commands

```bash
# Full run
jobagent run --job <path> --template <id> --profile-dir <dir>
  [--company <path>] [--storyboard <path>]
  [--override '{"language":"EN"}']
  [--cv-variant <id>]
  [--output-dir <dir>]
  [--dry-run]

# Validate an existing draft
jobagent validate --draft letter.md --job job.md --template <id>

# List available templates
jobagent list-templates [--json]
```

Exit codes: 0 = success, 1 = validation failures, 2 = file not found, 3 = config error.

---

## 13. Testing

```bash
# All unit tests (pure functions, no LLM calls, ~0.1s)
.venv/bin/pytest tests/unit/ -v

# Integration test (full graph, mock LLM dispatched by schema title)
.venv/bin/pytest tests/integration/ -v

# Linting
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
```

**Unit test pattern:** every stage has a `TestBuildPrompt` class (tests prompt
content without LLM) and a `TestParseResponse` class (tests constraint
enforcement on mock responses).

**Integration mock:** `tests/integration/test_full_run.py` uses a
`MagicMock.call.side_effect` function that dispatches by `tool_schema["title"]`,
so parallel branches (`write_letter` + `tailor_cv`) always get the right response
regardless of execution order.

---

## 14. Known limitations and improvement areas

### Prompt quality
The prompts in `prompts/` are functional but not tuned. The biggest quality
lever is `prompts/planner.md` — the content plan directly determines what the
letter can say. Iterating on this prompt (without touching code) will have the
most impact.

### LLM-assisted validation not wired
`prompts/validator.md` defines `tone` and `mode_rules` checks. The `validate.py`
stage currently only runs deterministic rules. Wiring the LLM-assisted path
(behind `config.validation_rules`) is the next natural extension.

### source_compliance is hash-based
The `source_compliance` rule checks whether the letter was generated from the
current `ContentPlan` by comparing hashes. It does not do semantic claim
verification (checking whether each sentence in the letter is traceable to an
evidence item). Semantic verification would require a second LLM pass.

### Post-validation rewrite is whole-letter
The `rewrite_if_needed` stage (triggered when deterministic validation fails)
still rewrites the entire letter. The pre-validation `targeted_rewrite` stage
(feature 005) already operates at section granularity using the hiring-review
report. Aligning `rewrite_if_needed` to the same section-level mechanism would
make validation-driven rewrites more precise and cheaper.

### No streaming output
The CLI prints stage names as they complete but does not stream the letter text.
LangGraph supports streaming — adding `--stream` to pipe the letter as it
generates is straightforward.

### PDF support
`load_pdf` uses `pypdf` which may emit warnings for malformed PDFs. Switching
to `pdfminer.six` or `pymupdf` would give cleaner text extraction.

### No eval harness
`jobagent eval` is stubbed. A golden-test harness that runs the pipeline on a
fixture job and diffs the output against a reference letter would let you
measure prompt changes systematically.

### German/English only tested
The language field is free-form (`"DE"`, `"EN"`). The prompts say "write in
{language}" but no locale-specific formatting rules are applied.

---

## 15. MLflow Observability

MLflow tracking is opt-in. When enabled, every pipeline run is logged to a local
file-based tracking store (`mlruns/` in the repo root). The UI lets you compare
runs side by side — useful for iterating on prompts or thinking settings.

### Enabling tracking

Add to your starter template YAML (e.g., `data/templates/default_de_neutral.yaml`):

```yaml
tracking:
  enabled: true
  tracking_uri: mlruns        # relative path; resolves from the directory where the CLI runs
  experiment_name: bewerbungs-agent
```

Install MLflow if not already present:

```bash
uv add mlflow
```

Run the agent normally — tracking happens automatically:

```bash
uv run jobagent run --job data/examples/jobs/sample.md --template default_de_neutral
```

### Viewing runs

Start the UI **from the repo root** (same directory where `mlruns/` lives):

```bash
cd /path/to/bewerbungs-agent
mlflow ui --backend-store-uri mlruns
# → http://127.0.0.1:5000
```

### What is tracked

Each run records:

| Type | Key | Example value |
|------|-----|---------------|
| Param | `run_id` | `4ffbe3df` |
| Param | `model` | `claude-sonnet-4-6` |
| Param | `template_id` | `default_de_neutral` |
| Param | `thinking_enabled_global` | `False` |
| Tag | `stage.plan_content.thinking_enabled` | `true` |
| Tag | `stage.plan_content.prompt_hash` | `a3f9c12d4e7b8091` (16-char SHA-256) |
| Metric | `evidence_count` | `8` |
| Metric | `gaps_count` | `2` |
| Metric | `letter_char_count` | `2743` |
| Metric | `validation_passes` | `1` |
| Metric | `rewrite_count` | `0` |

The `prompt_hash` is a SHA-256 of the prompt file content at run time.
It changes automatically whenever the file changes — no manual versioning needed.

### Prompt experimentation workflow

1. Run once → note `stage.write_letter.prompt_hash` in the UI
2. Edit `prompts/writer.md`
3. Run again → new hash appears → compare `letter_char_count` and output quality
4. Use the MLflow UI **Compare** view (select 2+ runs) to diff all params and metrics

### Per-stage thinking configuration

To enable extended thinking for specific stages:

```yaml
thinking:
  enabled: false          # global default: off

stage_thinking:
  plan_content:
    enabled: true
    effort: high          # low / medium / high → maps to 1024 / 8000 / 16000 budget_tokens
  build_evidence_map:
    enabled: true
    effort: medium
```

Thinking settings are logged as tags per stage, so you can filter and compare
runs where thinking was active vs. not.

### Tracking failure behaviour

Tracking is non-blocking. If the tracking store is unavailable (disk full,
permissions error, etc.), a `UserWarning` is emitted to stderr and the pipeline
continues normally. A failed write never aborts a run.

### Known gotcha: stuck RUNNING runs

If the CLI is killed with Ctrl+C during a run, the MLflow run is closed cleanly
via a `finally` block. In older versions of the code (before this fix was added),
interrupted runs were left in RUNNING state indefinitely.

To clean up any leftover RUNNING runs manually:

```python
import mlflow
client = mlflow.MlflowClient(tracking_uri="mlruns")
exp = client.get_experiment_by_name("bewerbungs-agent")
for run in client.search_runs(exp.experiment_id, filter_string="attributes.status = 'RUNNING'"):
    client.set_terminated(run.info.run_id, status="KILLED")
    print("closed:", run.info.run_name)
```

### Known gotcha: merge_config must list all template fields explicitly

`merge_config()` in `src/bewerbungs_agent/utils/merge.py` builds a `base` dict
manually from `StarterTemplate` fields. Any field added to `StarterTemplate`
**must also be added to this dict** or it will silently fall back to the
`MergedConfig` default, ignoring whatever the user set in their YAML.

This is what caused the tracking config to be ignored initially (tracking was
always `enabled=False` regardless of the template). The fix is in `merge.py`
under the `# IMPORTANT` comment above the `base` dict.

---

## 16. Hiring-Manager Review and Targeted Rewrite (`stages/hiring_review.py`, `stages/targeted_rewrite.py`)

Feature 005 adds two new stages after `write_letter` and before `validate_outputs`:

**`hiring_review`** — evaluates the generated letter section-by-section from a hiring manager's perspective. It calls Claude with the letter text and role requirements (no profile data), then produces a `LetterReviewReport` stored in `WorkflowState.letter_review`. The report contains per-section strengths, weaknesses (with severity and priority fix), and a pre-computed list of sections that need rewriting based on the configured threshold.

**`targeted_rewrite`** — uses the review report to rewrite only the flagged sections. Sections not listed in `sections_to_rewrite` are reproduced verbatim by the LLM. The rewritten letter overwrites `letter_draft` in-place, so `validate_outputs` works unchanged.

### Pipeline topology

```
write_letter → hiring_review → targeted_rewrite → validate_outputs
tailor_cv    →                                  → validate_outputs  (fan-in unchanged)
```

### Configuration

Add to your starter template YAML:

```yaml
review_config:
  enabled: true                      # set false to skip both stages entirely
  dimensions:                        # which dimensions to evaluate (all 5 by default)
    - clarity
    - specificity
    - credibility
    - role_relevance
    - differentiation
  rewrite_threshold: medium          # minimum severity that triggers rewriting (low/medium/high)
```

Or pass via run-level `--override`:

```bash
jobagent run ... --override '{"review_config": {"rewrite_threshold": "high"}}'
```

### What is tracked in MLflow

Both stages call `tracker.log_stage()` when MLflow tracking is enabled:
- `stage_name`: `"hiring_review"` / `"targeted_rewrite"`
- `model`: Claude model name
- `thinking`: enabled/effort if configured
- `prompt_name` + `prompt_hash`: for prompt versioning

The review summary is also printed in the CLI output after a run:
```
  letter_review  (4 sections reviewed, 1 rewritten)
```

### Non-blocking behaviour

Both stages catch all exceptions from the LLM call and emit a `warnings.warn()`. If either stage fails, the original `letter_draft` is preserved and the pipeline continues to validation. Pipeline abort rate from review/rewrite failures is 0%.

### Factual-integrity enforcement

The rewrite stage receives only:
- The generated letter text
- The structured role requirements
- The structured review report

It does NOT receive the profile, CV text, content plan, or evidence map. The system prompt (`prompts/targeted_rewriter.md`) explicitly forbids introducing any fact not present in the provided inputs.

### Feature 009 — full job context in the review prompt

Feature 009 extends the **hiring_review** stage's prompt with three additive context blocks and one new always-on dimension. All changes are confined to `stages/hiring_review.py::build_prompt` and `prompts/hiring_reviewer.md`. No schema change, no pipeline-graph change, no edits to other prompts. The `LetterReviewReport` Pydantic schema is unchanged; the new dimension routes via the existing weakness-text tagging convention.

**Prompt structure after feature 009** (each block omitted gracefully when its source is None / empty):

```
## Original Job Description (verbatim)   ← from feature 008
## Parsed Job Context                     ← NEW (feature 009): job_title, company_name, optional company_info, optional storyboard
## Role Requirements                      ← existing extracted summary
## Content Plan (read-only context …)     ← NEW (feature 009): sections + key_claims, role_positioning summary, known_gaps
## Evaluation Dimensions (evaluate ONLY these)   ← six always-on positioning + coverage dims + any configured standard dims
## Cover Letter                           ← existing letter text
```

**Six always-on dimensions** (was five in feature 008): `role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`, **`critical_requirements_underweighted`** (new). The new dimension fires when a top job responsibility receives thin or absent treatment in the letter; honest gaps acknowledged in `Known gaps acknowledged in the plan` are explicitly excluded by the prompt.

**Graceful-omission semantics**:
- `state.job_context is None` → `## Parsed Job Context` block omitted; raw-text block falls back to the `(job description unavailable …)` placeholder from feature 008.
- `state.job_context` set but all optional structured fields are None → individual field lines omitted; block kept when at least one field is populated.
- `state.content_plan is None` → `## Content Plan` block omitted entirely.
- `state.content_plan.role_positioning is None` → Role Positioning sub-block omitted; Sections sub-block still appears.
- `state.content_plan.evidence_map.known_gaps` empty → Known Gaps sub-block omitted.

**Read-only invariant**: the content plan is reference context only. The reviewer evaluates the LETTER; weaknesses are recorded on letter sections, never on plan fields. The prompt makes this explicit.

**Operator workflow**: edit nothing in your run command — the change is observable only in the hiring-review report quality. On the next `jobagent prompts sync`, feature 007's registry creates one new version of `bewerbungs-agent/hiring_reviewer` (the other nine prompts stay unchanged).

---

## 17. Langfuse Observability (`utils/observability.py`)

Feature 006 adds optional Langfuse tracing on top of the existing MLflow integration. The two backends are fully independent — neither can disable or corrupt the other (FR-014). Observability is **off by default** and silently degrades to a no-op when credentials are missing, so a developer without Langfuse access can still run the agent end-to-end (FR-011).

### What gets traced

One CLI invocation produces **one Langfuse trace** identified by the local run ID, containing one nested span per pipeline stage. The parallel branches `write_letter` and `tailor_cv` appear as sibling spans under the root trace with overlapping wall-clock timestamps — no synthetic parent span is inserted (FR-016a).

Each stage span records:

| Field | Source | Stages |
|---|---|---|
| `stage_name` | wiring in `workflow.py` | all |
| `prompt_name`, `prompt_hash` | `_compute_prompt_hash()` (existing util) | LLM stages |
| `model` | `AnthropicLLMClient.MODEL` | LLM stages |
| `input` (summary or full) | `utils/summaries.py` | all |
| `output` (summary or full) | `utils/summaries.py` | all |
| `usage_details` (input/output/total tokens) | Anthropic response.usage via contextvar | LLM stages |
| `level=ERROR` + `status_message` + trace excerpt | wrapper `except` block | error cases |
| start/end timestamps + duration | SDK | all |

### Enabling

1. Install the SDK: `uv add langfuse` (already in `pyproject.toml` ≥ feature 006).
2. Set credentials in `.env`:
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
   ```
3. Turn it on in your starter template YAML:
   ```yaml
   observability:
     langfuse:
       enabled: true
       log_full_inputs: false   # default — summary mode only
       log_full_outputs: false  # default — summary mode only
       mask_pii: true           # default — PII regex pass in full mode
   ```

If either of `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is missing, observability silently falls back to no-op regardless of the YAML flag (single debug-level log line, no warning).

### Privacy posture: summary mode by default

In default mode, **no profile/CV/job/letter prose** is sent to Langfuse — only counts, lengths, IDs, hashes, and enum labels derived by `utils/summaries.py`. This is the chokepoint that satisfies FR-018.

To send raw payloads, opt in per-direction:
```yaml
observability:
  langfuse:
    log_full_inputs: true     # raw pre-call state slice per stage
    log_full_outputs: true    # raw partial-update dict per stage
```

Even in raw mode, two redaction passes always run before transmission (`utils/redaction.py`):

| Pass | When it runs | What it strips |
|---|---|---|
| Env-var secret pass | always (summary + full) | values of env vars whose names end in `_API_KEY` / `_TOKEN` / `_SECRET` / `_PASSWORD` |
| PII regex pass | full mode + `mask_pii=true` (default) | email, phone, IBAN, postal-address blocks |

Setting `mask_pii: false` only disables the PII regex pass — env-var secret redaction is **unconditional** (FR-017).

### Bounded flush at CLI exit

`cli.run` wraps the entire pipeline in a `try/finally` that calls `observability.flush(timeout_seconds=3.0)` before exiting. The flush is bounded by a thread join: if Langfuse is unreachable, the CLI exits within 3 s anyway, accepting trace loss as the failure mode (FR-020). Trace lifecycle survives `KeyboardInterrupt` and uncaught exceptions.

### MLflow cross-link

When MLflow tracking is also active, `tracker.log_langfuse_link(trace_id, trace_url)` writes two MLflow tags so an operator viewing the MLflow run can pivot to the Langfuse trace:

```
langfuse_trace_id  = a3f9c12d4e7b80910000000000000000
langfuse_trace_url = https://cloud.langfuse.com/trace/a3f9c12d...
```

The link is **one-way only** (FR-021) — nothing is written back to Langfuse from MLflow. This keeps the two backends fully independent.

### CLI output line

After a successful run with observability enabled, the CLI prints:
```
[run] Done. Outputs written to: outputs/4ffbe3df
  langfuse trace: https://cloud.langfuse.com/trace/a3f9c12d...
  letter.md  (2743 chars)
  letter_review  (4 sections reviewed, 1 rewritten)
```

### Non-interference invariants

The observability wrapper never touches generation:

- **FR-013 / SC-004**: outputs are byte-identical between enabled and disabled runs on the same inputs. Enforced by `tests/integration/test_full_run.py::test_full_pipeline_outputs_byte_identical_enabled_vs_disabled` using `filecmp.cmp(..., shallow=False)`. Treat any regression here as a P0.
- **FR-015**: any Langfuse SDK exception (auth error, network failure, malformed payload, hung connection) emits at most one `warnings.warn()` per process and downgrades to no-op for the rest of the run. The pipeline always continues to write its artifacts.
- **Stage isolation**: stage modules import nothing from `utils/observability` except the `_active_span` ContextVar inside `AnthropicLLMClient.call` (used solely to surface token usage). Stages themselves remain observability-unaware.

### Disabling for one run

Three equivalent ways:
- Unset `LANGFUSE_PUBLIC_KEY` for the shell session.
- Set `observability.langfuse.enabled: false` in the template.
- Pass `--override '{"observability":{"langfuse":{"enabled":false}}}'` on the CLI.

All three produce a run with byte-identical output files to one where the integration was never installed.

---

## 18. Prompt Registry (`utils/prompt_registry.py`)

Feature 007 adds Langfuse Prompt Management on top of the existing observability layer: local prompt files stay canonical, but each one is also versioned, labelled, and metadata-tagged in Langfuse so prompt edits leave an auditable trail.

### Single source of truth: `STAGE_PROMPT_MAP`

`utils/prompt_registry.py` owns the `STAGE_PROMPT_MAP` constant — one entry per pipeline stage, mapping to the prompt file stem (or `None` for stages that don't load a prompt, like `load_job` or `validate_outputs`). Both `graph/workflow.py` (for `_wrap_stage(prompt_name=...)` wiring) and the registry (for discovery) read this constant. Adding a new stage prompt is a one-line edit picked up by both sites automatically.

### CLI workflow

```bash
# First sync (creates one version per prompt, applies label "staging")
uv run jobagent prompts sync

# Re-sync (idempotent — no new versions if nothing changed)
uv run jobagent prompts sync

# Promote validated content to production
uv run jobagent prompts sync --label production

# Inspect (works locally even without credentials)
uv run jobagent prompts list           # table
uv run jobagent prompts list --json    # machine-readable
```

**Exit codes** for `sync`:
- `0` — all synced (any mix of created / unchanged / relabeled)
- `1` — credentials missing
- `2` — at least one prompt failed to sync
- `3` — local discovery failed

**Exit codes** for `list`:
- `0` — listing succeeded (with or without credentials)
- `3` — local discovery failed

### Idempotence: content hash in `config`

Every `create_prompt` call writes the local SHA-256 (16-char prefix) into `config["content_hash"]` along with the metadata block (`stage`, `file_path`, `template_format`, `model`, `git_commit`, `git_dirty`). On every sync, the registry reads the latest version's `config["content_hash"]` and compares it to the local hash:

| Remote state | Local hash matches latest | Result |
|---|---|---|
| No prompt yet (404) | n/a | `create_prompt(...)` → `SyncAction.created` |
| Hash matches + requested label already on version | yes | `SyncAction.unchanged` (no SDK write) |
| Hash matches + requested label missing | yes | `update_prompt(new_labels=...)` → `SyncAction.relabeled` |
| Hash differs | no | `create_prompt(...)` → `SyncAction.created` (new version, label moves) |

Per-record failures (network, auth) are isolated: the loop continues, the failed prompt is recorded with `SyncAction.failed` and the upstream error message, and the overall command exits 2 at the end.

### Runtime cross-reference

When observability (feature 006) is enabled and a stage runs an LLM call, the wrapper additionally:

1. Computes `local_hash = _compute_prompt_hash(prompt_name)` (existing util).
2. Calls `runtime_reference("bewerbungs-agent/<name>", local_hash, client=obs.underlying_client())`.
3. Calls `span.set_prompt_reference(reference)`.

The resolved `PromptReference` becomes span metadata: `prompt_name`, `prompt_version` (or `"unsynced"`), `prompt_content_hash`, `prompt_label_at_resolve`. The resolver caches `(name, hash) → PromptReference` in a process-local dict, so per-stage spans incur **zero** additional network round-trips after the first resolution.

When the local content does not match any registered Langfuse version (e.g., an in-progress prompt edit), the span carries `prompt_version="unsynced"` — drift between "what's running" and "what's registered" is impossible to miss from the trace UI.

### Privacy invariant preserved

Adding `prompt_name` + `prompt_version` to spans does NOT loosen feature 006's privacy posture. Span input/output payloads still default to summary mode (counts, hashes, lengths, no prose); only the new four reference fields are added. Operators opting in to `observability.langfuse.log_full_inputs / log_full_outputs` get raw payloads, with the env-var-secret + PII regex passes still applied — exactly as before.

### Disabled / degraded mode

- `prompts sync` without credentials → exit code 1 with `"Langfuse disabled (credentials missing); nothing uploaded"`. CI catches the misconfiguration.
- `prompts list` without credentials → exits 0, every row shows `no-langfuse` placeholder.
- `jobagent run` without credentials → unchanged behaviour: pipeline runs from local files, observability silently no-ops, no registry resolution attempted.

Local prompt files are always the source of truth — the runtime never substitutes a Langfuse-fetched prompt for a local file.

---

## 19. Role-Positioned Prompting (feature 008)

Feature 008 makes the planner's framing decision explicit and forces the writer to use it. The hiring-review stage now sees the original verbatim job description so it can evaluate role-match and opening-alignment directly. The change ships as prompt edits + two small Pydantic additions; the pipeline graph, MLflow logs, Langfuse trace shape, and CLI contract are all unchanged.

### What's new on `ContentPlan`

`RolePositioning` is a nested sub-object the planner emits alongside the existing sections:

| Field | Type | Purpose |
|---|---|---|
| `primary_role_family` | str | Short name of the role the job is hiring for (e.g. "AI/ML platform engineering"). Mirrors the job ad's framing. |
| `primary_selling_point` | str | One-sentence statement of the candidate's main match for that family. |
| `secondary_selling_points` | list[str] | Adjacent-domain matches worth mentioning briefly. |
| `topics_to_emphasise` | list[str] | What the writer should develop in main paragraphs. |
| `topics_to_deemphasise` | list[str] | What the writer should mention only briefly. |
| `opening_angle` | str | Short instruction shaping the writer's first paragraph. |

The field is `RolePositioning | None` on `ContentPlan` so plans serialised before this feature still load. New plans always carry it.

### What's new in config: `WriterRules`

```yaml
writer_rules:
  tool_density_max: 4              # max distinct tool/tech names per paragraph
  banned_phrases:                  # writer is forbidden from producing these
    - expert-level
    - deep expertise
    - world-class
    - guru
    - rockstar
    - 10x
    - ninja
```

Defaults are applied automatically. Operators override per starter template.

### Source-of-truth ordering for the planner

The planner is explicitly instructed to derive positioning **from the job description text first, the extracted requirements second, and the candidate's evidence last**. This is the central rule that prevents the GSK-style failure mode where the candidate's most distinctive past project hijacks the framing of a job in a different domain.

### Writer behaviour

- Opening paragraph references `primary_role_family` and `opening_angle` within the first 400 characters.
- Each paragraph caps distinct tool/technology names at `writer_rules.tool_density_max`.
- The seven default banned self-rating phrases never appear.
- Topics in `topics_to_deemphasise` may appear only as brief secondary mentions — never as section headings or in the opening.
- No claim outside the plan's `key_claims` / `evidence_refs` / `anchor_passages`.

### Hiring-review additions

The review prompt now includes:
- The verbatim original job description (`state.job_context.raw_job_text` — already loaded by `load_job`, no new data flow).
- Five always-on positioning dimensions in addition to whatever the standard `review_config.dimensions` are: `role_match`, `opening_alignment`, `secondary_topic_dominance`, `tool_density`, `overclaiming`.

Weaknesses are tagged with the dimension name (e.g. `"role_match: letter leads with biomedical-ML, but job is AI/ML infrastructure"`) so downstream `targeted_rewrite` can route the fix. Severity ≥ medium on any positioning weakness triggers the existing rewrite path — no new stage was added.

### AI/ML infrastructure regression fixture

`data/examples/jobs/sample_ml_infrastructure.md` describes a Senior Software Engineer role focused on scalable cloud infrastructure, efficient compute, robust Python software, AI/ML workloads, and agentic systems, with biomedical context as a peripheral nice-to-have. `data/examples/profile/projects/biomedical_ml_project.md` adds a notable biomedical-ML project to the profile.

The deterministic regression guard lives in `tests/unit/test_plan_content.py::TestPlannerPositioning::test_positions_infrastructure_first_on_ml_infra_fixture` — given a correctly-positioned canned LLM response, it asserts that `primary_role_family` contains "platform" or "infrastructure" (NOT "biomedical") and that any biomedical reference appears only in `secondary_selling_points`.

### Non-interference invariants

- Pipeline stage order: unchanged.
- Artefact files: unchanged (`artifacts/content_plan.json` now additively contains a `role_positioning` block).
- MLflow tags / metrics / params: unchanged names; per-prompt hashes flip naturally because `planner.md` / `writer.md` / `hiring_reviewer.md` changed.
- Langfuse trace shape: unchanged. The content-plan span summary adds one `role_positioning_present: bool` field; the prose stays out of spans (feature 006 privacy default preserved).
- Langfuse prompt registry (feature 007): the next `jobagent prompts sync` creates one new version of each of the three edited prompts and moves the configured label. Run it after pulling this feature.
- CLI: unchanged commands, flags, exit codes, output files.

### Smoke test (manual)

```bash
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral
jq '.role_positioning' outputs/*/artifacts/content_plan.json
head -20 outputs/*/letter.md
grep -iE "(expert-level|deep expertise|world-class|guru|rockstar|10x|ninja)" outputs/*/letter.md && echo "REGRESSION" || echo "OK"
uv run jobagent prompts sync --label staging
```

`role_positioning.role_family` should contain "platform" or "infrastructure"; the opening paragraph should reference infrastructure framing; the grep should find nothing; the prompts sync should report `3 created, 7 unchanged`.

### Feature 010 — weighted requirements + refined positioning field names

Feature 010 evolves the requirement-extraction and role-positioning structures additively:

**`RequirementItem` (new)** — the richer per-requirement record produced by the extractor:

| Field | Type | Purpose |
|---|---|---|
| `id` | str (≤16 chars) | stable token unique within the response (`R1`, `R2`, …) |
| `text` | str | verbatim or faithful one-sentence text of the requirement |
| `priority` | `Priority` enum | `high` / `medium` / `low` |
| `category` | `RequirementCategory` enum | `core` / `technical` / `collaboration` / `domain` / `optional` |
| `evidence_needed` | `EvidenceNeeded` enum | `required` / `preferred` / `optional` |
| `source_excerpt` | `str \| None` (≤200) | optional verbatim job-text fragment that anchors the requirement |

Added to `RequirementExtraction` as `requirement_items: list[RequirementItem]`. A `model_validator` enforces unique IDs; a second `model_validator` back-fills the legacy `all_requirements` list from `requirement_items` so downstream readers of the old field continue to work.

**`RolePositioning` field renames** — the feature 008 structure is normalised: `primary_role_family → role_family`, `topics_to_emphasise → emphasise`, `topics_to_deemphasise → deemphasise`, plus a new `risky_or_gap_areas: list[str]`. Pydantic `populate_by_name=True` + `Field(..., alias=...)` lets feature-008-shape JSON load unchanged; outputs use the new names. The writer (`stages/write_letter.py`) and hiring review (`stages/hiring_review.py`) update their format strings to use the new attribute names; the writer additionally renders the new `risky_or_gap_areas` block when populated.

**Planner consumption** — `stages/plan_content.build_prompt` renders a new `# Weighted Requirements (priority-ordered)` block ABOVE the legacy summary block whenever `state.requirements.requirement_items` is populated. Each item is rendered as `- [{id}, priority={priority}, evidence={evidence_needed}, category={category}] {text}` with the optional `source: "{source_excerpt}"` continuation line. Items sort by priority (high→medium→low) then by id.

**Hiring review** — the existing content-plan summary block (feature 009) surfaces the renamed positioning fields AND a new `risky_or_gap_areas` line when non-empty. The `critical_requirements_underweighted` dimension instruction is extended so the reviewer does NOT flag topics that are explicitly listed in `risky_or_gap_areas` — those are intentional brief or absent treatments, not regressions.

**Three prompts edited** — `prompts/requirements.md` (new weighted-items section), `prompts/planner.md` (new field names + `requirement_items` consumption rules), `prompts/hiring_reviewer.md` (extended `critical_requirements_underweighted` bullet). The next `jobagent prompts sync` reports `3 created, 7 unchanged`.

**Backward-compat guarantees** (test-enforced):
- Legacy `RequirementExtraction` JSON (no `requirement_items`) loads cleanly; the new field defaults to `[]`.
- Feature-008-shape `RolePositioning` JSON loads via Pydantic aliases; `risky_or_gap_areas` defaults to `[]`.
- Both models reject unknown top-level fields via `extra="forbid"` (typo fields surface clearly rather than silently dropping).

**Test count**: 239 → 254 (+15 new for feature 010).

### Feature 011 — ContentPlan as a hiring story

Feature 011 evolves `ContentPlan` from a list of sections into an explicit hiring story. It adds two new top-level fields and a new sub-model, gated by `extra="forbid"` and three cross-field `@model_validator`s:

- `letter_thesis: str | None` — one-sentence headline (≤ 300 chars) the cover letter argues.
- `paragraphs: list[ParagraphPlan]` — ordered paragraphs the writer must render one-to-one (no extra paragraphs, no collapsing two into one).

Each `ParagraphPlan` carries `purpose`, `main_message` (single ≤ 300 char sentence), optional `requirement_ids` / `evidence_refs` / `emphasise` / `deemphasise`, and HARD per-paragraph caps `max_claims ∈ [1, 8]` and `max_tools ∈ [0, 12]`. `max_tools` OVERRIDES `writer_rules.tool_density_max` for that paragraph specifically — opening paragraphs can pin `max_tools=0` while a credibility paragraph rises to `6`.

**Three model validators enforce invariants**:
- `_validate_evidence_refs_within_max_claims` — `len(p.evidence_refs) ≤ p.max_claims` per paragraph.
- `_validate_opening_paragraph_max_claims` — `paragraphs[0].max_claims ∈ {1, 2}` (opening discipline).
- `_validate_paragraph_evidence_refs_in_evidence_map` — every paragraph `evidence_refs` claim must trace to `evidence_map.items[*].claim`.

A fourth check — `requirement_ids` cross-reference against `state.requirements.requirement_items` — lives at the stage level inside `plan_content()` because the model validators can't reach `RequirementExtraction`.

**Writer changes** — `stages/write_letter.py` gains a `_format_paragraphs_block(plan)` helper inserted between the `# Writer Rules` and `# Writing Mode Instructions` blocks. When `paragraphs` is empty, the helper returns `""` and the prompt structure is byte-identical to feature 010's prompt (zero regression for legacy plans). `prompts/writer.md` gains a new "Paragraph plan consumption" section instructing the writer to render paragraphs one-to-one, honour per-paragraph `max_tools`, and treat `main_message` as the paragraph's topic-sentence intent.

**Planner changes** — `prompts/planner.md` gains a new "Hiring-story structure" section telling the planner to produce `letter_thesis` + ordered `paragraphs`, to size `max_claims` / `max_tools` by paragraph purpose, and to make `paragraphs[0]` reflect `role_positioning.role_family` + `opening_angle`. The reminder line in `plan_content.build_prompt` is extended to mention the new fields.

**Backward-compat guarantees** (test-enforced):
- Legacy `ContentPlan` JSON (no `paragraphs`, no `letter_thesis`) loads cleanly with empty / `None` defaults.
- The three new model validators only fire when `paragraphs` is non-empty — they are no-ops on legacy plans.
- `ContentPlan` now sets `extra="forbid"` (was implicit before); unknown top-level fields surface as `ValidationError`s.

**Two prompts edited** — `prompts/planner.md` + `prompts/writer.md`. The next `jobagent prompts sync` reports `2 created, 8 unchanged`. Hiring-review behaviour and evidence retrieval are explicitly out of scope for this feature.

**Test count**: 254 → 266 (+12 new for feature 011: 5 schema/validator + 1 stage cross-reference + 1 opening regression guard + 2 writer-prompt rendering + 2 backward-compat + 1 main_message-as-single-string).

### Feature 013 — narrative_strategy + story_polish + craft dimensions

Feature 013 lifts cover-letter quality beyond requirement matching with three additions: a NEW `narrative_strategy` stage upstream of planning, a NEW `story_polish` stage between writer and reviewer, and six craft-level dimensions plus a German over-analogy phrase blocklist inside the existing `hiring_review` stage. The `role_positioning` decision is now produced by its OWN dedicated stage (`role_position`) instead of inside `plan_content`, so the new `narrative_strategy` stage can run between role positioning and content planning. The role-positioning logic and schema are unchanged — only the call site moves.

**New pipeline topology** (three new nodes, no nodes removed, no nodes reordered):

```
... build_evidence_map
 → role_position          (NEW, extracted from plan_content)
 → narrative_strategy     (NEW)
 → plan_content           (MODIFIED — consumes role_positioning + narrative_strategy)
 → write_letter           (MODIFIED — consumes narrative_strategy)
 → story_polish           (NEW, configurable, fallback-safe)
 → hiring_review          (MODIFIED — adds craft_dimensions + deterministic_findings + verdict + escalation)
 → targeted_rewrite → validate_outputs → rewrite_if_needed
```

**NarrativeStrategy schema** (9 required fields, bounded for German length, `extra="forbid"`): `candidate_story` (≤ 800), `role_story` (≤ 800), `bridge` (≤ 800, load-bearing for domain transitions), `opening_angle` (≤ 400), `proof_points_to_use` (list ≤ 12, each must trace to `evidence_map.items[*].claim` — stage-level cross-check), `proof_points_to_avoid` (list ≤ 12, same cross-check), `transfer_framing_guidance` (≤ 600), `tone_guidance` (≤ 600; constrained to "restrained AIDA" when mode=aida), `anti_patterns` (list ≤ 20, each entry ≤ 240). The planner consumes the strategy via a `# Narrative Strategy` block in its prompt AND a stage-level filter that drops paragraphs whose `evidence_refs` overlap `proof_points_to_avoid` (a strategy that vetoes every paragraph raises). The writer consumes a parallel block between `# Writer Rules` and `# Paragraph Plan`.

**StoryPolishOutput + deterministic post-check** — the load-bearing factual-integrity contract for US2. `utils/extractors.py` provides three pure extractors (`tool_names_in_text`, `employer_names_in_text`, `numeric_tokens_in_text`) that operate on whole-word case-insensitive matches with punctuation normalisation (so "1000", "1,000", "~1000", "1000+", "1000%" all map to "1000"). `post_check(draft, polished, registry)` returns `passed=True` iff the polished version's extracted sets are subsets of the draft's. When the post-check fails, `story_polish` falls back to the original draft and records `used_fallback=True` with a `fallback_reason`; the hiring reviewer then sees the unpolished draft. Three failure modes (LLM error, post-check failure, stage disabled) all preserve the draft — never invent content. Configurable via `NarrativePolishConfig.story_polish_enabled` (default true).

**Hiring-review extensions** (US3, additive — existing fields preserved):
- `craft_dimensions: CraftDimensions | None` — six dimensions (`story_coherence`, `transition_smoothness`, `over_constructed_language`, `claim_relevance`, `aida_restraint`, `human_readability`), each with severity (`pass`/`warn`/`error`), rationale, and evidence_quote (required when severity ≥ warn).
- `deterministic_findings: list[DeterministicFinding]` — German over-analogy phrase scan (`OVER_ANALOGY_PHRASES_DE` = `"direkt übertragbar"`, `"direkt vergleichbar"`, `"strukturell eng verwandt"`, `"belastbares Analogon"`), case-insensitive substring matches with surrounding context snippets.
- `verdict: Literal["pass", "needs_minor_revision", "needs_major_revision"]` — when LLM returns `pass` but `aida_restraint` or `transition_smoothness` is severity ≥ warn, the stage automatically escalates to `needs_minor_revision`.

**Restrained AIDA mode** — `NarrativePolishConfig.restrained_aida` (default true). When set, `narrative_strategy.tone_guidance` must contain the literal phrase "restrained AIDA"; `prompts/story_polisher.md` removes any over-dramatic AIDA copy; `prompts/styles/aida.md` adds a restrained-tone reinforcement section banning ALL-CAPS opening, exclamation marks in the opening, second-person imperatives, and hyperbolic adjectives ("revolutionary", "world-class", "unparalleled"). The `aida_restraint` craft dimension catches violations the prompts miss.

**Seven prompt files edited or added** — `role_positioner.md` (extracted verbatim from `planner.md`), `narrative_strategist.md` (new), `story_polisher.md` (new), `planner.md` (role-positioning section removed; consumes narrative_strategy), `writer.md` (new "narrative strategy consumption" section), `hiring_reviewer.md` (six craft dimensions + restrained AIDA evaluation), `styles/aida.md` (restrained tone reinforcement). `STAGE_PROMPT_MAP` gains three new stage entries.

**Backward-compat guarantees** (test-enforced):
- Legacy `WorkflowState` snapshots without `narrative_strategy`, `story_polish_output`, or upstream-produced `role_positioning` load cleanly (all fields default to `None`).
- Pre-feature-013 `ContentPlan` JSON with `role_positioning` populated inside the planner output continues to load identically.
- Legacy `HiringReviewOutput` JSON without `craft_dimensions`/`deterministic_findings`/`verdict` loads (those fields default to `None` / `[]` / `"pass"`).

**Cost**: +2 LLM calls per run with both new stages enabled (`narrative_strategy` + `story_polish`); +1 when `story_polish_enabled=false`; +0 vs baseline when both disabled (the extracted `role_position` call replaces the role-positioning sub-task previously bundled into `plan_content`).

**Test count**: 266 → 300 (+34 new for feature 013: 3 NarrativePolishConfig + 3 role_position + 8 narrative_strategy schema/cross-check + 2 planner consumption + 1 writer consumption + 8 extractors/post_check + 5 story_polish schema/fallback/disabled + 4 craft dimensions parse/escalation + 3 deterministic over-analogy scan, minus 3 fold-overs).

---

## 20. Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Required. Anthropic API key. |
| `BEWERBUNGS_PROFILE_DIR` | `data` | Root of profile directory. |
| `BEWERBUNGS_PROMPTS_DIR` | `prompts/` (package-relative) | Override prompt files location. Also honoured by `jobagent prompts sync`/`list` (feature 007). |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse public key. Required when `observability.langfuse.enabled: true` OR when running `jobagent prompts sync`; missing → no-op fallback (runtime) / exit 1 (sync). |
| `LANGFUSE_SECRET_KEY` | — | Langfuse secret key. Same gating as the public key. |
| `LANGFUSE_BASE_URL` (or `LANGFUSE_HOST`) | Langfuse cloud | Self-hosted Langfuse URL. Optional. |

Set in `.env` at repo root (loaded automatically via `python-dotenv`).
