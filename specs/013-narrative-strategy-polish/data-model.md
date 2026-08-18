# Data Model: Narrative Strategy & Story Polish

**Feature**: 013-narrative-strategy-polish
**Date**: 2026-06-05

Three new Pydantic models, one extended model, one extended config object. All under `src/bewerbungs_agent/models/state.py` except `NarrativePolishConfig` which lives in `src/bewerbungs_agent/config/models.py`.

---

## 1. `NarrativeStrategy` (NEW)

The story-strategy object produced by the new `narrative_strategy` stage.

```python
class NarrativeStrategy(BaseModel):
    """The hiring story this letter will tell — selected once before content planning."""

    model_config = ConfigDict(extra="forbid")

    candidate_story: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description="1–3 sentences: who the candidate is in this letter (the implicit narrative they bring).",
    )
    role_story: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description="1–3 sentences: what story the company is implicitly inviting candidates to tell.",
    )
    bridge: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description=(
            "1–3 sentences linking the candidate background to the target role. "
            "Load-bearing when the candidate is making a domain transition."
        ),
    )
    opening_angle: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description="Single short instruction for how to open the letter; consistent with the bridge.",
    )
    proof_points_to_use: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Evidence-claim text references to lean on. Each entry MUST trace to an existing "
            "evidence_map.items[*].claim (cross-checked at the stage level)."
        ),
    )
    proof_points_to_avoid: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Evidence-claim text references to deliberately leave out because they dilute the "
            "narrative. Each entry MUST trace to evidence_map.items[*].claim. Used by the planner "
            "as a hard filter (paragraphs overlapping these claims are dropped)."
        ),
    )
    transfer_framing_guidance: str = Field(
        default="",
        max_length=600,
        description=(
            "Concrete instructions for how to frame any domain transition naturally. "
            "MAY be an empty string when no transition needs framing."
        ),
    )
    tone_guidance: str = Field(
        ...,
        min_length=1,
        max_length=600,
        description=(
            "Tone instructions for the writer. When the configured writing mode is AIDA, "
            "MUST explicitly constrain the tone to a restrained, senior, credible register."
        ),
    )
    anti_patterns: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Short phrasings, openings, or moves the writer must avoid. Each entry ≤ 240 chars."
        ),
    )

    @field_validator("anti_patterns")
    @classmethod
    def _bound_each_anti_pattern(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > 240:
                raise ValueError(f"anti_patterns[{i}] exceeds 240 chars (got {len(s)})")
        return v
```

### Stage-level cross-checks (in `narrative_strategy.py::parse_response`)

These cannot live on the model because `EvidenceMap` is not on `NarrativeStrategy`:

```python
def parse_response(data, evidence_map: EvidenceMap) -> NarrativeStrategy:
    ns = NarrativeStrategy.model_validate(data)
    valid_claims = {item.claim for item in evidence_map.items}
    for i, c in enumerate(ns.proof_points_to_use):
        if valid_claims and c not in valid_claims:
            raise ValueError(
                f"proof_points_to_use[{i}] = {c!r} is not in evidence_map.items[*].claim"
            )
    for i, c in enumerate(ns.proof_points_to_avoid):
        if valid_claims and c not in valid_claims:
            raise ValueError(
                f"proof_points_to_avoid[{i}] = {c!r} is not in evidence_map.items[*].claim"
            )
    return ns
```

### Placement on `WorkflowState`

```python
class WorkflowState(BaseModel):
    # ... existing fields ...
    role_positioning: RolePositioning | None = None       # produced by new role_position stage
    narrative_strategy: NarrativeStrategy | None = None   # produced by new narrative_strategy stage
    story_polish_output: StoryPolishOutput | None = None  # produced by new story_polish stage
    # ... existing fields ...
```

---

## 2. `StoryPolishOutput` (NEW)

Wraps the polished letter and the deterministic post-check result.

```python
class StoryPolishOutput(BaseModel):
    """Output of the story_polish stage: polished prose + post-check audit trail."""

    model_config = ConfigDict(extra="forbid")

    polished_text: str = Field(
        ...,
        min_length=1,
        description="The polished letter text. Equals draft when used_fallback=True.",
    )
    post_check_passed: bool = Field(
        ...,
        description=(
            "True when polished_text introduced no new tool/employer/numeric token vs. draft. "
            "False when fallback was triggered for any reason."
        ),
    )
    post_check_rationale: str = Field(
        default="",
        max_length=600,
        description="Human-readable explanation of pass/fail.",
    )
    used_fallback: bool = Field(
        default=False,
        description=(
            "True when polished_text is actually the original draft (LLM failure, post-check "
            "failure, or stage disabled). False when polish succeeded and was accepted."
        ),
    )
    fallback_reason: str | None = Field(
        default=None,
        max_length=240,
        description="Short reason string when used_fallback=True; None otherwise.",
    )
    added_tools: list[str] = Field(
        default_factory=list,
        description="Tool names appearing in polished but not draft. Non-empty implies post-check failure.",
    )
    added_employers: list[str] = Field(
        default_factory=list,
        description="Employer names appearing in polished but not draft.",
    )
    added_numerics: list[str] = Field(
        default_factory=list,
        description="Normalised numeric tokens appearing in polished but not draft.",
    )
    diff_char_count: int = Field(
        default=0,
        ge=0,
        description="Absolute difference in character count between draft and polished_text.",
    )

    @model_validator(mode="after")
    def _consistency(self) -> "StoryPolishOutput":
        # When post_check_passed, no additions allowed
        if self.post_check_passed and (
            self.added_tools or self.added_employers or self.added_numerics
        ):
            raise ValueError(
                "post_check_passed=True but added_* lists are non-empty — invariant violation"
            )
        # When used_fallback, fallback_reason MUST be set
        if self.used_fallback and not self.fallback_reason:
            raise ValueError("used_fallback=True requires fallback_reason to be set")
        return self
```

