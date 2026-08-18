# Contract: Schemas, Prompts, Formatters, and Pipeline Graph

**Feature**: 013-narrative-strategy-polish
**Date**: 2026-06-05

Six contract sections: (1) graph topology, (2) prompt files, (3) `narrative_strategy.build_prompt` shape, (4) `plan_content` consumption + proof_points_to_avoid filter, (5) `write_letter` narrative-strategy block, (6) `story_polish` stage contract including post-check, (7) `hiring_review` extension (LLM dimensions + deterministic over-analogy scan + aggregate-verdict escalation), (8) observability + Langfuse prompt-sync expectations, (9) non-interference invariants.

---

## 1. Pipeline graph topology

### Before (current main)

```
load_job → extract_requirements → load_profile → select_cv_variant
        → build_evidence_map → plan_content → write_letter → hiring_review
        → targeted_rewrite → validate_outputs → rewrite_if_needed
```

`plan_content` produces `role_positioning` internally as a field on `ContentPlan`.

### After (feature 013)

```
load_job → extract_requirements → load_profile → select_cv_variant
        → build_evidence_map
        → role_position          (NEW — extracted)
        → narrative_strategy     (NEW)
        → plan_content           (MODIFIED — consumes role_positioning + narrative_strategy)
        → write_letter           (MODIFIED — consumes narrative_strategy)
        → story_polish           (NEW — configurable, fallback-safe)
        → hiring_review          (MODIFIED — adds craft_dimensions + deterministic_findings)
        → targeted_rewrite → validate_outputs → rewrite_if_needed
```

### Graph edges to add/remove in `graph/workflow.py`

```python
# REMOVE
graph.add_edge("build_evidence_map", "plan_content")

# ADD
graph.add_node("role_position", role_position_node)
graph.add_node("narrative_strategy", narrative_strategy_node)
graph.add_node("story_polish", story_polish_node)

graph.add_edge("build_evidence_map", "role_position")
graph.add_edge("role_position", "narrative_strategy")
graph.add_edge("narrative_strategy", "plan_content")
# plan_content → write_letter edge unchanged
# plan_content → tailor_cv edge unchanged
graph.add_edge("write_letter", "story_polish")
graph.add_edge("story_polish", "hiring_review")
# REMOVE existing graph.add_edge("write_letter", "hiring_review")
```

The `tailor_cv` parallel branch (`plan_content → tailor_cv → hiring_review`) is preserved as-is. Hiring review continues to merge both branches (`write_letter`/`story_polish` AND `tailor_cv`).

---

## 2. Prompt files

| File | Status | Source |
|---|---|---|
| `prompts/role_positioner.md` | NEW | Moved verbatim from the role-positioning section of `prompts/planner.md` (existing content; just relocated) |
| `prompts/narrative_strategist.md` | NEW | New content per §3 below |
| `prompts/planner.md` | MODIFIED | Role-positioning section REMOVED; new `# Consumes Narrative Strategy` section added per §4 |
| `prompts/writer.md` | MODIFIED | New "Narrative strategy consumption (feature 013)" sub-section per §5 |
| `prompts/story_polisher.md` | NEW | New content per §6 |
| `prompts/hiring_reviewer.md` | MODIFIED | Six craft dimensions + restrained-AIDA evaluation guidance per §7 |
| `prompts/styles/aida.md` | MODIFIED | Restrained-tone reinforcement (when `restrained_aida=True` in config) |

Expected `jobagent prompts sync` output after this feature: `5 created, 5 unchanged`. The five created are `role_positioner`, `narrative_strategist`, `planner`, `writer`, `story_polisher`, `hiring_reviewer`, and `styles/aida` — wait, that's seven names. Let me reconcile: `planner` + `writer` + `hiring_reviewer` are edits to existing files (`CREATED` because the content hash changes ⇒ a new version is created in the registry — that's the same pattern features 011/012 exhibited). `styles/aida` is similarly a new version. So expected sync: **`7 created, 3 unchanged`** (the three unchanged are `requirements`, `system`, `tailor_cv`, `validator`, `targeted_rewriter`, `evidence-label` minus the ones that did change — count those carefully at sync time). Operators verify by inspecting `git diff prompts/` before running sync.

---

## 3. `narrative_strategy` stage contract

