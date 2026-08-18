# Requirements Extraction Instructions

Your task: read the job description and extract the structured requirements
that will drive the rest of the application pipeline.

## Extraction Rules

1. **core_requirement** — one sentence capturing the primary purpose of the
   role (e.g. "Lead backend development of a distributed data platform").
   Be specific to this posting; do not write a generic job title.

2. **technical_requirements** — list of concrete technical skills or
   technologies explicitly mentioned in the job description. Maximum 8 items.
   Use the exact terminology from the posting (e.g. "Kubernetes", not
   "container orchestration").

3. **domain_requirement** — the business domain or industry context if stated
   (e.g. "fintech / payment processing"). Omit if not mentioned.

4. **collaboration_requirement** — teamwork, communication, or cross-functional
   expectations if explicitly stated. Omit if absent.

5. **must_include** — phrases, keywords, or topics the applicant must address
   (e.g. mandatory certifications, explicit must-have requirements from the
   posting). Empty list if none.

6. **must_avoid** — topics to omit (sourced from the run configuration, not
   inferred from the job description). Pass through unchanged from config.

## Weighted requirement items (feature 010)

In addition to the legacy summary fields above, produce a `requirement_items`
array containing every distinct requirement you extract from the job
description. For each item provide:

- **id** — a short stable token unique within this response (`R1`, `R2`, ...).
  The downstream planner and reviewer reference items by this id.
- **text** — the verbatim text (or a faithful one-sentence paraphrase) of the
  requirement.
- **priority** — one of `high`, `medium`, `low`:
  - `high` — top one or two responsibilities the job ad emphasises (listed
    first, repeated, or called "core" / "primary" / "must-have").
  - `medium` — solid mid-tier expectations explicitly listed.
  - `low` — nice-to-haves or context-only mentions ("familiarity with X is a
    plus", "experience with Y a bonus").
- **category** — one of `core`, `technical`, `collaboration`, `domain`,
  `optional`. Matches the categorical fields above.
- **evidence_needed** — one of `required`, `preferred`, `optional`:
  - `required` — a hiring manager would expect explicit evidence in the cover
    letter (skill mention, project anchor, measurable result).
  - `preferred` — strong evidence helps but isn't strictly necessary.
  - `optional` — a brief mention or acknowledgement suffices.
- **source_excerpt** (optional, ≤200 chars) — verbatim fragment of the job
  text that anchors this requirement, when one clean fragment is available.
  When the requirement is synthesised from multiple sentences or implicit
  from context, OMIT this field entirely. Never fabricate a quote.

Both shapes must be produced: the legacy summary fields (`core_requirement`,
`technical_requirements`, etc.) AND `requirement_items`. Existing downstream
consumers continue to read the legacy fields while the planner gradually
adopts the weighted items.

## Important Constraints

- Extract only what is written in the job description. Do not infer unstated
  requirements from job title or industry norms.
- Do not create requirements that have no basis in the text.
- Prefer specificity: "React 18 + TypeScript" is better than "frontend skills".
- Within `requirement_items`, every `id` MUST be unique. Choose short tokens
  the planner can reference (`R1`, `R2`, …).
- Set at least one `requirement_items` entry to `priority="high"` whenever the
  job ad clearly emphasises one or two top responsibilities — don't flatten
  every requirement to `medium`.
