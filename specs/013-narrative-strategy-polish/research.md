# Research: Narrative Strategy & Story Polish

**Feature**: 013-narrative-strategy-polish
**Date**: 2026-06-05

Ten design decisions resolved before implementation. Each was the live tension at the spec/plan boundary.

---

## R1. Where does `role_positioning` live now?

**Decision**: Split `role_positioning` into its own dedicated stage (`role_position.py`) with its own prompt (`role_positioner.md`). The prompt content is moved verbatim from the existing role-positioning section of `planner.md`; the output schema (`RolePositioning` Pydantic model) is unchanged.

**Rationale**: The `/plan` command's instruction "insert a narrative_strategy stage after role_positioning and before content_plan" treats role-positioning as a discrete pipeline step. The spec's constraint "do not change role positioning" reads as "do not change the role-positioning *logic or output shape*" — not "do not change its call site". Splitting preserves the logic and shape while satisfying the sequencing requirement.

**Alternatives considered**:
- (a) Keep role-positioning inside `plan_content` and treat "after role_positioning" as conceptual. Rejected: the user explicitly named role_positioning as a pipeline step in the `/plan` directive; conceptual ordering would surprise.
- (b) Compute role_positioning twice (once in narrative_strategy as a precursor, once in plan_content). Rejected: redundant LLM call, two sources of truth that can drift.
- (c) Move role_positioning into `narrative_strategy` itself. Rejected: collapses two distinct outputs into one stage; loses inspectability.

**Cost**: One extra LLM call per run (the extracted role-positioning call). Mitigated by stripping the role-positioning ask from `plan_content` (its prompt and output both shrink).

---

## R2. What does the `NarrativeStrategy` Pydantic schema look like?

**Decision**: Nine required fields per spec FR-002 through FR-011. All string fields are bounded (max_length on each); list fields are `default_factory=list` and bounded by element count. `proof_points_to_use` and `proof_points_to_avoid` are typed as `list[str]` of evidence-claim text references (matching the existing `evidence_refs` pattern in `ParagraphPlan`). `model_config = ConfigDict(extra="forbid")` to catch typo top-level fields, matching the existing `ContentPlan` / `ParagraphPlan` discipline from feature 011.

| Field | Type | Bound | Notes |
|---|---|---|---|
| `candidate_story` | `str` | min_length=1, max_length=800 | 1–3 sentences |
| `role_story` | `str` | min_length=1, max_length=800 | 1–3 sentences |
| `bridge` | `str` | min_length=1, max_length=800 | 1–3 sentences |
| `opening_angle` | `str` | min_length=1, max_length=400 | matches feature-011 paragraph `max_length=400` |
| `proof_points_to_use` | `list[str]` | max_length=12 elements | each must trace to `EvidenceItem.claim` (stage-level check) |
| `proof_points_to_avoid` | `list[str]` | max_length=12 elements | each must trace to `EvidenceItem.claim` (stage-level check) |
| `transfer_framing_guidance` | `str` | max_length=600 | empty-string-allowed-but-recommended; spec FR-009 |
| `tone_guidance` | `str` | min_length=1, max_length=600 | AIDA-constrained when mode=aida (validator) |
| `anti_patterns` | `list[str]` | max_length=20, each ≤ 240 chars | short phrasings to avoid |