### 3.1 Stage signature

```python
def narrative_strategy(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: produce a NarrativeStrategy before content planning.

    Inputs (from state):
      - state.job_context     (required)
      - state.requirements    (required; uses requirement_items when present)
      - state.evidence_map    (required; cross-checked against proof_points)
      - state.role_positioning (required; passes through to the prompt)
      - state.config          (required; reads narrative_polish.* + writing mode)

    Outputs:
      {"narrative_strategy": NarrativeStrategy(...)}
    """
```

### 3.2 `build_prompt(state)` shape

```
# Task
Produce a NarrativeStrategy for this letter.

Configuration: language=DE, tone=neutral-professionell, mode=standard

# Job Description (verbatim)
<state.job_context.raw_job_text>

# Weighted Requirements (priority-ordered)
- [R1, priority=high, evidence=required, category=...] ...

# Role Positioning (already decided upstream)
- role_family: AI/ML platform engineering
- primary_selling_point: ...
- secondary_selling_points: ...
- emphasise: ...
- deemphasise: ...
- opening_angle: ...
- risky_or_gap_areas: ...

# Available Evidence Claims
- "Built scalable Python ML inference platforms ..." [source: cv_software.md]
  Passage: "..."
- ...

# Instructions
<contents of prompts/narrative_strategist.md>

IMPORTANT: Each entry in `proof_points_to_use` and `proof_points_to_avoid`
MUST appear verbatim in the evidence-claim list above. When mode=aida AND
narrative_polish.restrained_aida=True, tone_guidance MUST contain the
literal phrase "restrained AIDA" and constrain the writer to a calm,
senior, institutional voice (no marketing copy).
```

### 3.3 Fallback behaviour (LLM failure OR `narrative_strategy_enabled=False`)

```python
def _fallback_strategy(state: WorkflowState) -> NarrativeStrategy:
    """Minimal deterministic strategy derived from already-decided positioning."""
    rp = state.role_positioning
    assert rp is not None  # role_position stage runs first
    top_claims = [item.claim for item in state.evidence_map.items[:6]] if state.evidence_map else []
    return NarrativeStrategy(
        candidate_story=f"Candidate's strongest positioning is in {rp.role_family}.",
        role_story=f"This role is in {rp.role_family}.",
        bridge=rp.primary_selling_point or "Direct alignment between background and role.",
        opening_angle=rp.opening_angle,
        proof_points_to_use=top_claims,
        proof_points_to_avoid=[],
        transfer_framing_guidance="",
        tone_guidance=(
            "Calm, senior, credible, institutional voice."
            + (" Restrained AIDA — narrative arc only, no marketing copy."
               if state.config.mode == WritingMode.aida else "")
        ),
        anti_patterns=[
            "Do not open with 'Although my background is...' — defensive framing",
            "Do not use marketing imperatives ('Imagine...', 'PICTURE THIS:')",
        ],
    )
```

---

## 4. `plan_content` modifications

### 4.1 Prompt change — `prompts/planner.md`

REMOVE the entire role-positioning section (relocated to `prompts/role_positioner.md`). REPLACE the existing "You MUST populate the `role_positioning` object" reminder with:

```
You MUST NOT produce `role_positioning` — it has already been decided
upstream and will be attached to the ContentPlan automatically. Focus on:
letter_thesis, paragraphs (ordered), sections, selected_soft_skills, evidence_map.

You will receive a `# Narrative Strategy` block listing candidate_story,
role_story, bridge, opening_angle, proof_points_to_use, proof_points_to_avoid,
transfer_framing_guidance, tone_guidance, and anti_patterns. Treat this
strategy as the spine of the letter — paragraphs MUST support its bridge
and opening_angle. Paragraphs whose evidence_refs overlap with
proof_points_to_avoid MUST be omitted.
```

### 4.2 `build_prompt(state)` additions

Insert a new `# Narrative Strategy` block between the existing `# Weighted Requirements` block and the `# Available Evidence Claims` block:

