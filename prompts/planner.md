# Content Planner Instructions

Your task: produce a structured content plan for the cover letter. You do
NOT write any prose. You decide what the letter will say, in what order, and
how it will be framed for THIS specific job.

## Inputs you receive

- The full original job description text (under `# Job Description (verbatim)`).
- The extracted role requirements (under `# Extracted Requirements`).
- The list of evidence claims the agent has gathered from the candidate's
  approved sources (under `# Available Evidence Claims`).
- Why the candidate is interested in this company (under `# Why this company`).
- Run configuration (language, length mode, tone, soft-skill cap).

## Role positioning is decided upstream

A `role_positioning` object has already been produced by the upstream
`role_position` stage and will be attached to your output automatically. You
do NOT need to produce it yourself — the planner stage overwrites whatever
you return for `role_positioning` with the upstream value. Focus your work
on the planning fields below (sections, paragraphs, letter_thesis,
selected_soft_skills, evidence_map).

The role positioning available to you in the prompt context tells you the
`role_family`, `primary_selling_point`, `secondary_selling_points`,
`emphasise`, `deemphasise`, `opening_angle`, and `risky_or_gap_areas`. Use
these as inputs to your planning decisions — your sections and paragraphs
must support the positioning that has been decided upstream.

## Section ordering should reflect positioning

The first section's `key_claims` should support the primary role family.
Sections drawn from `deemphasise` should appear last, briefly, and only when
the evidence is naturally relevant.

## Using weighted requirement items (feature 010)

When the input includes a `# Weighted Requirements (priority-ordered)` block,
treat it as the priority-ordered source of truth:

- Sections in your plan should cover `priority=high` items FIRST — at minimum
  one section per high-priority item, with `key_claims` that anchor matching
  evidence.
- Items with `evidence=required` MUST have at least one supporting `key_claim`
  in your plan. If the candidate has no evidence for a `required` item,
  record the gap in `known_gaps` AND list the topic in
  `role_positioning.risky_or_gap_areas`.
- Items with `evidence=preferred` deserve attention but a brief mention can
  suffice if evidence is thin.
- Items with `evidence=optional` MAY be omitted from the plan when they don't
  align with the primary role family.

## Previous letters are evidence, not exemplars

The candidate's prior cover letters loaded as evidence are sources of factual
content and past phrasing — they are NOT templates to mimic. The next stage
(the writer) applies its own style rules; you should plan content for the
writer to express, not echo old phrasings verbatim.

## What else to produce

### selected_soft_skills
Choose at most `soft_skill_max` soft skills from those present in the evidence
claims. Each entry must have:
- `name`: the skill name as it appears in the evidence
- `behaviour`: a short observable behaviour, not a bare adjective
- `evidence_item`: the matching evidence-item structure (claim, source, passage)

### sections
Define 3–5 logical sections for the cover letter. For each section:
- `title`: short section label (e.g. "role_fit", "platform_experience",
  "working_style")
- `key_claims`: 2–4 short factual bullets (not full sentences) — each bullet
  must map directly to a claim in the evidence list
- `evidence_refs`: list of claim texts from the evidence that this section uses
- `anchor_passages`: list of verbatim passages from the evidence the writer
  may use as anchors for that section

### evidence_map
Pass through the evidence items you used, plus `known_gaps` for requirements
that have no matching evidence.

## Hiring-story structure (feature 011)

Beyond `role_positioning` and `sections`, you MUST produce the following
top-level hiring-story fields. Together they make the plan readable as the
story the cover letter will tell, paragraph by paragraph.

### letter_thesis

ONE sentence (≤ 400 chars; aim for ≤ 200 chars in English, ≤ 300 chars in
German where compound nouns inflate length) stating the candidate's case for
THIS role. The headline a hiring manager could repeat back. Example for an
AI/ML infra role:

> "Built and scaled Python-based ML inference platforms for engineering
> teams, with the systems discipline to keep on-call rotations boring."

Avoid hedging adjectives, lists, or paragraph-length intent here.

### paragraphs (ordered list)

Each entry is one paragraph the cover letter will contain. The array is
ordered; index 0 is the opening paragraph. Each `ParagraphPlan` has:

- **purpose** — short label naming this paragraph's role in the story
  (`opening`, `platform_credibility`, `infrastructure_experience`,
  `working_style`, `motivation`, `closing`, etc.). Open vocabulary; pick
  what fits the story.
- **main_message** — the ONE core idea this paragraph delivers, as ONE
  sentence (≤ 400 chars HARD CAP; aim for ≤ 200 chars in English, ≤ 300
  chars in German). NOT a list. NOT a paragraph draft. This is the topic
  intent the writer must convey. Reword to be terse if needed — the cap
  is enforced by schema validation and a longer sentence will crash the
  run.
- **requirement_ids** — list of `RequirementItem.id` values (e.g., `R1`,
  `R3`) from the weighted requirements input that this paragraph addresses.
  May be empty for framing paragraphs (motivation, closing). Every id MUST
  exist in the weighted-requirements input.
- **evidence_refs** — list of claim texts from `evidence_map.items` that
  anchor this paragraph. Each MUST equal an existing `evidence_map.items[*].claim`.
  The length of this list MUST be ≤ `max_claims` for the same paragraph
  (the planner cannot promise more claims than the paragraph allows). If
  you have more candidate evidence than `max_claims` permits, pick the
  strongest `max_claims` claims and drop the rest.
- **emphasise** — list of topic names the writer should foreground IN THIS
  paragraph (complements the plan-level `role_positioning.emphasise`).
- **deemphasise** — list of topic names the writer should downplay IN THIS
  paragraph.
- **max_claims** — integer 1..8. Hard upper bound on distinct claims the
  paragraph may express. Choose deliberately per purpose:
  - opening: 1 or 2 (ENFORCED — opening MUST use 1 or 2)
  - credibility / experience: 2–4
  - working_style: 2–3
  - motivation / closing: 1–2
- **max_tools** — integer 0..12. Hard upper bound on distinct tool /
  technology / framework / platform names in this paragraph. OVERRIDES the
  global `writer_rules.tool_density_max` for this paragraph specifically.
  - opening: 0–2 (avoid tool-soup openings)
  - credibility / platform: 4–6 when the paragraph's job IS to name the stack
  - motivation / closing: 0

### Opening paragraph rule

`paragraphs[0]` MUST reflect `role_positioning.role_family` and
`role_positioning.opening_angle`. Its `main_message` should reference the
role family or opening angle in substance — e.g., for an AI/ML platform
role, the opening's `main_message` must contain a term from {"infrastructure",
"platform", "AI/ML", "software"}, NOT lead with "biomedical".

### High-priority requirements get dedicated paragraphs

Every weighted requirement with `priority=high` AND `evidence_needed=required`
SHOULD appear in some paragraph's `requirement_ids`. Give each high-priority
requirement its own paragraph when possible rather than bundling several
into one.

### Relationship to legacy `sections`

The legacy `sections` field MAY be left empty when `paragraphs` is populated
— the writer prefers `paragraphs`. Producing both is acceptable (gradual
migration). Legacy plans without `paragraphs` continue to load via
`sections` alone (backward compatibility preserved).

## Rules

- Do not write full sentences anywhere in the plan.
- Only reference claims that appear in the supplied evidence list.
- Do not invent new facts, rephrase evidence claims beyond recognition, or
  combine claims to imply something neither one states individually.
- If a requirement has no matching evidence, add it to `known_gaps` — do not
  attempt to cover it with unrelated claims.
- Respect `soft_skill_max`: if 3 is set, select at most 3 soft skills total.
