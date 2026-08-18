# bewerbungs-agent

A CLI tool that generates **factually-grounded** cover letters and tailored CVs for
job applications. Given a job description and your personal profile, it runs a
multi-stage LLM pipeline (LangGraph + Anthropic Claude) that extracts the role's
requirements, maps them to evidence from your approved source documents, plans the
letter, writes it, reviews it as a hiring manager would, and validates the result.

The central design invariant: **the model that writes the letter never sees your raw
profile.** It only receives a structured content plan derived from an evidence map,
so every claim in the letter traces back to an approved source — nothing is invented.

## How it works

```
load_job → extract_requirements → load_profile → select_cv_variant
→ build_evidence_map → role_position → narrative_strategy → plan_content
→ [write_letter ∥ tailor_cv] → story_polish → hiring_review
→ targeted_rewrite → validate_outputs → rewrite_if_needed
```

Each stage is a typed node in a LangGraph `StateGraph`; structured extraction always
runs before any prose generation. See [`ENGINEERING.md`](ENGINEERING.md) for the full
architecture, data models, and extension points.

## Requirements

- Python 3.11
- An Anthropic API key
- (Optional) [`uv`](https://github.com/astral-sh/uv) for dependency management

## Setup

```bash
# install (using uv)
uv sync

# or with pip
pip install -e ".[dev]"

# configure your API key
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY
```

## Usage

```bash
# generate a letter + tailored CV from the bundled example profile
jobagent run \
  --job data/examples/jobs/sample_software_engineer.md \
  --template default_de_neutral \
  --profile-dir data/examples

# dry run (validate inputs and evidence, no LLM generation)
jobagent run --job data/examples/jobs/sample_software_engineer.md \
  --template default_de_neutral --profile-dir data/examples --dry-run

# validate an existing draft
jobagent validate --draft outputs/<run_id>/letter.md \
  --job data/examples/jobs/sample_software_engineer.md

# list available templates
jobagent list-templates
```

Outputs are written to `outputs/<run_id>/` — the final `letter.md` and `cv_tailored.md`
plus an `artifacts/` folder with the requirements, evidence map, and content plan for
debugging.

### Your own profile

The repo ships a **synthetic** example profile under `data/examples/`. To use your own,
point `--profile-dir` at a directory laid out the same way (`profile/`, `cvs/`,
`templates/`, optional `letters/`). Anything under `data/` other than `data/examples/`
is gitignored, so your real profile never gets committed. See the profile-directory
section of [`ENGINEERING.md`](ENGINEERING.md) for the expected layout.

## Prompts

All prompts live as plain Markdown under [`prompts/`](prompts/) and are loaded at
runtime — you can iterate on letter quality without touching code. Override the
directory with `BEWERBUNGS_PROMPTS_DIR`.

## Observability (optional)

Both are off by default and degrade to a no-op when unconfigured:

- **MLflow** — local run tracking (`mlruns/`), per-stage prompt hashes and thinking config.
- **Langfuse** — one trace per run, one span per stage, summary-mode-by-default privacy,
  plus a prompt registry that versions the local prompt files.

## Development

```bash
pytest tests/unit/          # pure-function unit tests (no LLM calls)
pytest tests/integration/   # full graph run against a mock LLM
ruff check src/ tests/
mypy src/
```

## License

[MIT](LICENSE) © 2026 Angelo Duo