```python
narrative_block = ""
if state.narrative_strategy is not None:
    ns = state.narrative_strategy
    avoid_lines = "\n".join(f"  - {c}" for c in ns.proof_points_to_avoid) or "  (none)"
    use_lines = "\n".join(f"  - {c}" for c in ns.proof_points_to_use) or "  (none)"
    anti_lines = "\n".join(f"  - {p}" for p in ns.anti_patterns) or "  (none)"
    narrative_block = (
        "# Narrative Strategy\n"
        f"- candidate_story: {ns.candidate_story}\n"
        f"- role_story: {ns.role_story}\n"
        f"- bridge: {ns.bridge}\n"
        f"- opening_angle: {ns.opening_angle}\n"
        f"- proof_points_to_use:\n{use_lines}\n"
        f"- proof_points_to_avoid:\n{avoid_lines}\n"
        f"- transfer_framing_guidance: {ns.transfer_framing_guidance or '(none)'}\n"
        f"- tone_guidance: {ns.tone_guidance}\n"
        f"- anti_patterns:\n{anti_lines}\n\n"
    )
```

### 4.3 `plan_content` LangGraph node — proof_points_to_avoid filter

After `parse_response` succeeds, but before the existing `requirement_ids` cross-check:

```python
if state.narrative_strategy is not None and plan.paragraphs:
    avoid = set(state.narrative_strategy.proof_points_to_avoid)
    if avoid:
        kept: list[ParagraphPlan] = []
        for i, p in enumerate(plan.paragraphs):
            overlap = avoid.intersection(p.evidence_refs)
            if overlap:
                if state.tracker:
                    state.tracker.log_event(
                        "narrative_strategy.paragraph_dropped",
                        {"index": i, "purpose": p.purpose, "overlap": sorted(overlap)},
                    )
                continue
            kept.append(p)
        if not kept and plan.paragraphs:
            raise ValueError(
                "narrative_strategy.proof_points_to_avoid vetoed every paragraph — "
                "the strategy is incompatible with the plan."
            )
        plan = plan.model_copy(update={"paragraphs": kept})
```

Then attach the upstream role_positioning as pass-through:

```python
plan = plan.model_copy(update={"role_positioning": state.role_positioning})
```

---

## 5. `write_letter` modifications

### 5.1 New helper

```python
def _format_narrative_strategy_block(state: WorkflowState) -> str:
    """Render the narrative_strategy as a structured block in the writer prompt.
    Empty string when state.narrative_strategy is None (legacy compat)."""
    ns = state.narrative_strategy
    if ns is None:
        return ""

    use = "\n".join(f"  - {c}" for c in ns.proof_points_to_use) or "  (none)"
    avoid = "\n".join(f"  - {c}" for c in ns.proof_points_to_avoid) or "  (none)"
    anti = "\n".join(f"  - {p}" for p in ns.anti_patterns) or "  (none)"
    return (
        "# Narrative Strategy\n"
        f"- candidate_story: {ns.candidate_story}\n"
        f"- role_story: {ns.role_story}\n"
        f"- bridge: {ns.bridge}\n"
        f"- opening_angle: {ns.opening_angle}\n"
        f"- transfer_framing_guidance: {ns.transfer_framing_guidance or '(none)'}\n"
        f"- tone_guidance: {ns.tone_guidance}\n"
        f"- proof_points_to_use:\n{use}\n"
        f"- proof_points_to_avoid:\n{avoid}\n"
        f"- anti_patterns:\n{anti}\n\n"
    )
```

### 5.2 Wire into `build_prompt`

Insert between the existing `# Writer Rules` block and the `# Paragraph Plan` block (which itself was added by feature 011):

```python
narrative_block = _format_narrative_strategy_block(state)
content = (
    f"Write a cover letter from the structured content plan below.\n\n"
    f"Configuration: ...\n\n"
    f"{positioning_block}\n"
    f"{rules_block}\n"
    f"{narrative_block}"        # NEW (feature 013)
    f"{paragraphs_block}"
    f"# Writing Mode Instructions\n{style_instructions}\n\n"
    # ... rest unchanged ...
)
```

### 5.3 Prompt change — `prompts/writer.md`

Add new section after "Paragraph plan consumption (feature 011)":