**Rationale**: Bounds chosen to be defensive against runaway LLM output but generous enough for German (compound nouns inflate length 30–40%, lesson learned from feature 011's `main_message=400` bump).

**Alternatives considered**:
- (a) Use 300-char caps everywhere. Rejected: German would crash, as already happened in feature 011 production.
- (b) No upper bound on list elements. Rejected: a runaway 50-element `proof_points_to_use` would defeat the purpose (force the writer to pick); 12 is generous for the longest realistic evidence map.

---

## R3. How does the planner consume `NarrativeStrategy` without duplicating role_positioning?

**Decision**: After R1, `plan_content` no longer produces `role_positioning` — it consumes it from upstream state. The planner's prompt loses its role-positioning section (moved to `role_positioner.md`) and gains a `# Narrative Strategy` block summarising the strategy's nine fields. The planner produces `ContentPlan` with `role_positioning` populated from upstream (pass-through), `paragraphs` shaped by the strategy, and the rest of the existing fields unchanged.

The `ContentPlan` schema keeps the `role_positioning: RolePositioning | None` field for backward-compat with legacy artefacts; in this feature's runtime flow it is always populated (pass-through from `role_position` stage).

**Rationale**: Avoids breaking downstream consumers that read `ContentPlan.role_positioning` (e.g., `write_letter._format_positioning_block`, hiring review's content-plan summary). The field becomes a pass-through but its existence on the model is preserved.

---

## R4. How does the planner enforce `proof_points_to_avoid`?

**Decision**: Two-layer enforcement:
1. **Prompt-level (soft)**: The new `# Narrative Strategy` block in the planner prompt lists `proof_points_to_avoid` explicitly with the instruction "DO NOT build paragraphs around these claims — they dilute the narrative".
2. **Stage-level (hard)**: After `ContentPlan.model_validate(data)`, `plan_content` iterates `plan.paragraphs` and removes any paragraph whose `evidence_refs` intersect `narrative_strategy.proof_points_to_avoid`. Removal is logged as a tracker event. If the removal would leave zero paragraphs, the stage raises `ValueError` (a strategy that vetoes its own narrative is a planner bug).

**Rationale**: LLMs sometimes ignore prompt-level "do not" rules. The stage-level filter is the deterministic backstop. Logging the removal makes the behaviour debuggable.

**Alternatives considered**:
- (a) Prompt-only. Rejected: feature 011 already demonstrated three production crashes where LLMs ignored explicit prompt constraints; deterministic backstop is mandatory for correctness contracts.
- (b) Model-validator on `ContentPlan` that cross-checks against `NarrativeStrategy`. Rejected: model validators can't reach `WorkflowState` (same constraint that forced feature 011's `requirement_ids` check to live in the stage).

---

## R5. What does the `StoryPolishOutput` post-check look like?

**Decision**: A deterministic, three-extractor subset check.

```python
def _post_check(draft: str, polished: str, tool_registry: set[str]) -> StoryPolishPostCheck:
    draft_tools     = tool_names_in_text(draft, tool_registry)
    polished_tools  = tool_names_in_text(polished, tool_registry)
    draft_employers = employer_names_in_text(draft)
    polished_emp    = employer_names_in_text(polished)
    draft_numerics  = numeric_tokens_in_text(draft)
    polished_num    = numeric_tokens_in_text(polished)

    added_tools     = polished_tools - draft_tools
    added_employers = polished_emp - draft_employers
    added_numerics  = polished_num - draft_numerics

    passed = not (added_tools or added_employers or added_numerics)
    return StoryPolishPostCheck(
        passed=passed,
        added_tools=sorted(added_tools),
        added_employers=sorted(added_employers),
        added_numerics=sorted(added_numerics),
    )
```

Extractors live in `utils/extractors.py` and are independently unit-tested.

**Tool extractor**: case-insensitive whole-word match against `tool_registry`. Whole-word means surrounded by non-word characters (or start/end of string). "AWS" matches in "AWS-managed" (hyphen is non-word) but not in "AWSome" (hyphen would be word-internal).

**Employer extractor**: capitalised multi-word phrases (`r'\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b'`) restricted to context windows after one of `["at ", "bei ", "with ", "für ", "for "]`. Plus a configured employer registry (seeded from the candidate's profile in tests). Heuristic — accepts that proper-noun detection has noise; the deterministic check fires only on *additions*, so a false positive in extraction that's present in BOTH draft and polished is harmless.

**Numeric extractor**: digit sequences with `~`, `,`, `+`, `%`, and `.` (when followed by a digit) stripped before comparison. "1000" / "1,000" / "~1000" / "1000+" / "1000%" all map to `"1000"`. "1.5" maps to `"1.5"` (decimal preserved). "1000" and "1500" are different.

**Rationale**: This is the load-bearing correctness contract for US2. The constitution makes factual integrity non-negotiable; the post-check is the mechanical enforcement. The three extractors are simple enough to test exhaustively and tolerant enough to allow legitimate flow improvements (whitespace, punctuation, sentence reordering).

**Alternatives considered**:
- (a) LLM-as-judge for "did this polish add facts?". Rejected: defeats the deterministic-safety-net goal; introduces a new LLM dependency for a check that should be a 50-line pure function.
- (b) Diff-based check (any deletion is OK, any insertion is suspect). Rejected: too strict — polishing is precisely rewording, which inserts new words; we only care about *categories* of facts.
- (c) Exact-string-only check (no normalisation). Rejected: a polished `"~1000"` from a draft `"1000"` is a tone improvement, not a fact addition.

---

## R6. How does `story_polish` fall back gracefully?

**Decision**: Three failure modes, all non-fatal:
1. **LLM call fails / times out** → log warning, return `StoryPolishOutput(polished_text=draft, used_fallback=True, fallback_reason="llm_failure: <msg>", post_check_passed=True)`.
2. **Post-check fails** → log warning, return `StoryPolishOutput(polished_text=draft, used_fallback=True, fallback_reason="post_check_failed: added_tools=[...] added_employers=[...] added_numerics=[...]", post_check_passed=False)`.
3. **Stage disabled by config** → skip entirely; downstream sees `state.letter_draft` (no `StoryPolishOutput` artefact written). The hiring reviewer reads `state.letter_draft.text` regardless (already its current behaviour).

In all three cases, the LangGraph node returns `{"letter_draft": state.letter_draft.model_copy(update={"text": polished_or_draft_text}), "story_polish_output": output_or_None}` so that downstream stages always read from `letter_draft.text`.

**Rationale**: Constitution principle I — factual integrity is non-negotiable. The polish stage is a quality nice-to-have; never let it become a correctness liability. Falling back to the draft is always safe because the draft already passed all upstream invariants.

---

## R7. How does `hiring_review` get the six new dimensions wired in?

**Decision**: The `/plan` directive names six dimensions: `story_coherence`, `transition_smoothness`, `over_constructed_language`, `claim_relevance`, `aida_restraint`, `human_readability`. The spec named seven. **Reconcile by adopting the `/plan` list (six)** — the directive is the more recent authority. The spec's seven were drafted earlier with slightly different naming; the six in `/plan` cover the same conceptual ground with better names. Mapping:

| Spec name (FR-027) | `/plan` name | Notes |
|---|---|---|
| `over_constructed_transfer_language` | `over_constructed_language` | broader scope per /plan |
| `forced_analogies` | (folded into `over_constructed_language` + over-analogy phrase blocklist) | deterministic blocklist replaces dedicated dimension |
| `defensive_domain_transition` | (folded into `transition_smoothness`) | one dimension covers both directions |
| `overdramatic_aida` | `aida_restraint` | symmetric framing (pass = restrained) |
| `weak_narrative_coherence` | `story_coherence` | rename for clarity |
| `low_relevance_impact_claims` | `claim_relevance` | rename for clarity |
| `machine_like_requirement_mapping` | `human_readability` | broader framing |

Each dimension produces severity (`pass`, `warn`, `error`), rationale (≤ 240 chars), and an evidence quote when severity ≥ `warn`. The hiring-review prompt is rewritten to instruct evaluation of all six.

Aggregate verdict escalation: when `aida_restraint` or `transition_smoothness` reports severity ≥ `warn`, the verdict cannot remain `pass` (mirrors feature 012's pattern).

**Rationale**: Six well-named dimensions are easier for the LLM to evaluate consistently than seven overlapping ones. The deterministic blocklist (R8) catches the worst over-analogy cases the dropped `forced_analogies` dimension would have caught.

**Alternatives considered**:
- (a) Keep both lists (13 dimensions total). Rejected: too many dimensions dilutes LLM attention; many would correlate.
- (b) Keep spec's seven. Rejected: the `/plan` directive is more recent and named the cleaner set.

---

## R8. Where does the German over-analogy phrase blocklist live?

**Decision**: Inside `stages/hiring_review.py`, as a deterministic post-processing step that runs after the LLM-driven review and *adds* findings to the structured output. Implemented as a small list `OVER_ANALOGY_PHRASES_DE = ["direkt übertragbar", "direkt vergleichbar", "strukturell eng verwandt", "belastbares Analogon"]` plus a case-insensitive substring scan. Each match contributes one `warn`-severity finding to a new `deterministic_findings` field on the hiring-review output, with `phrase`, `char_start`, and surrounding context.

**Rationale**:
- Hiring review is the natural home: it already evaluates letter quality, and operators look there for "what's wrong with my letter".
- Deterministic checks belong adjacent to the LLM evaluation that they complement — keeps the surface coherent.
- Feature 012's validation report is a more natural long-term home, but feature 012 isn't shipped yet; placing the check in hiring_review now is a forward-compatible interim solution.

**Why not in `story_polish`'s prompt as a banned-phrase list?** Because the phrases are the *symptom*, not the *failure*. A polished letter that no longer contains the phrase but still relies on forced analogies internally would slip through. The hiring-review LLM evaluates the substance; the deterministic scan catches the surface tells.

**Future**: when feature 012 lands, the over-analogy scan moves to the validation report's `overclaim_risk`/`forced_analogy` finding and is removed from hiring_review.

---

## R9. Auto-generated schema propagation

**Decision**: All new Pydantic models (`NarrativeStrategy`, `StoryPolishOutput`, extended `HiringReviewOutput`) are passed to the Anthropic client via `Model.model_json_schema()` in the same pattern as existing stages (`plan_content`, `write_letter`, `hiring_review`). No hand-written JSON schemas.

**Rationale**: Existing convention; auto-generation guarantees field/constraint sync between the runtime validator and the tool-call schema the LLM sees.

---

## R10. Test surface inventory

**Decision**: The following test files / test classes are required for this feature. Counts the user's five mandated test categories plus the standard stage-isolation pattern.

| Test surface | File | Classes | Approx test count |
|---|---|---|---|
| `NarrativeStrategy` schema parsing | `tests/unit/test_narrative_strategy.py` | `TestNarrativeStrategySchema` | 4 (required fields, max_length bounds, list bounds, extra="forbid") |
| Stage order (graph wired correctly) | `tests/unit/test_workflow_graph.py` (extended) OR `tests/integration/test_full_run.py` | `TestPipelineOrderFeature013` | 1 (sequence: role_position → narrative_strategy → plan_content → write_letter → story_polish → hiring_review) |
| Prompt assembly — planner | `tests/unit/test_plan_content.py` (extended) | `TestPlannerConsumesNarrativeStrategy` | 2 (narrative_strategy block surfaces; proof_points_to_avoid filter drops paragraphs) |
| Prompt assembly — writer | `tests/unit/test_write_letter.py` (extended) | `TestWriterConsumesNarrativeStrategy` | 2 (narrative_strategy block surfaces; opening_angle reflected) |
| Prompt assembly — hiring_review | `tests/unit/test_hiring_review.py` (extended) | `TestHiringReviewCraftDimensions` | 2 (six dimensions in prompt; all six in structured output) |
| `story_polish` no-new-claims (mocked) | `tests/unit/test_story_polish.py` | `TestStoryPolishPostCheck` | 4 (subset OK; added tool fails; added employer fails; added numeric fails) |
| `story_polish` fallback paths | same file | `TestStoryPolishFallback` | 3 (LLM failure; post-check failure; disabled) |
| Hiring review over-constructed transfer language | `tests/unit/test_hiring_review.py` (extended) | `TestHiringReviewDeterministicScan` | 2 (`"direkt übertragbar"` detected; clean letter clean) |
| Extractors (post-check building blocks) | `tests/unit/test_extractors.py` | `TestToolExtractor`, `TestEmployerExtractor`, `TestNumericExtractor` | 8 (whole-word match; case-insensitive; AWS-managed; numeric normalisation; etc.) |
| `role_position` extracted stage | `tests/unit/test_role_position.py` | `TestRolePositionStage` | 3 (prompt build; parse_response; schema unchanged from prior `RolePositioning`) |

**Total**: ~31 new tests. Existing 266 + ~31 = ~297 target.

**Rationale**: Covers the five user-mandated categories explicitly (NarrativeStrategy schema parsing, stage order, prompt assembly, no-new-claims with mocked output, over-constructed transfer language review findings) plus the extractor primitives that the post-check depends on. The extractor tests are mandatory because the post-check is the constitution's load-bearing correctness contract for US2.
