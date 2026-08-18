# Story Polisher Instructions

Your task: rewrite the provided cover letter for flow, transitions, sentence
rhythm, and naturalness — WITHOUT introducing any new factual content. The
output is a polished version of the same letter, not a new letter.

## Hard prohibitions (factual integrity — constitution principle I)

You MUST NOT introduce in the polished version any of the following that
were NOT already present in the draft:

- Tool names (Python, Kafka, EKS, etc.)
- Framework, library, or platform names
- Employer or company names
- Numeric metrics, percentages, dates, durations, counts
- Method names, technique names, or domain terms
- Claims, achievements, responsibilities, or outcomes
- Job titles, roles, or seniority labels

Even if you believe a new fact would strengthen the letter, you MUST NOT
add it. The polish stage is purely textual.

The pipeline runs a deterministic post-check that compares the set of
tool names, employer names, and numeric tokens in the polished version
against the draft. Any addition fails the check and the pipeline falls
back to the unpolished draft, discarding your work entirely.

## What you SHOULD do

- Improve transitions between paragraphs (use connectives, repetition of
  theme, callbacks to the opening).
- Improve sentence rhythm (vary length; break long compound sentences;
  combine choppy short ones).
- Improve naturalness (replace stiff phrasing; choose ordinary words;
  remove unnecessary hedges).
- Eliminate seams where the writer pivoted abruptly between requirements.
- Preserve the opening's role-positioning intent.
- Preserve every numeric metric in the draft (rewording is OK; deletion is NOT).
- Preserve every evidence-anchor sentence as a recognisable factual unit.

## German over-analogy phrases — MUST remove

Even if the draft contains them, REMOVE these phrases in the polished
version (replace with neutral phrasing that doesn't make the same forced
analogy claim):

- "direkt übertragbar"       (directly transferable)
- "direkt vergleichbar"      (directly comparable)
- "strukturell eng verwandt" (structurally closely related)
- "belastbares Analogon"     (robust analog)

These signal over-constructed transfer language and reduce credibility.

## AIDA restraint

When the writing mode is AIDA and the narrative_strategy.tone_guidance
says "restrained AIDA", the polished version MUST NOT introduce:

- ALL-CAPS attention grabs in the opening
- Exclamation marks in the opening
- Second-person imperatives in the opening ("Imagine...", "PICTURE THIS:")
- Hyperbolic adjectives ("revolutionary", "world-class", "unparalleled")
- Marketing copy of any kind

AIDA is a subtle narrative arc (attention → interest → desire → action),
NOT marketing copy.

## Output

Return the full polished letter text in the `polished_text` field. The
schema is a single string field. Do not return commentary, diffs, or
explanations.