```
### 11. Narrative strategy consumption (feature 013)

When a `Narrative Strategy` block is present in the prompt:

- Your opening prose MUST reflect `opening_angle` in substance (not
  necessarily verbatim).
- You MUST NOT include any claim whose text appears in
  `proof_points_to_avoid`.
- You MUST avoid every phrasing/move listed in `anti_patterns`. The list
  contains specific failure modes ("Do not open with 'Although...'") —
  treat them as hard prohibitions.
- Treat `bridge` as the load-bearing sentence type — the letter's logical
  spine. Each paragraph should ladder up to it.
- `tone_guidance` modulates rules 1–9 above. When it says "restrained AIDA",
  AIDA mode is a subtle narrative arc — no marketing imperatives, no
  ALL-CAPS, no exclamation marks in the opening, no second-person calls
  to action.
```

---

## 6. `story_polish` stage contract

### 6.1 Stage signature + flow

```python
def story_polish(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: polish prose without adding facts.

    Inputs (from state):
      - state.letter_draft       (required)
      - state.content_plan       (required; passed to prompt for context)
      - state.narrative_strategy (required; tone guidance)
      - state.role_positioning   (required; for context)
      - state.config             (required; reads narrative_polish.story_polish_enabled)

    Outputs:
      {
        "letter_draft": <draft updated to polished_text or kept identical on fallback>,
        "story_polish_output": StoryPolishOutput(...)
      }
    """
```

### 6.2 Disabled path

```python
if not state.config.narrative_polish.story_polish_enabled:
    return {"letter_draft": state.letter_draft, "story_polish_output": None}
```

### 6.3 LLM call + post-check

```python
draft_text = state.letter_draft.text
messages = build_prompt(state)
schema = {"title": "story_polish", "type": "object",
          "properties": {"polished_text": {"type": "string"}},
          "required": ["polished_text"]}

try:
    response = client.call(messages, schema, system=load_prompt("system"), thinking=stage_th)
    polished_text = response["polished_text"]
except Exception as exc:
    return _fallback(state, reason=f"llm_failure: {exc!s}"[:240])

check = _post_check(draft_text, polished_text, tool_registry=_resolve_tool_registry(state))
if not check.passed:
    return _fallback(
        state,
        reason=(
            f"post_check_failed: tools={check.added_tools} "
            f"employers={check.added_employers} numerics={check.added_numerics}"
        )[:240],
        check=check,
    )

# Accept polished text
updated_draft = state.letter_draft.model_copy(update={"text": polished_text})
output = StoryPolishOutput(
    polished_text=polished_text,
    post_check_passed=True,
    post_check_rationale="all extracted sets are subsets of draft",
    used_fallback=False,
    fallback_reason=None,
    added_tools=[], added_employers=[], added_numerics=[],
    diff_char_count=abs(len(polished_text) - len(draft_text)),
)
return {"letter_draft": updated_draft, "story_polish_output": output}
```

### 6.4 `_fallback` helper

```python
def _fallback(state: WorkflowState, reason: str, check: StoryPolishPostCheck | None = None) -> dict[str, Any]:
    output = StoryPolishOutput(
        polished_text=state.letter_draft.text,
        post_check_passed=False,
        post_check_rationale=reason,
        used_fallback=True,
        fallback_reason=reason,
        added_tools=check.added_tools if check else [],
        added_employers=check.added_employers if check else [],
        added_numerics=check.added_numerics if check else [],
        diff_char_count=0,
    )
    return {"letter_draft": state.letter_draft, "story_polish_output": output}
```

### 6.5 `_post_check` + extractors

Lives in `utils/extractors.py` (new):

