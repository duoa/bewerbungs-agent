# Quickstart: Langfuse Observability

**Feature**: 006-langfuse-observability
**Audience**: operators who want to enable tracing on their job-application runs.

---

## 1. Install the optional dependency

```bash
uv add langfuse
# or
pip install 'langfuse>=2.0'
```

If you skip this step, the agent runs normally with observability disabled — no error, no warning beyond a single debug line.

---

## 2. Set credentials

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx
export LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx
export LANGFUSE_BASE_URL=https://cloud.langfuse.com    # or your self-hosted URL
```

Credentials are read once at CLI startup. If either of `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is missing, observability silently degrades to no-op for that run.

---

## 3. Enable in your starter template

Add an `observability` block to your YAML (e.g., `data/examples/templates/default_de_neutral.yaml`):

```yaml
observability:
  langfuse:
    enabled: true            # master switch; default false
    log_full_inputs: false   # default false → summaries only
    log_full_outputs: false  # default false → summaries only
    mask_pii: true           # default true; affects only full-payload mode
```

All four flags are optional and default to safe values; the snippet above is what you'd write to keep defaults explicit.

---

## 4. Run the agent

```bash
uv run jobagent run \
  --job data/examples/jobs/sample_software_engineer.md \
  --template default_de_neutral
```

The output directory and exit code are identical to a no-Langfuse run. The console additionally prints one line at the end:

```
  langfuse trace: https://cloud.langfuse.com/trace/4ffbe3df...
```

(only when observability successfully started).

---

## 5. View the trace

Open the printed URL or browse to your Langfuse project. You will see:

```
Trace: 4ffbe3df-...   tags: template_id=default_de_neutral, cv_variant=cv_software
├── extract_requirements        (1.2s, success)  prompt=requirements  hash=a3f9c12d4e7b8091
├── load_profile                (0.1s, success)
├── select_cv_variant           (0.8s, success)  prompt=cv_selector   hash=...
├── build_evidence_map          (4.2s, success)  prompt=evidence      hash=...   tokens=in:3200 out:1100
├── plan_content                (3.1s, success)  prompt=planner       hash=...
├── write_letter                (5.5s, success)  prompt=writer        hash=...   tokens=in:2100 out:850
├── tailor_cv                   (5.3s, success)  prompt=tailor_cv     hash=...   tokens=in:1800 out:1200
├── hiring_review               (2.9s, success)  prompt=hiring_reviewer
├── targeted_rewrite            (3.4s, success)  prompt=targeted_rewriter
├── validate_outputs            (0.05s, success)
└── (rewrite_if_needed)         — not present when validation passed first try
```

Each span carries `stage_name`, `prompt_name`, `prompt_hash`, `model`, `input_summary` (or full input if enabled), `output_summary`, `latency_ms`, `status`, `artifact_paths`, and `token_usage` where applicable.

---

## 6. What gets sent in summary vs. full mode

### Summary mode (default)

```json
{
  "input_summary": {
    "requirements": {"core_present": true, "technical_count": 2},
    "evidence_map": {"items_count": 8, "known_gaps_count": 1}
  },
  "output_summary": {
    "content_plan": {"sections_count": 4, "selected_soft_skills_count": 2}
  }
}
```

No CV body, no profile JSON, no job description, no evidence passage text, no generated prose. Just counts, hashes, IDs, enum labels.

### Full mode (opt-in via `log_full_inputs: true` / `log_full_outputs: true`)

```json
{
  "input": {
    "requirements": { "...full RequirementExtraction dict..." }
  },
  "output": {
    "content_plan": { "...full ContentPlan dict, prose included..." }
  }
}
```

Even in full mode:
- Any environment variable whose name ends in `_API_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD` has its value replaced with `<REDACTED:NAME>`.
- With `mask_pii: true` (default), email addresses, phone numbers, IBANs, and postal-address blocks are replaced with `<EMAIL>`, `<PHONE>`, `<IBAN>`, `<POSTAL>`.
- Set `mask_pii: false` to opt out of the regex pass — env-var-value redaction still runs.

---

## 7. Cross-link with MLflow

If you already use MLflow tracking, no extra config is needed. When both backends are active, each MLflow run automatically gets two tags:

```
langfuse_trace_id  = 4ffbe3df-xxxx-xxxx-...
langfuse_trace_url = https://cloud.langfuse.com/trace/4ffbe3df-...
```

This is one-way — no MLflow URLs are written into Langfuse. (Rationale: keep the backends fully independent so a Langfuse outage cannot affect MLflow recording, and vice versa.)

---

## 8. Disable for a single run

Three equally valid ways:

1. Unset `LANGFUSE_PUBLIC_KEY` for that shell session.
2. Set the YAML flag `observability.langfuse.enabled: false`.
3. Pass `--override '{"observability":{"langfuse":{"enabled":false}}}'` on the CLI.

All three produce a run with byte-identical output files to one where the Langfuse integration was never installed.

---

## 9. Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| No trace appears in Langfuse | Credentials missing or wrong host | Check `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, verify `LANGFUSE_BASE_URL` is reachable. The CLI prints a debug line at startup if it fell back to no-op. |
| CLI takes ~3 s extra at end of run | Langfuse host is slow or unreachable; flush is hitting the 3 s bound | Expected behaviour (FR-020 bound). Fix connectivity or set `observability.langfuse.enabled: false`. |
| Trace appears but spans are empty | Mocked LLM client during test runs | Expected — token usage and prompt hash only populate when real stages run. |
| "Pipeline aborted: langfuse error" | THIS WOULD BE A BUG | File an issue with the warning text. Per FR-015, no Langfuse failure may ever abort the pipeline. |

---

## 10. Smoke test (manual)

```bash
# 1. With observability disabled (baseline)
unset LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
uv run jobagent run --job data/examples/jobs/sample_software_engineer.md \
                    --template default_de_neutral \
                    --output-dir /tmp/run_a

# 2. With observability enabled
export LANGFUSE_PUBLIC_KEY=pk-lf-test
export LANGFUSE_SECRET_KEY=sk-lf-test
export LANGFUSE_BASE_URL=https://cloud.langfuse.com
uv run jobagent run --job data/examples/jobs/sample_software_engineer.md \
                    --template default_de_neutral \
                    --output-dir /tmp/run_b \
                    --override '{"observability":{"langfuse":{"enabled":true}}}'

# 3. Verify byte-identical outputs (run_id-independent files)
diff /tmp/run_a/*/letter.md /tmp/run_b/*/letter.md && echo "letter OK"
for f in artifacts/requirements.json artifacts/evidence_map.json \
         artifacts/content_plan.json artifacts/cv_tailoring_plan.json \
         artifacts/validation_letter.json artifacts/validation_cv.json; do
  diff /tmp/run_a/*/$f /tmp/run_b/*/$f && echo "$f OK"
done
```

All file comparisons MUST report no differences. If any differ, FR-013 has regressed.
