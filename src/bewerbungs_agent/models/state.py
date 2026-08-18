"""Pipeline state models: all typed containers that flow between LangGraph stages."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bewerbungs_agent.config.models import MergedConfig, WeaknessSeverity, WritingMode

# ---------------------------------------------------------------------------
# Feature 010 — enums shared by RequirementItem
# ---------------------------------------------------------------------------


class Priority(str, Enum):
    """Per-requirement weighting introduced by feature 010."""

    high = "high"
    medium = "medium"
    low = "low"


class RequirementCategory(str, Enum):
    """Per-requirement category. Values mirror the existing `Requirement.label`
    convention so the back-fill validator can map enum → label cleanly.
    """

    core = "core"
    technical = "technical"
    collaboration = "collaboration"
    domain = "domain"
    optional = "optional"


class EvidenceNeeded(str, Enum):
    """Strength of evidence the writer should anchor for each requirement."""

    required = "required"
    preferred = "preferred"
    optional = "optional"

# ---------------------------------------------------------------------------
# Job context
# ---------------------------------------------------------------------------


class JobContext(BaseModel):
    """Normalised content loaded from the job description and optional files."""

    raw_job_text: str
    job_title: str | None = None
    company_name: str | None = None
    raw_company_text: str | None = None
    raw_storyboard_text: str | None = None


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------


class Requirement(BaseModel):
    """A single extracted job requirement (legacy shape; pre-feature-010).

    Kept for backward compatibility. The richer `RequirementItem` below is the
    canonical structure as of feature 010; a model validator on
    `RequirementExtraction` back-fills `all_requirements` from
    `requirement_items` so downstream consumers reading the legacy list
    continue to see populated data.
    """

    label: str  # "core" | "technical" | "collaboration" | "domain" | "optional"
    text: str
    priority: int  # 1 = highest


class RequirementItem(BaseModel):
    """A weighted, individually-addressable extracted requirement.

    Feature 010 replacement for the thin `Requirement` model.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=16)
    text: str = Field(..., min_length=1)
    priority: Priority
    category: RequirementCategory
    evidence_needed: EvidenceNeeded
    source_excerpt: str | None = Field(default=None, max_length=200)


# Priority → legacy int mapping used by the back-fill validator below.
_PRIORITY_TO_INT: dict[Priority, int] = {
    Priority.high: 1,
    Priority.medium: 2,
    Priority.low: 3,
}