```python
TOOL_REGISTRY_DEFAULT = frozenset({
    "Python", "Kafka", "Spark", "Airflow", "Beam", "Snowflake", "dbt",
    "Terraform", "Kubernetes", "K8s", "EKS", "S3", "MSK", "RDS", "AWS",
    "GCP", "Azure", "Argo", "Docker", "PostgreSQL", "Redis", "PyTorch",
    "TensorFlow", "JAX", "Ray", "MLflow", "FastAPI", "Django", "React",
    "TypeScript", "JavaScript", "Node", "Go", "Rust", "Java", "Scala",
    "C++", "C#", "SQL", "GraphQL", "REST",
})

EMPLOYER_CONTEXT_PREFIXES = ("at ", "bei ", "with ", "für ", "for ", " @ ")

def tool_names_in_text(text: str, registry: set[str]) -> set[str]:
    """Whole-word case-insensitive matches against the registry."""
    found = set()
    lowered = text.lower()
    for tool in registry:
        pattern = r"(?<![\w]){}(?![\w])".format(re.escape(tool.lower()))
        if re.search(pattern, lowered):
            found.add(tool)
    return found

def employer_names_in_text(text: str) -> set[str]:
    """Capitalised multi-word phrases after EMPLOYER_CONTEXT_PREFIXES."""
    found = set()
    for prefix in EMPLOYER_CONTEXT_PREFIXES:
        pattern = re.escape(prefix) + r"([A-Z][\w&]*(?:\s+[A-Z][\w&]*){0,3})"
        for m in re.finditer(pattern, text):
            found.add(m.group(1).strip())
    return found

NUMERIC_RE = re.compile(r"[~+]*(\d[\d,]*(?:\.\d+)?)\s*[%+]*")

def numeric_tokens_in_text(text: str) -> set[str]:
    """Digit sequences normalised by stripping ~, commas, +, %."""
    found = set()
    for m in NUMERIC_RE.finditer(text):
        normalised = m.group(1).replace(",", "")
        found.add(normalised)
    return found

@dataclass(frozen=True)
class StoryPolishPostCheck:
    passed: bool
    added_tools: list[str]
    added_employers: list[str]
    added_numerics: list[str]

def post_check(draft: str, polished: str, registry: set[str]) -> StoryPolishPostCheck:
    added_tools = sorted(tool_names_in_text(polished, registry)
                         - tool_names_in_text(draft, registry))
    added_emp = sorted(employer_names_in_text(polished)
                       - employer_names_in_text(draft))
    added_num = sorted(numeric_tokens_in_text(polished)
                       - numeric_tokens_in_text(draft))
    return StoryPolishPostCheck(
        passed=not (added_tools or added_emp or added_num),
        added_tools=added_tools,
        added_employers=added_emp,
        added_numerics=added_num,
    )
```

### 6.6 `prompts/story_polisher.md` content

```
# Story Polisher Instructions

Your task: rewrite the provided cover letter for flow, transitions, sentence
rhythm, and naturalness — WITHOUT introducing any new factual content.

## Hard prohibitions (factual integrity)

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
add it. The polish stage is purely textual. The pipeline runs a
deterministic post-check that will reject any polished version
introducing the above categories.

## What you SHOULD do

- Improve transitions between paragraphs (use connectives, repetition, theme)
- Improve sentence rhythm (vary length; break long compound sentences)
- Improve naturalness (replace stiff phrasing; choose ordinary words)
- Eliminate seams where the writer pivoted abruptly between requirements
- Preserve the opening's role-positioning intent
- Preserve every numeric metric in the draft (rewording is OK; deletion is NOT)
- Preserve every evidence-anchor sentence as a recognisable factual unit

## German over-analogy phrases — MUST avoid

Even if the draft contains them, REMOVE these phrases in the polished version:

- "direkt übertragbar"       (directly transferable)
- "direkt vergleichbar"      (directly comparable)
- "strukturell eng verwandt" (structurally closely related)
- "belastbares Analogon"     (robust analog)

These signal over-constructed transfer language and reduce credibility.

## AIDA restraint

When the writing mode is AIDA, the narrative_strategy.tone_guidance will say
"restrained AIDA". This means:

- No ALL-CAPS attention grabs in the opening
- No exclamation marks in the opening
- No second-person imperatives in the opening ("Imagine...", "PICTURE THIS:")
- No hyperbolic adjectives ("revolutionary", "world-class", "unparalleled")
- AIDA is a subtle narrative arc, not marketing copy

## Output

Return the full polished letter text in the `polished_text` field. The
schema is a single string field. Do not return commentary, diffs, or
explanations.
```

---

## 7. `hiring_review` extensions

### 7.1 Prompt change — `prompts/hiring_reviewer.md`

Existing reviewer prompt stays. ADD a new section "Craft dimensions (feature 013)":

