# CLI Contract: Bewerbungs-Agent

**Branch**: `001-bewerbungs-agent-core` | **Date**: 2026-04-01
**Implementation**: `src/bewerbungs_agent/cli.py` (Typer)

The CLI is the sole user-facing interface. It is deterministic and scriptable:
the same inputs and configuration MUST produce structurally equivalent outputs.
All commands exit with code 0 on success and non-zero on any error.

---

## Global Options

```
jobagent [OPTIONS] COMMAND [ARGS]...

Options:
  --profile-dir PATH   Root directory of the user's profile data.
                       Default: ./data
  --version            Show version and exit.
  --help               Show help and exit.
```

---

## `jobagent run`

Execute a full application run: cover letter + tailored CV.

```
jobagent run [OPTIONS]

Required:
  --job PATH            Path to the job description file (Markdown or plain text).
  --template TEXT       Name of the starter template to use
                        (must exist in <profile-dir>/templates/).

Optional:
  --company PATH        Path to company information file.
  --storyboard PATH     Path to storyboard / AIDA input file.
  --override TEXT       JSON string of run-specific overrides applied on top of
                        the starter template. May be repeated.
                        Example: --override '{"language":"EN","mode":"aida"}'
  --cv-variant TEXT     Force selection of a specific CV variant by ID.
  --output-dir PATH     Directory for run outputs. Default: ./outputs/<run-id>/
  --dry-run             Run all structured stages (extraction, planning,
                        evidence mapping) but skip generative stages. Useful
                        for validating inputs without LLM calls.
  --help                Show help and exit.

Exit codes:
  0   Success — all outputs produced and validation passed.
  1   Validation failed after max rewrite attempts.
  2   A required approved source file is missing.
  3   Configuration error (unknown template, invalid override schema).
  4   LLM API error.

Output (on success):
  <output-dir>/
  ├── artifacts/
  │   ├── requirements.json
  │   ├── evidence_map.json
  │   ├── content_plan.json
  │   ├── cv_tailoring_plan.json
  │   ├── validation_letter.json
  │   └── validation_cv.json
  ├── letter.md
  └── cv_tailored.md

Stdout:
  Progress lines prefixed with stage name, e.g.:
    [load_template]        ✓ default_de_neutral
    [extract_requirements] ✓ 6 requirements extracted
    [build_evidence]       ✓ 12 claims mapped, 1 known gap
    [write_letter]         ✓ 2487 chars
    [validate_letter]      ✓ all rules pass
    [tailor_cv]            ✓ cv_ml_engineer → tailored
    [validate_cv]          ✓ all rules pass
    Run complete → outputs/2026-04-01-abc123/
```

---

## `jobagent validate`

Validate an existing draft against its source job description.

```
jobagent validate [OPTIONS]

Required:
  --draft PATH    Path to the draft cover letter (Markdown).
  --job PATH      Path to the original job description file.

Optional:
  --template TEXT Starter template to use for rule thresholds.
                  Default: default_de_neutral
  --help          Show help and exit.

Exit codes:
  0   All validation rules pass.
  1   One or more validation rules fail (details in stdout).
  2   Draft or job file not found.

Output (stdout):
  Validation results per rule (pass / fail / warning), with offending
  excerpts on failure.
```

---

## `jobagent list-templates`

List available starter templates.

```
jobagent list-templates [OPTIONS]

Optional:
  --json      Output as JSON array instead of human-readable table.
  --help      Show help and exit.

Output (human-readable):
  ID                      Language  Mode      Length   Tone
  default_de_neutral      DE        standard  normal   neutral-professionell
  engineer_direct         DE        standard  normal   direkt
  formal_enterprise       EN        standard  long     formal
  aida_light              DE        aida      normal   neutral-professionell
```

---

## `jobagent eval`

Run the evaluation suite against a fixture dataset.

```
jobagent eval [OPTIONS]

Required:
  --dataset PATH  Path to the eval dataset YAML (job/expected-output pairs).

Optional:
  --output PATH   Directory for eval results. Default: ./eval-results/
  --help          Show help and exit.

Exit codes:
  0   All eval cases pass.
  1   One or more eval cases fail.
  2   Dataset file not found or malformed.
```

---

## `jobagent ingest-letters` *(optional, post-MVP)*

Load previous cover letters into the profile for tone reference.

```
jobagent ingest-letters [OPTIONS] DIRECTORY

Arguments:
  DIRECTORY   Directory containing previous letter files.

Optional:
  --help      Show help and exit.
```
