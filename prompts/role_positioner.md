# Role Positioning Instructions

Your task: decide how this cover letter should be framed for THIS specific
job. You do NOT write any prose, paragraphs, or section plan — that happens
in later stages. Your single output is a `role_positioning` object with
seven fields that the downstream narrative-strategy and content-planning
stages will consume.

## Inputs you receive

- The full original job description text (under `# Job Description (verbatim)`).
- The priority-ordered weighted requirements (under `# Weighted Requirements`).
- The extracted role requirements summary (under `# Extracted Requirements`).
- The list of evidence claims the agent has gathered from the candidate's
  approved sources (under `# Available Evidence Claims`).
- Run configuration (language, tone, soft-skill cap).

## Source-of-truth ordering for the positioning decision

When deciding how to frame the letter, derive your decision in this order:

1. **First: the job description text.** What role is this company actually
   hiring for? What are the top one or two responsibilities the ad emphasises?
2. **Second: the extracted requirements.** Use them as a structured summary of
   #1, not as a substitute for reading the original text.
3. **Third (and only third): the candidate's evidence.** Evidence informs HOW
   the positioning is supported, NOT WHAT it is. If the candidate's strongest
   evidence is from a different domain than the role's primary family, that
   evidence becomes a *secondary* selling point — never the primary one.

This ordering is the central rule. The most common failure mode is letting the
candidate's most distinctive past project dictate the letter's framing even
when the job is clearly about a different role family. Don't do that.

## Required output: role_positioning

You MUST produce a `role_positioning` object with all SEVEN fields:

- **role_family**: short human-readable string naming the role family the
  job is actually hiring for (e.g., "AI/ML platform engineering",
  "biomedical-data ML modelling", "backend infrastructure engineering").
  Mirror the job ad's own framing.
- **primary_selling_point**: one short sentence stating the candidate's single
  best match for the PRIMARY role family. Must be supported by evidence.
- **secondary_selling_points**: list (possibly empty) of one-sentence
  secondary matches. Adjacent-domain experience the candidate brings that's
  worth mentioning briefly but is NOT the headline.
- **emphasise**: list of short topic names the letter should develop in its
  main paragraphs.
- **deemphasise**: list of short topic names the letter should mention only
  briefly, or not at all, even when the candidate has evidence for them —
  because they distract from the primary role family.
- **opening_angle**: one short instruction on how the letter should open.
  This shapes the writer's first paragraph.
- **risky_or_gap_areas**: list (possibly empty) of topic names the writer
  should treat carefully or avoid because the candidate has no strong
  evidence — or the alignment is weak in a way that could backfire if
  leaned on. Use this for topics that are technically "in-scope" for the
  role but where over-claiming would be detected by a reviewer.

## Special cases

- If the job is unambiguous (one dominant role family), `secondary_selling_points`
  and `deemphasise` MAY be short or empty. Do not fabricate secondary themes
  just to fill the slot.
- If the candidate has NO evidence supporting the primary role family, do
  NOT downgrade `role_family` to something the evidence supports. Instead,
  leave `role_family` aligned with the job, AND list the topic in
  `risky_or_gap_areas` so the writer treats it carefully. The writer will
  then frame the closest transferable experience honestly rather than
  pivoting away from the actual role.

## Rules

- Do not invent facts. The seven fields are positioning judgements, but
  `primary_selling_point` and `secondary_selling_points` MUST be supported
  by evidence the candidate has in the evidence map.
- Do not write full sentences in `emphasise` / `deemphasise` / `risky_or_gap_areas`
  — short topic names only.
- Mirror the job ad's terminology for `role_family` (do not editorialise).