```
## Craft dimensions (always-on)

You MUST evaluate the letter on six craft dimensions and report each as a
structured object with severity (pass/warn/error), rationale (≤ 240
chars), and an evidence_quote (verbatim from the letter) when severity is
warn or error.

The six dimensions:

1. **story_coherence** — Does the letter tell a single coherent story
   ladder-ing up to the narrative_strategy.bridge? warn if the letter
   reads as disconnected sections.

2. **transition_smoothness** — Do paragraph transitions flow naturally?
   warn if any transition is abrupt, defensive ("Although my background
   is..."), or jumps without setup.

3. **over_constructed_language** — Is any sentence over-engineered to
   bridge two domains? warn if phrasings sound contrived (forced
   analogies, formulaic "this maps to that" structure, German
   over-analogy phrases like "direkt übertragbar").

4. **claim_relevance** — Is every concrete claim load-bearing for THIS
   role family? warn if a claim is factually true but unrelated to the
   primary role family the letter is positioning for.

5. **aida_restraint** — When mode=aida and narrative_strategy.tone_guidance
   says "restrained AIDA", does the letter remain calm, senior, and
   institutional? warn on ALL-CAPS, opening exclamation marks, second-
   person imperatives, hyperbolic adjectives.

6. **human_readability** — Does the letter read as a human cover letter
   or as a mechanical requirement-by-requirement mapping? warn when each
   paragraph reads as a direct response to a single requirement bullet.

When severity is warn or error on any dimension, the aggregate verdict
MUST be at minimum `needs_minor_revision` for `aida_restraint` or
`transition_smoothness` specifically; for the other four, the LLM uses
its judgement.

Return the six dimensions as a `craft_dimensions` object on your
structured output.
```

### 7.2 Stage post-processing — deterministic over-analogy scan

After `parse_response` returns the parsed `HiringReviewOutput`:

```python
OVER_ANALOGY_PHRASES_DE = (
    "direkt übertragbar",
    "direkt vergleichbar",
    "strukturell eng verwandt",
    "belastbares Analogon",
)

def _scan_over_analogy_phrases(letter_text: str) -> list[DeterministicFinding]:
    findings: list[DeterministicFinding] = []
    lowered = letter_text.lower()
    for phrase in OVER_ANALOGY_PHRASES_DE:
        start = 0
        plower = phrase.lower()
        while True:
            idx = lowered.find(plower, start)
            if idx == -1:
                break
            ctx_start = max(0, idx - 40)
            ctx_end = min(len(letter_text), idx + len(phrase) + 40)
            findings.append(DeterministicFinding(
                check_id="over_analogy_phrase_de",
                severity="warn",
                phrase=phrase,
                char_start=idx,
                char_end=idx + len(phrase),
                context_snippet=letter_text[ctx_start:ctx_end],
            ))
            start = idx + len(phrase)
    return findings
```

Attach to review:

```python
deterministic = _scan_over_analogy_phrases(state.letter_draft.text)
review = review.model_copy(update={"deterministic_findings": deterministic})
```

### 7.3 Aggregate verdict escalation

```python
if (
    review.craft_dimensions.aida_restraint.severity in ("warn", "error")
    or review.craft_dimensions.transition_smoothness.severity in ("warn", "error")
):
    if review.verdict == "pass":
        review = review.model_copy(update={"verdict": "needs_minor_revision"})
```

---

## 8. Observability & Langfuse prompt sync

### 8.1 Per-stage spans (Langfuse)

- New `role_position` span (extracted)
- New `narrative_strategy` span
- New `story_polish` span with attributes: `post_check_passed` (bool), `used_fallback` (bool), `fallback_reason` (string when set), `diff_char_count` (int), `added_tools_count` (int), `added_employers_count` (int), `added_numerics_count` (int)
- Existing `hiring_review` span gains: per-dimension severities (`craft_dimensions.story_coherence.severity`, etc.) + `deterministic_findings_count` + `over_analogy_phrases_count`

### 8.2 MLflow tags

- New tags: `stage_role_position_status`, `stage_narrative_strategy_status`, `stage_story_polish_status`
- New tag: `story_polish_used_fallback` (true/false)
- New tag: `craft_<dimension_name>_severity` for each of the six dimensions

### 8.3 Prompt-registry sync

Files edited or added: `role_positioner.md`, `narrative_strategist.md`, `planner.md`, `writer.md`, `story_polisher.md`, `hiring_reviewer.md`, `styles/aida.md` = **7 prompt files**.