Persisted at `outputs/<run_id>/artifacts/story_polish_output.json`.

---

## 3. `HiringReviewOutput` extensions (MODIFIED)

The existing structured output of `hiring_review` gains:

```python
class CraftDimension(BaseModel):
    """One craft-level dimension finding from the hiring reviewer."""

    model_config = ConfigDict(extra="forbid")

    severity: Literal["pass", "warn", "error"]
    rationale: str = Field(..., max_length=240)
    evidence_quote: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _evidence_required_when_warn_or_error(self) -> "CraftDimension":
        if self.severity in ("warn", "error") and not self.evidence_quote:
            raise ValueError(
                f"severity={self.severity!r} requires a non-empty evidence_quote"
            )
        return self


class CraftDimensions(BaseModel):
    """Six craft-level dimensions evaluated on every hiring review."""

    model_config = ConfigDict(extra="forbid")

    story_coherence: CraftDimension
    transition_smoothness: CraftDimension
    over_constructed_language: CraftDimension
    claim_relevance: CraftDimension
    aida_restraint: CraftDimension
    human_readability: CraftDimension


class DeterministicFinding(BaseModel):
    """Output of the deterministic over-analogy phrase scan (R8)."""

    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(..., min_length=1)   # e.g. "over_analogy_phrase_de"
    severity: Literal["warn"]                  # always warn for this scan
    phrase: str = Field(..., min_length=1, max_length=120)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    context_snippet: str = Field(..., max_length=240)


# Existing HiringReviewOutput gains:
#   craft_dimensions: CraftDimensions                  (required; produced by LLM)
#   deterministic_findings: list[DeterministicFinding] (default_factory=list; produced by stage post-processing)
```

### Aggregate verdict escalation

After parsing the LLM response, `hiring_review.parse_response` enforces:

```python
if (review.craft_dimensions.aida_restraint.severity in ("warn", "error")
    or review.craft_dimensions.transition_smoothness.severity in ("warn", "error")):
    if review.verdict == "pass":
        review = review.model_copy(update={"verdict": "needs_minor_revision"})
```

---

## 4. `NarrativePolishConfig` (NEW)

Lives in `src/bewerbungs_agent/config/models.py` alongside existing `WriterRules`.

```python
class NarrativePolishConfig(BaseModel):
    """Per-template / per-run knobs for feature 013."""

    model_config = ConfigDict(extra="forbid")

    narrative_strategy_enabled: bool = Field(
        default=True,
        description=(
            "When False, the narrative_strategy stage produces a deterministic minimal "
            "strategy from existing inputs instead of calling the LLM."
        ),
    )
    story_polish_enabled: bool = Field(
        default=True,
        description=(
            "When False, the story_polish stage is bypassed entirely; the hiring reviewer "
            "sees the writer's draft unchanged. No StoryPolishOutput artefact is written."
        ),
    )
    restrained_aida: bool = Field(
        default=True,
        description=(
            "When True (default), AIDA mode runs are constrained to the restrained, senior "
            "register described in feature 013 spec FR-032. Setting False reverts to the "
            "pre-feature-013 AIDA style (not recommended)."
        ),
    )
    tool_registry: list[str] | None = Field(
        default=None,
        description=(
            "Optional override of the built-in tool-name registry used by the story_polish "
            "post-check. None = use built-in seed (Python, Kafka, EKS, S3, ...)."
        ),
    )


# Existing MergedConfig (or TemplateConfig) gains:
#   narrative_polish: NarrativePolishConfig = Field(default_factory=NarrativePolishConfig)
```

---

## 5. `ContentPlan.role_positioning` becomes pass-through (MODIFIED behaviour, schema unchanged)

The Pydantic model `ContentPlan` is **unchanged in shape**: it still declares
`role_positioning: RolePositioning | None = None`. The behavioural change is
that this field is now populated by the upstream `role_position` stage (passed
through `plan_content` from `state.role_positioning`) instead of being produced
by the planner LLM. Legacy artefacts that have `role_positioning` populated
inside their ContentPlan JSON continue to load identically.

The `plan_content` stage explicitly copies `state.role_positioning` into the
returned `ContentPlan` after the planner LLM call, so consumers (`write_letter._format_positioning_block`,
hiring-review's content-plan summary) need no changes.

---

## 6. Backward-compat audit

| Legacy artefact | Behaviour |
|---|---|
| `WorkflowState` with no `narrative_strategy` field | Loads cleanly; field defaults to `None`. Downstream stages handle `None` by computing a minimal fallback (matches R6 fallback path). |
| `WorkflowState` with no `story_polish_output` field | Loads cleanly; field defaults to `None`. Hiring reviewer reads `letter_draft.text` unchanged. |
| Pre-feature-013 `ContentPlan` JSON with `role_positioning` populated by LLM | Loads identically (shape unchanged). The pass-through behaviour only matters for the *runtime flow*, not for replay. |
| Pre-feature-013 `HiringReviewOutput` JSON without `craft_dimensions` / `deterministic_findings` | Adding required `craft_dimensions` is a breaking change for legacy artefacts. Mitigation: `craft_dimensions: CraftDimensions \| None = None` instead of required, with a stage-level post-check that raises if `None` is returned by the LLM (so live runs always produce it; legacy replay tolerates absence). Tracked in contracts §4. |
| Templates without `narrative_polish` config block | `MergedConfig.narrative_polish` defaults to `NarrativePolishConfig()` (all features enabled). |
