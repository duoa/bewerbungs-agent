# Quickstart: Hiring Review with Full Job Context

**Feature**: 009-review-full-job-context
**Audience**: operators and contributors who want to understand what changes after this feature merges.

---

## 1. What changes for operators?

Nothing in your daily workflow:
- Same CLI: `jobagent run --job ... --template ...`.
- Same exit codes, same output files.
- Same MLflow tags, same Langfuse trace shape.

What's different is what the **hiring-review report** in `outputs/<run_id>/artifacts/letter_review.md` (or the equivalent Langfuse trace span) contains:

- More grounded `role_match` and `opening_alignment` judgements, because the reviewer now sees the verbatim job ad plus the parsed structured `job_context` fields (job title, company, optional company-info and storyboard texts).
- Sharper `priority_fix` text on opening-alignment weaknesses, because the reviewer can now see what the planner's `role_positioning.opening_angle` intended.
- A new always-on dimension `critical_requirements_underweighted` — fires when a top job responsibility receives only thin or no treatment in the letter. Routes to `targeted_rewrite` like every other positioning dimension at severity ≥ medium.

---

## 2. Confirming the new context lands in the prompt

The deterministic check is in the unit test suite:

```bash
.venv/bin/pytest tests/unit/test_hiring_review.py -v
```

For a live check against Langfuse (requires the credentials set up by features 006/007):

```bash
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral
# → opens the printed langfuse trace URL
# → in the hiring_review span, the "input" metadata shows the constructed prompt
# → confirm "## Parsed Job Context" and "## Content Plan (read-only context...)" blocks are present
```

---

## 3. Pushing the prompt edit to Langfuse Prompt Registry (feature 007)

After merging this feature:

```bash
uv run jobagent prompts sync
# → expected output: "Summary: 1 created, 9 unchanged, 0 relabeled, 0 failed."
# → the created prompt is bewerbungs-agent/hiring_reviewer (now at version N+1)
```

If the summary reports more or fewer than `1 created`, something else inadvertently changed — investigate before promoting.

To promote the new version to `production` after a smoke run:

```bash
uv run jobagent prompts sync --label production
# → "RELABELED bewerbungs-agent/hiring_reviewer ..."
```

---

## 4. The new `critical_requirements_underweighted` dimension in practice

A real-world example: the AI/ML infrastructure fixture (`data/examples/jobs/sample_ml_infrastructure.md`) lists "Co-own incidents end-to-end: oncall rotation, postmortems, structural fixes that prevent recurrence, SLO-driven decision making" as a top responsibility. If the writer produces a letter that opens with infrastructure framing (good — feature 008 working) but spends three paragraphs on Python libraries and never mentions oncall, on-call rotation, postmortems, or SLOs, the reviewer should now flag:

```
section: experience
weakness:
  text: "critical_requirements_underweighted: the job emphasises end-to-end
        incident ownership (oncall rotation, postmortems, SLO-driven decisions);
        the letter does not mention any of these responsibilities."
  severity: high
  priority_fix: "add a paragraph or sentence on incident ownership /
                postmortems / SLOs, anchored to a concrete project from
                the plan."
```

With the configured `rewrite_threshold: medium`, that weakness routes "experience" into `sections_to_rewrite` and the existing `targeted_rewrite` stage rewrites just that section.

---

## 5. Graceful-omission behaviour (legacy paths)

Three legacy paths continue to work:

| Path | Behaviour |
|---|---|
| `jobagent validate --draft letter.md --job job.md --template ...` | `state.job_context` is populated (the validate command loads the job), but `state.content_plan` is None. The "Content Plan" block is omitted; everything else works. |
| Unit-test path with a minimal `WorkflowState(config=..., letter_draft=...)` (no `job_context`, no `content_plan`) | Both new blocks are omitted; the "(job description unavailable …)" placeholder appears for the raw text block. Reviewer evaluates against requirements alone. |
| Re-review of a `letter_review.md` from a pre-feature-008 run | Same as above when invoked via a state without `job_context` / `content_plan`. |

These paths are explicitly covered by the test suite (FR-021, FR-022).

---

## 6. Smoke test (manual)

```bash
# 1. Run the agent against the AI/ML infrastructure fixture.
uv run jobagent run \
  --job data/examples/jobs/sample_ml_infrastructure.md \
  --template default_de_neutral

# 2. Inspect the hiring-review output.
cat outputs/*/artifacts/letter_review.md 2>/dev/null || \
  echo "(letter_review.md not yet written by your stage; check trace UI)"

# 3. Look for the new dimension in any weakness text.
grep -E "critical_requirements_underweighted" outputs/*/artifacts/*.json && \
  echo "new dimension fired" || \
  echo "no critical-requirement weakness found"

# 4. Push the prompt update to Langfuse.
uv run jobagent prompts sync
# → expected: 1 created (hiring_reviewer), 9 unchanged
```

If step 4 reports anything other than `1 created, 9 unchanged`, an unintended prompt was modified — `git diff prompts/` will show what.
