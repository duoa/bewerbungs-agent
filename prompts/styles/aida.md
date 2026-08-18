# AIDA Cover Letter Style

Structure the cover letter using the AIDA persuasion framework:
Attention → Interest → Desire → Action.

## Structure (in order)

1. **Attention — Opening hook**
   Open with the strongest single fact from `opening_hook` that immediately
   signals fit. One to two sentences. Avoid starting with "I am applying for…"
   — lead with the value, not the request.

2. **Interest — Evidence of relevance**
   Build interest by connecting 2–3 technical or domain evidence claims
   directly to what the role requires. Show that you understand the company's
   context or challenge (use `closing_note` cues if available).

3. **Desire — Why this matters**
   Create desire by articulating concrete past outcomes (from evidence) that
   demonstrate what the applicant will bring. Focus on what the hiring manager
   gains, not what the applicant wants. Soft skills may appear here if in plan.

4. **Action — Closing**
   End with a clear, direct call to action: express availability for a
   conversation and a brief forward-looking statement. One to two sentences.

## Style Notes

- Each AIDA section is a paragraph; no section headers in the final letter.
- The Attention paragraph should create genuine curiosity — avoid clichés.
- Desire is the longest paragraph (typically 3–5 sentences).
- Tone: engaging and confident — more dynamic than standard style, but still
  professional. No marketing hype or unsubstantiated superlatives.
- Write in first-person voice.
- Do not use bullet points or headers in the letter body.

## Restrained AIDA (feature 013 — default ON via `narrative_polish.restrained_aida`)

When `narrative_polish.restrained_aida` is `true` (the default), AIDA mode
is a SUBTLE narrative arc — NOT marketing copy. The tone remains calm,
senior, credible, and institutionally appropriate throughout.

Specifically, the Attention paragraph MUST NOT contain:

- ALL-CAPS attention grabs (e.g. "PICTURE THIS:", "IMAGINE:")
- Exclamation marks (`!`) in the opening sentence
- Second-person imperatives ("Imagine a world where...", "Picture your
  team finally...")
- Hyperbolic adjectives anywhere in the letter — "revolutionary",
  "world-class", "unparalleled", "best-in-class", "transformative",
  "game-changing", "disruptive"
- Marketing-copy framing — the letter is a cover letter to a hiring
  manager, not a sales pitch

AIDA's four moves still apply, but each is delivered with the same
institutional register as the standard style:

- Attention = a clean, specific fact about the candidate's fit; no theatre.
- Interest = evidence-grounded relevance; no "you'll love this".
- Desire = concrete past outcomes; no superlatives.
- Action = professional close; "I would welcome the opportunity to
  discuss…" — not "Don't miss out!".

If `narrative_strategy.tone_guidance` includes the phrase "restrained
AIDA", treat that as the binding tone constraint and let it override any
suggestion of dynamism above.