class RequirementExtraction(BaseModel):
    """Structured output of the extract_requirements stage."""

    model_config = ConfigDict(extra="forbid")

    core_requirement: str
    technical_requirements: list[str] = Field(default_factory=list)  # max 2
    collaboration_requirement: str | None = None
    domain_requirement: str | None = None
    optional_requirement: str | None = None
    tone_signals: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    all_requirements: list[Requirement] = Field(default_factory=list)
    # Feature 010: weighted, individually-addressable requirement list.
    requirement_items: list[RequirementItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_unique_item_ids(self) -> "RequirementExtraction":
        seen: set[str] = set()
        for item in self.requirement_items:
            if item.id in seen:
                raise ValueError(
                    f"Duplicate RequirementItem id: {item.id!r} appears more than once"
                )
            seen.add(item.id)
        return self

    @model_validator(mode="after")
    def _backfill_all_requirements_from_items(self) -> "RequirementExtraction":
        """Populate legacy ``all_requirements`` from ``requirement_items``.

        Lets downstream consumers reading ``all_requirements`` keep working
        after the extractor switches to producing ``requirement_items``.
        Back-fill only runs when the legacy list is empty — preserves any
        explicitly-provided legacy data.
        """
        if self.requirement_items and not self.all_requirements:
            self.all_requirements = [
                Requirement(
                    label=item.category.value,
                    text=item.text,
                    priority=_PRIORITY_TO_INT[item.priority],
                )
                for item in self.requirement_items
            ]
        return self


# ---------------------------------------------------------------------------
# Internal knowledge
# ---------------------------------------------------------------------------


class CVVariantMetadata(BaseModel):
    """Metadata for one CV variant, loaded from data/cvs/metadata/*.json."""

    variant_id: str
    file_path: Path
    role_families: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    summary: str = ""


class InternalKnowledge(BaseModel):
    """All approved internal documents loaded for a run."""

    master_profile: dict[str, Any]
    cv_variants: list[CVVariantMetadata] = Field(default_factory=list)
    personal_skills: str = ""
    project_docs: dict[str, str] = Field(default_factory=dict)  # filename → text
    previous_letters: dict[str, str] = Field(default_factory=dict)  # filename → text


# ---------------------------------------------------------------------------
# CV selection
# ---------------------------------------------------------------------------


class SelectedCV(BaseModel):
    """Result of the select_cv_variant stage."""

    variant_id: str
    metadata: CVVariantMetadata
    full_text: str
    selection_reason: str = ""


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single claim → approved-source mapping."""

    claim: str
    source_type: str  # "master_profile" | "cv_variant" | "personal_skills" | ...
    source_file: str  # relative path within data/
    passage: str      # verbatim excerpt — required non-empty after build_evidence_map
    relevance_note: str = ""  # one-sentence explanation of why this passage supports the claim


class EvidenceMap(BaseModel):
    """Complete mapping of selected claims to approved sources."""

    items: list[EvidenceItem] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Content planning
# ---------------------------------------------------------------------------


class SoftSkill(BaseModel):
    """A selected soft skill with evidence backing."""

    name: str
    behaviour: str      # observable behaviour or outcome — not a bare adjective
    evidence_item: EvidenceItem


class SectionPlan(BaseModel):
    """One planned section of the cover letter."""

    title: str          # "role_fit" | "relevant_experience" | "working_style" | ...
    key_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)       # claim texts
    anchor_passages: list[str] = Field(default_factory=list)     # verbatim passages for this section
    soft_skills: list[str] = Field(default_factory=list)


class RolePositioning(BaseModel):
    """Planner's explicit decision about how to frame the cover letter.

    Derived primarily from the job description text + extracted requirements
    (NOT from whichever candidate evidence happens to be strongest).
    Consumed by the writer to shape the opening and paragraph order; consumed
    by the hiring review to evaluate role-match / opening-alignment / etc.

    Field names normalised by feature 010. Feature-008-shape JSON loads via
    Pydantic field aliases (``populate_by_name=True``):
      - ``primary_role_family`` → ``role_family``
      - ``topics_to_emphasise`` → ``emphasise``
      - ``topics_to_deemphasise`` → ``deemphasise``
    The new ``risky_or_gap_areas`` field defaults to ``[]`` so legacy
    artifacts load cleanly.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    role_family: str = Field(..., alias="primary_role_family")
    primary_selling_point: str
    secondary_selling_points: list[str] = Field(default_factory=list)
    opening_angle: str
    emphasise: list[str] = Field(
        default_factory=list, alias="topics_to_emphasise"
    )
    deemphasise: list[str] = Field(
        default_factory=list, alias="topics_to_deemphasise"
    )
    # Feature 010 — topics the writer should treat carefully or avoid because
    # the candidate has no strong evidence (or alignment is weak in a way that
    # could backfire if leaned on).
    risky_or_gap_areas: list[str] = Field(default_factory=list)


class ParagraphPlan(BaseModel):
    """One planned paragraph of the cover letter (feature 011).

    Replacement for the thinner SectionPlan when the planner emits the new
    hiring-story structure. Lives ALONGSIDE SectionPlan for backward
    compatibility — legacy ContentPlan artifacts continue to use ``sections``.

    Required fields force the planner to think per-paragraph: ``max_claims``
    and ``max_tools`` are not defaulted because the appropriate density
    depends on the paragraph's purpose (an opening uses 1, a credibility
    paragraph may use 4).
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(..., min_length=1)
    main_message: str = Field(..., min_length=1, max_length=400)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    emphasise: list[str] = Field(default_factory=list)
    deemphasise: list[str] = Field(default_factory=list)
    max_claims: int = Field(..., ge=1, le=8)
    max_tools: int = Field(..., ge=0, le=12)


class ContentPlan(BaseModel):
    """Structured plan produced before any prose is generated."""

    model_config = ConfigDict(extra="forbid")

    template_id: str
    selected_cv_variant: str
    mode: WritingMode
    sections: list[SectionPlan] = Field(default_factory=list)
    selected_soft_skills: list[SoftSkill] = Field(default_factory=list)
    evidence_map: EvidenceMap = Field(default_factory=EvidenceMap)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    role_positioning: RolePositioning | None = None
    # Feature 011 — hiring-story structure
    letter_thesis: str | None = Field(default=None, max_length=400)
    paragraphs: list[ParagraphPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_refs_within_max_claims(self) -> "ContentPlan":
        for i, p in enumerate(self.paragraphs):
            if len(p.evidence_refs) > p.max_claims:
                raise ValueError(
                    f"Paragraph {i} ({p.purpose!r}) lists {len(p.evidence_refs)} "
                    f"evidence_refs but max_claims is {p.max_claims}; the plan "
                    f"cannot promise more claims than the paragraph allows."
                )
        return self

    @model_validator(mode="after")
    def _validate_opening_paragraph_max_claims(self) -> "ContentPlan":
        if self.paragraphs:
            opening = self.paragraphs[0]
            if opening.max_claims not in (1, 2):
                raise ValueError(
                    f"Opening paragraph (index 0, purpose={opening.purpose!r}) "
                    f"has max_claims={opening.max_claims}; opening paragraphs "
                    f"must use 1 or 2 claims to keep the opening tight."
                )
        return self

    @model_validator(mode="after")
    def _validate_paragraph_evidence_refs_in_evidence_map(self) -> "ContentPlan":
        if not self.paragraphs:
            return self
        valid_claims = {item.claim for item in self.evidence_map.items}
        if not valid_claims:
            return self
        for i, p in enumerate(self.paragraphs):
            for claim in p.evidence_refs:
                bare = claim.split(" [source:")[0].strip()
                if bare not in valid_claims:
                    raise ValueError(
                        f"Paragraph {i} ({p.purpose!r}) references claim "
                        f"{bare!r} which is not in the evidence map."
                    )
        return self


# ---------------------------------------------------------------------------
# Letter and CV outputs
# ---------------------------------------------------------------------------


class LetterDraft(BaseModel):
    """The generated cover letter prose."""

    text: str
    char_count: int
    mode: WritingMode
    content_plan_hash: str = ""  # SHA-256 of the ContentPlan used


class CVTailoringChange(BaseModel):
    """One targeted change to the base CV variant."""

    section: str
    action: str  # "emphasise" | "reorder" | "include" | "exclude"
    rationale: str
    evidence_ref: str | None = None


class CVTailoringPlan(BaseModel):
    """Instructions and result of adapting the selected CV variant."""

    base_variant_id: str
    changes: list[CVTailoringChange] = Field(default_factory=list)
    tailored_text: str = ""


# ---------------------------------------------------------------------------
# Hiring-manager review
# ---------------------------------------------------------------------------


class WeaknessEntry(BaseModel):
    """One identified weakness within a reviewed letter section."""

    text: str
    severity: WeaknessSeverity
    priority_fix: str


class SectionReview(BaseModel):
    """Assessment of one named section of the cover letter."""

    section_name: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[WeaknessEntry] = Field(default_factory=list)
    assessment: str = ""


class CraftDimension(BaseModel):
    """One craft-level dimension finding from the hiring reviewer (feature 013 US3)."""

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
    """Six craft-level dimensions evaluated on every hiring review (feature 013 US3)."""

    model_config = ConfigDict(extra="forbid")

    story_coherence: CraftDimension
    transition_smoothness: CraftDimension
    over_constructed_language: CraftDimension
    claim_relevance: CraftDimension
    aida_restraint: CraftDimension
    human_readability: CraftDimension


class DeterministicFinding(BaseModel):
    """Output of the deterministic over-analogy phrase scan (feature 013 US3)."""

    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(..., min_length=1)
    severity: Literal["warn"]
    phrase: str = Field(..., min_length=1, max_length=120)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    context_snippet: str = Field(..., max_length=240)


class LetterReviewReport(BaseModel):
    """Full structured output of the hiring_review stage."""

    sections: list[SectionReview] = Field(default_factory=list)
    overall_assessment: str = ""
    sections_to_rewrite: list[str] = Field(default_factory=list)
    # ^ pre-computed by hiring_review stage based on configured rewrite_threshold
    # Feature 013 US3 — craft dimensions + deterministic findings + verdict.
    # `craft_dimensions` is optional for backward-compat with legacy artefact
    # replay; live runs always populate it (stage-level enforcement).
    craft_dimensions: CraftDimensions | None = None
    deterministic_findings: list[DeterministicFinding] = Field(default_factory=list)
    verdict: Literal["pass", "needs_minor_revision", "needs_major_revision"] = "pass"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class RuleStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    warning = "warning"


class ValidationResult(BaseModel):
    """Result for a single validation rule."""

    rule: str
    status: RuleStatus
    detail: str | None = None  # offending excerpt or message on failure


class ValidationReport(BaseModel):
    """Aggregate validation report across all rules for one output."""

    target: str  # "letter" | "cv"
    results: list[ValidationResult] = Field(default_factory=list)
    passed: bool = True
    violations: list[str] = Field(default_factory=list)  # rule names that failed


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------


class NarrativeStrategy(BaseModel):
    """The hiring story this letter will tell — selected once before content planning.

    Feature 013. Bounds are generous to accommodate German compound nouns
    (lesson learned from feature 011's main_message length bump).
    """

    model_config = ConfigDict(extra="forbid")

    candidate_story: str = Field(..., min_length=1, max_length=800)
    role_story: str = Field(..., min_length=1, max_length=800)
    bridge: str = Field(..., min_length=1, max_length=800)
    opening_angle: str = Field(..., min_length=1, max_length=400)
    proof_points_to_use: list[str] = Field(default_factory=list, max_length=12)
    proof_points_to_avoid: list[str] = Field(default_factory=list, max_length=12)
    transfer_framing_guidance: str = Field(default="", max_length=600)
    tone_guidance: str = Field(..., min_length=1, max_length=600)
    anti_patterns: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("anti_patterns")
    @classmethod
    def _bound_each_anti_pattern(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > 240:
                raise ValueError(
                    f"anti_patterns[{i}] exceeds 240 chars (got {len(s)})"
                )
        return v


class StoryPolishOutput(BaseModel):
    """Output of the story_polish stage: polished prose + post-check audit trail.

    Feature 013 US2. The deterministic post-check is the load-bearing
    correctness contract — see utils/extractors.py for the extractors.
    """

    model_config = ConfigDict(extra="forbid")

    polished_text: str = Field(..., min_length=1)
    post_check_passed: bool
    post_check_rationale: str = Field(default="", max_length=600)
    used_fallback: bool = False
    fallback_reason: str | None = Field(default=None, max_length=240)
    added_tools: list[str] = Field(default_factory=list)
    added_employers: list[str] = Field(default_factory=list)
    added_numerics: list[str] = Field(default_factory=list)
    diff_char_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistency(self) -> "StoryPolishOutput":
        if self.post_check_passed and (
            self.added_tools or self.added_employers or self.added_numerics
        ):
            raise ValueError(
                "post_check_passed=True but added_* lists are non-empty — "
                "invariant violation"
            )
        if self.used_fallback and not self.fallback_reason:
            raise ValueError(
                "used_fallback=True requires fallback_reason to be set"
            )
        return self


class WorkflowState(BaseModel):
    """Typed container accumulated and threaded through all LangGraph nodes.

    Every field is None until the corresponding stage populates it.
    LangGraph receives partial dict updates; missing keys keep their defaults.
    """

    config: MergedConfig
    job_context: JobContext | None = None
    requirements: RequirementExtraction | None = None
    knowledge: InternalKnowledge | None = None
    selected_cv: SelectedCV | None = None
    evidence_map: EvidenceMap | None = None
    # Feature 013: role_positioning is produced by the dedicated role_position
    # stage upstream of plan_content; plan_content reads it from state and
    # pass-throughs it onto the ContentPlan.role_positioning field.
    role_positioning: "RolePositioning | None" = None
    narrative_strategy: "NarrativeStrategy | None" = None
    content_plan: ContentPlan | None = None
    letter_draft: LetterDraft | None = None
    story_polish_output: "StoryPolishOutput | None" = None
    cv_tailoring_plan: CVTailoringPlan | None = None
    letter_review: LetterReviewReport | None = None
    letter_validation: ValidationReport | None = None
    cv_validation: ValidationReport | None = None
    rewrite_count: int = 0
    max_rewrites: int = 2
    run_id: str = ""
    tracker: Any | None = Field(default=None, exclude=True)
    observability: Any | None = Field(default=None, exclude=True)
