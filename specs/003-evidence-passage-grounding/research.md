# Research: Evidence Passage Grounding

**Feature**: 003-evidence-passage-grounding  
**Date**: 2026-04-15  
**Status**: Complete — no unknowns; all decisions are derivable from existing codebase

## Decision 1: How to pass full document content without truncation

**Decision**: Remove the hard character truncation in `build_evidence_map.build_prompt` (`:3000`, `:1500`, `:500`) and pass the full text of each document directly in the prompt. No chunking strategy, no vector search.

**Rationale**: Documents in typical user profiles are 2–8 KB each. The claude-sonnet-4-6 context window is 200 K tokens. A full profile (CV + skills + 5 project docs + 3 previous letters) totals roughly 30–60 KB — comfortably within a single call. The current truncation was a conservative default that predated validation of typical profile sizes. Removing it is the simplest correct fix.

**Alternatives considered**:
- Sliding-window chunking with overlap: unnecessary complexity for files of this size; rejected.
- Vector search / embedding retrieval: introduces a new dependency and infrastructure requirement; rejected for this iteration (spec explicitly defers this).
- Summarise-then-extract two-step: adds a second LLM call per document; rejected for cost and latency reasons.

## Decision 2: Verbatim passage extraction strategy

**Decision**: Instruct the LLM via prompt to return exact quoted text from the supplied document as the `passage` field, rather than paraphrasing. The prompt will include an explicit instruction such as: "Quote the exact text from the source document that supports this claim. Do not paraphrase."

**Rationale**: No post-hoc substring validation is performed (spec FR clarification: "no semantic or verbatim claim validation"). The LLM is trusted to comply when given clear instructions. Empirically, claude-sonnet-4-6 reliably quotes source text when explicitly instructed to do so.

**Alternatives considered**:
- Post-hoc substring match + rejection: adds complexity and may over-reject legitimate near-verbatim quotes; explicitly out of scope per clarifications.
- Structured extraction with character offsets: more precise but adds schema complexity; deferred.

## Decision 3: Empty-passage handling (FR-006)

**Decision**: In `build_evidence_map.parse_response`, after deserialising each `EvidenceItem`, check whether `passage` is empty (after `.strip()`). If so, drop the item from `items` and append its `claim` to `known_gaps`. The pipeline continues normally.

**Rationale**: Aborting on an empty passage would be too brittle for profiles where some requirements have no evidence. The existing `known_gaps` mechanism already handles coverage gaps — reusing it keeps the architecture consistent.

**Alternatives considered**:
- Keep item in map with a warning flag: adds a new "warning" state to EvidenceItem; unnecessary complexity given existing known_gaps pattern.
- Abort pipeline: explicitly rejected in spec clarifications.

## Decision 4: Data model extensions

**Decision**: Add two new optional fields with safe defaults:
- `EvidenceItem.relevance_note: str = ""` — one-sentence LLM explanation of why this passage supports the claim.
- `SectionPlan.anchor_passages: list[str] = Field(default_factory=list)` — list of verbatim passages the letter writer should anchor prose to for this section.

**Rationale**: `relevance_note` gives the planner (and the user reviewing the plan) a human-readable reason for each evidence selection, improving auditability. `anchor_passages` makes the per-section passage contract explicit — the writer sees exactly which text to use, reducing generic paraphrase risk. Both fields use safe defaults, so existing serialised state (e.g., in tests) remains valid without migration.

**Alternatives considered**:
- Embed passages only in the EvidenceMap inside ContentPlan (already present, no new field): the writer must then cross-reference by claim text to find the passage; making them explicit per section is clearer.
- Store anchor_passages as `list[EvidenceItem]` objects: richer but redundant given the full evidence_map is already embedded in ContentPlan; plain strings are sufficient for the writer.

## Decision 5: How anchor_passages flow into plan_content

**Decision**: Update `plan_content.build_prompt` to include the verbatim passage alongside each claim in the claims list, formatted as:

```
- [claim text] [source: source_file]
  Passage: "[verbatim excerpt]"
```

The planner LLM is instructed to copy the relevant passages into `SectionPlan.anchor_passages` for each section it creates.

**Rationale**: The planner needs to see the passages to select and forward the right ones. Since passages are already in the `EvidenceMap`, this is a prompt formatting change only — no additional data loading.

## Decision 6: writer_letter prompt update

**Decision**: Add a single instruction line to `write_letter.build_prompt`: "For each section, anchor your prose to the `anchor_passages` listed in that section. Use their phrasing as a starting point."

**Rationale**: The writer already receives the full ContentPlan JSON, which now includes `anchor_passages`. This one-line prompt addition directs attention to the new field. No structural change to isolation or schema is needed.

## No NEEDS CLARIFICATION items

All technical decisions are grounded in the existing codebase. No external dependencies, protocols, or integrations are introduced.
