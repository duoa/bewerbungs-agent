"""Configuration models: StarterTemplate, RunInput, MergedConfig."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LengthMode(str, Enum):
    short = "short"    # 1200–1800 chars
    normal = "normal"  # 2000–3000 chars
    long = "long"      # 3200–4000 chars


class WritingMode(str, Enum):
    standard = "standard"
    aida = "aida"


class CVSelectionMode(str, Enum):
    automatic = "automatic"
    manual = "manual"


class ThinkingEffort(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ThinkingConfig(BaseModel):
    """Per-stage or global extended thinking configuration for Claude API calls."""

    enabled: bool = False
    effort: ThinkingEffort = ThinkingEffort.medium


class TrackingConfig(BaseModel):
    """MLflow tracking configuration. Opt-in; disabled by default."""

    enabled: bool = False
    tracking_uri: str = "mlruns"
    experiment_name: str = "bewerbungs-agent"


class LangfuseConfig(BaseModel):
    """Langfuse observability configuration.

    Read once at CLI start. Combined with presence of `LANGFUSE_PUBLIC_KEY` and
    `LANGFUSE_SECRET_KEY` env vars to decide active vs. no-op mode.
    """

    enabled: bool = False
    log_full_inputs: bool = False
    log_full_outputs: bool = False
    mask_pii: bool = True


class ObservabilityConfig(BaseModel):
    """Container for observability backends. Currently Langfuse only."""

    model_config = ConfigDict(extra="forbid")

    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)


class ReviewDimension(str, Enum):
    clarity = "clarity"
    specificity = "specificity"
    credibility = "credibility"
    role_relevance = "role_relevance"
    differentiation = "differentiation"


class WeaknessSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ReviewConfig(BaseModel):
    """Hiring-manager review and targeted-rewrite configuration."""

    enabled: bool = True
    dimensions: list[ReviewDimension] = Field(
        default_factory=lambda: list(ReviewDimension)
    )
    rewrite_threshold: WeaknessSeverity = WeaknessSeverity.medium


class WriterRules(BaseModel):
    """Per-template constraints on writer prose (feature 008).

    Enforced primarily by prompt instruction; the hiring-review stage catches
    violations and routes them through targeted_rewrite.
    """

    model_config = ConfigDict(extra="forbid")

    tool_density_max: int = Field(default=4, ge=1, le=20)
    banned_phrases: list[str] = Field(
        default_factory=lambda: [
            "expert-level",
            "deep expertise",
            "world-class",
            "guru",
            "rockstar",
            "10x",
            "ninja",
        ]
    )


class NarrativePolishConfig(BaseModel):
    """Per-template / per-run knobs for feature 013 (narrative_strategy + story_polish).

    All knobs default to "on" — the new stages are enabled out of the box.
    Operators can disable individual stages for cost control or to fall back to
    pre-feature-013 behaviour without removing the wiring.
    """

    model_config = ConfigDict(extra="forbid")

    narrative_strategy_enabled: bool = True
    story_polish_enabled: bool = True
    restrained_aida: bool = True
    tool_registry: list[str] | None = None


class StarterTemplate(BaseModel):
    """Persistent baseline configuration loaded from a YAML file."""

    template_id: str
    language: str = "DE"
    length: LengthMode = LengthMode.normal
    tone: str = "neutral-professionell"
    mode: WritingMode = WritingMode.standard
    cv_selection: CVSelectionMode = CVSelectionMode.automatic
    cv_tailoring: bool = True
    soft_skill_max: int = Field(default=3, ge=0, le=5)
    output_sections: list[str] = Field(
        default_factory=lambda: [
            "letter",
            "evidence_map",
            "known_gaps",
            "requirements",
            "content_draft",
            "validation",
        ]
    )
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    stage_thinking: dict[str, ThinkingConfig] = Field(default_factory=dict)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    review_config: ReviewConfig = Field(default_factory=ReviewConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    writer_rules: WriterRules = Field(default_factory=WriterRules)
    narrative_polish: NarrativePolishConfig = Field(default_factory=NarrativePolishConfig)


class RunInput(BaseModel):
    """Per-run inputs: job-specific values and optional overrides."""

    starter_template_id: str
    job_file: Path
    company_file: Path | None = None
    storyboard_file: Path | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    prioritized_projects: list[str] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)
    why_company: list[str] = Field(default_factory=list)
    cv_variant_override: str | None = None
    output_dir: Path = Path("outputs")


class MergedConfig(BaseModel):
    """Resolved configuration after applying RunInput.overrides on StarterTemplate.

    All pipeline stages read exclusively from this model.
    Merge precedence: starter_template < run_overrides.
    """

    model_config = ConfigDict(extra="forbid")

    template_id: str
    language: str
    length: LengthMode
    tone: str
    mode: WritingMode
    cv_selection: CVSelectionMode
    cv_tailoring: bool
    soft_skill_max: int = Field(ge=0, le=5)
    output_sections: list[str]
    validation_rules: dict[str, Any]
    # run-specific fields
    job_file: Path
    company_file: Path | None = None
    storyboard_file: Path | None = None
    prioritized_projects: list[str] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)
    why_company: list[str] = Field(default_factory=list)
    cv_variant_override: str | None = None
    output_dir: Path = Path("outputs")
    profile_dir: Path = Path("data")
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    stage_thinking: dict[str, ThinkingConfig] = Field(default_factory=dict)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    review_config: ReviewConfig = Field(default_factory=ReviewConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    writer_rules: WriterRules = Field(default_factory=WriterRules)
    narrative_polish: NarrativePolishConfig = Field(default_factory=NarrativePolishConfig)


def resolve_stage_thinking(config: MergedConfig, stage_name: str) -> ThinkingConfig:
    """Return the effective ThinkingConfig for a stage.

    Returns the per-stage override if present; otherwise the global default.
    """
    return config.stage_thinking.get(stage_name, config.thinking)
