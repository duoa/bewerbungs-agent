# Quickstart: Bewerbungs-Agent

**Branch**: `001-bewerbungs-agent-core` | **Date**: 2026-04-01

---

## Prerequisites

- [uv](https://github.com/astral-sh/uv) — install once with
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- An Anthropic API key (`ANTHROPIC_API_KEY`)

Python 3.11 is installed automatically by uv; no separate Python installation
is required.

---

## 1. Install

```bash
# Clone the repo
git clone <repo-url> bewerbungs-agent
cd bewerbungs-agent

# Create a Python 3.11 virtual environment
uv venv --python 3.11

# Activate it
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

# Install pinned dependencies + the project
uv pip sync requirements-dev.txt
uv pip install -e .

# Verify
python --version               # Python 3.11.x
jobagent --version
```

---

## 2. Set API Key

Copy `.env.example` to `.env` and fill in your key:

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
BEWERBUNGS_PROFILE_DIR=./data   # optional, defaults to ./data
```

The `.env` file is gitignored. It is loaded automatically when `jobagent`
starts; no `export` command is needed.

---

## 3. Set Up Profile Directory

The agent reads your personal data from a profile directory (default: `./data`).
Create the structure and populate it with your actual documents:

```
data/
├── profile/
│   ├── master_profile.json     # required — all career facts
│   ├── personal_skills.md      # required — soft skills with evidence
│   └── projects/               # optional — project detail docs (*.md)
├── cvs/
│   ├── cv_ml_engineer.pdf      # at least one CV variant required
│   └── metadata/
│       └── cv_ml_engineer.json # required alongside each CV file
├── templates/
│   └── default_de_neutral.yaml # at least one starter template required
├── letters/                    # optional — previous cover letters
├── jobs/                       # suggested location for job description files
└── companies/                  # optional — company information files
```

See `data/examples/` for sample files showing the expected format of each
document type.

---

## 4. Verify Templates

```bash
jobagent list-templates
```

Expected output:
```
ID                      Language  Mode      Length   Tone
default_de_neutral      DE        standard  normal   neutral-professionell
```

---

## 5. Prepare a Run

Create a job description file:

```bash
mkdir -p data/jobs
cat > data/jobs/senior-engineer-acme.md << 'EOF'
# Senior Software Engineer – Acme Corp

We are looking for a senior Python engineer with experience in ML systems,
data pipelines, and cloud infrastructure. Strong communication skills required.
...
EOF
```

Optionally create a company info file:

```bash
cat > data/companies/acme.md << 'EOF'
# Acme Corp

Acme Corp builds real-time data infrastructure for e-commerce platforms.
Founded 2015, Series C, ~200 engineers, Berlin + remote.
EOF
```

---

## 6. Run the Agent

```bash
jobagent run \
  --job data/jobs/senior-engineer-acme.md \
  --template default_de_neutral \
  --company data/companies/acme.md
```

Progress output:
```
[load_template]        ✓ default_de_neutral
[load_job]             ✓ senior-engineer-acme.md + acme.md
[extract_requirements] ✓ 6 requirements extracted
[load_profile]         ✓ master_profile + 3 CV variants + 12 projects
[select_cv_variant]    ✓ cv_ml_engineer (role family: ml, data-engineering)
[build_evidence_map]   ✓ 14 claims mapped, 0 known gaps
[plan_content]         ✓ 5 sections, 2 soft skills
[write_letter]         ✓ 2541 chars
[validate_letter]      ✓ all rules pass
[tailor_cv]            ✓ cv_ml_engineer → tailored (4 changes)
[validate_cv]          ✓ all rules pass
Run complete → outputs/2026-04-01-a1b2c3/
```

---

## 7. Inspect Outputs

```
outputs/2026-04-01-a1b2c3/
├── letter.md           ← cover letter (Markdown)
├── cv_tailored.md      ← tailored CV (Markdown)
└── artifacts/
    ├── requirements.json
    ├── evidence_map.json       ← every claim linked to a source
    ├── content_plan.json
    ├── cv_tailoring_plan.json
    ├── validation_letter.json
    └── validation_cv.json
```

---

## 8. Common Overrides

Run with English output and AIDA mode:

```bash
jobagent run \
  --job data/jobs/senior-engineer-acme.md \
  --template default_de_neutral \
  --override '{"language":"EN","mode":"aida"}'
```

Force a specific CV variant:

```bash
jobagent run \
  --job data/jobs/senior-engineer-acme.md \
  --template engineer_direct \
  --cv-variant cv_data_science
```

Dry run (no LLM generation, validates inputs and evidence only):

```bash
jobagent run \
  --job data/jobs/senior-engineer-acme.md \
  --template default_de_neutral \
  --dry-run
```

Or a real run against a profile directory:

```bash
.venv/bin/jobagent run \
  --job data/examples/jobs/machine_learning_engineer.md \
  --template default_eng_neutral \
  --profile-dir data/examples
```
 
---

## 9. Validate an Existing Draft

```bash
jobagent validate \
  --draft outputs/2026-04-01-a1b2c3/letter.md \
  --job data/jobs/senior-engineer-acme.md
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Missing required source: master_profile.json` | File not in profile dir | Create `data/profile/master_profile.json` |
| `Unknown template: engineer_x` | Template file missing | Add YAML to `data/templates/` |
| `EvidenceItem source outside approved directories` | Bug or misconfigured data dir | Check `--profile-dir` argument |
| `Validation failed after 2 rewrites` | Persistent violation | Inspect `artifacts/validation_letter.json` |