Expected `jobagent prompts sync` after the feature lands: **`7 created, 3 unchanged`** (the three unchanged: `requirements`, `system`, `tailor_cv`, `targeted_rewriter`, `validator`, `styles/standard`, `evidence-label` — exact count depends on current `STAGE_PROMPT_MAP`; verify at sync time, but the contract is "exactly seven prompts changed, the others did not").

---

## 9. Non-interference invariants

- Retrieval (`build_evidence_map`) unchanged — same prompt, same output, same span.
- Requirement extraction (`extract_requirements`) unchanged.
- Evidence-mapping artefact format unchanged.
- `RolePositioning` schema unchanged (just produced by a different stage).
- CV tailoring branch (`tailor_cv`) unchanged.
- Validation / rewrite-if-needed stages unchanged.
- CLI exit codes unchanged.
- Existing 266-test suite continues to pass; some plan_content tests need updates because the planner no longer produces role_positioning (those tests inject it on state instead). The updates are mechanical, not semantic.

---

## 10. Test surface (recap from research.md §R10)

| Behaviour | Test | File |
|---|---|---|
| NarrativeStrategy required fields | `test_narrative_strategy_schema_required_fields` | `tests/unit/test_narrative_strategy.py` |
| NarrativeStrategy max_length bounds | `test_narrative_strategy_schema_bounds` | same |
| NarrativeStrategy list element bounds | `test_narrative_strategy_list_bounds` | same |
| NarrativeStrategy extra="forbid" | `test_narrative_strategy_unknown_field_forbidden` | same |
| proof_points_to_use cross-check | `test_proof_points_must_trace_to_evidence_map` | same |
| Stage order in graph | `test_pipeline_includes_role_position_narrative_strategy_story_polish` | `tests/integration/test_full_run.py` (or new `tests/unit/test_workflow_graph.py`) |
| Planner consumes narrative_strategy block | `test_planner_prompt_includes_narrative_strategy_block` | `tests/unit/test_plan_content.py` |
| Planner drops paragraphs overlapping proof_points_to_avoid | `test_planner_drops_paragraphs_in_proof_points_to_avoid` | same |
| Writer prompt includes narrative_strategy block | `test_writer_prompt_includes_narrative_strategy_block` | `tests/unit/test_write_letter.py` |
| Writer opening reflects opening_angle | (covered by feature 011 regression guard, still passes) | same |
| Hiring review has six craft dimensions in prompt | `test_hiring_review_prompt_includes_six_craft_dimensions` | `tests/unit/test_hiring_review.py` |
| Hiring review parses all six craft dimensions | `test_hiring_review_parses_craft_dimensions` | same |
| story_polish post-check passes on subset | `test_story_polish_post_check_passes_on_subset` | `tests/unit/test_story_polish.py` |
| story_polish post-check fails on added tool | `test_story_polish_post_check_fails_on_added_tool` | same |
| story_polish post-check fails on added employer | `test_story_polish_post_check_fails_on_added_employer` | same |
| story_polish post-check fails on added numeric | `test_story_polish_post_check_fails_on_added_numeric` | same |
| story_polish fallback on LLM failure | `test_story_polish_falls_back_on_llm_failure` | same |
| story_polish fallback on post-check failure | `test_story_polish_falls_back_on_post_check_failure` | same |
| story_polish skipped when disabled | `test_story_polish_skipped_when_disabled` | same |
| Hiring review deterministic German over-analogy scan | `test_hiring_review_scans_over_analogy_phrases_de` | `tests/unit/test_hiring_review.py` |
| Tool extractor whole-word match | `test_tool_extractor_whole_word_match` | `tests/unit/test_extractors.py` |
| Tool extractor case-insensitive | `test_tool_extractor_case_insensitive` | same |
| Numeric extractor normalisation | `test_numeric_extractor_normalises_punctuation` | same |
| Employer extractor context prefix | `test_employer_extractor_after_at_bei` | same |
| role_position stage produces RolePositioning | `test_role_position_stage_produces_role_positioning` | `tests/unit/test_role_position.py` |
| role_position prompt build | `test_role_position_prompt_includes_job_description` | same |
| role_position parse_response | `test_role_position_parse_response_validates_schema` | same |

Total: ~26 new tests + small modifications to existing test files. Net: 266 → ~292.
