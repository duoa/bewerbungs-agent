"""Unit tests for ThinkingConfig resolution, TrackingConfig, and ReviewConfig validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LangfuseConfig,
    LengthMode,
    MergedConfig,
    ObservabilityConfig,
    ReviewConfig,
    ReviewDimension,
    StarterTemplate,
    ThinkingConfig,
    ThinkingEffort,
    WeaknessSeverity,
    WriterRules,
    WritingMode,
    resolve_stage_thinking,
)


def _make_config(**overrides: object) -> MergedConfig:
    """Return a minimal valid MergedConfig with optional field overrides."""
    defaults: dict = {
        "template_id": "default_de_neutral",
        "language": "DE",
        "length": LengthMode.normal,
        "tone": "neutral-professionell",
        "mode": WritingMode.standard,
        "cv_selection": CVSelectionMode.automatic,
        "cv_tailoring": True,
        "soft_skill_max": 3,
        "output_sections": ["letter"],
        "validation_rules": {},
        "job_file": Path("data/examples/jobs/sample.md"),
        "output_dir": Path("outputs"),
    }
    defaults.update(overrides)
    return MergedConfig(**defaults)


class TestThinkingConfigResolution:
    def test_stage_override_takes_precedence(self) -> None:
        """Per-stage override is returned when present, ignoring global default."""
        config = _make_config(
            thinking=ThinkingConfig(enabled=False),
            stage_thinking={
                "plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high)
            },
        )
        result = resolve_stage_thinking(config, "plan_content")
        assert result.enabled is True
        assert result.effort == ThinkingEffort.high

    def test_global_default_when_no_override(self) -> None:
        """Global thinking config is returned when stage has no override."""
        config = _make_config(
            thinking=ThinkingConfig(enabled=False),
            stage_thinking={
                "plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high)
            },
        )
        result = resolve_stage_thinking(config, "write_letter")
        assert result.enabled is False

    def test_invalid_effort_raises_validation_error(self) -> None:
        """Invalid effort value raises ValidationError before any LLM call."""
        with pytest.raises(ValidationError) as exc_info:
            ThinkingConfig(enabled=True, effort="extreme")  # type: ignore[arg-type]
        assert "effort" in str(exc_info.value)

    def test_backward_compat_no_thinking_fields(self) -> None:
        """MergedConfig without thinking/stage_thinking/tracking uses safe defaults."""
        config = _make_config()
        assert config.thinking.enabled is False
        assert config.stage_thinking == {}
        assert config.tracking.enabled is False


class TestReviewConfig:
    def test_review_config_default_has_all_five_dimensions(self) -> None:
        """Default ReviewConfig includes all five evaluation dimensions."""
        cfg = ReviewConfig()
        assert set(cfg.dimensions) == set(ReviewDimension)
        assert len(cfg.dimensions) == 5

    def test_review_config_dimension_subset(self) -> None:
        """ReviewConfig accepts a subset of dimensions."""
        cfg = ReviewConfig(dimensions=[ReviewDimension.clarity, ReviewDimension.credibility])
        assert len(cfg.dimensions) == 2
        assert ReviewDimension.clarity in cfg.dimensions
        assert ReviewDimension.credibility in cfg.dimensions

    def test_review_config_default_threshold_is_medium(self) -> None:
        """Default rewrite threshold is medium."""
        cfg = ReviewConfig()
        assert cfg.rewrite_threshold == WeaknessSeverity.medium

    def test_review_config_flows_through_merge_config(self) -> None:
        """review_config from StarterTemplate survives merge_config round-trip."""
        from bewerbungs_agent.config.models import RunInput
        from bewerbungs_agent.utils.merge import merge_config

        template = StarterTemplate(
            template_id="test",
            review_config=ReviewConfig(rewrite_threshold=WeaknessSeverity.high),
        )
        run = RunInput(starter_template_id="test", job_file=Path("job.md"))
        merged = merge_config(template, run)
        assert merged.review_config.rewrite_threshold == WeaknessSeverity.high


class TestObservabilityConfig:
    def test_langfuse_config_defaults_are_conservative(self) -> None:
        """LangfuseConfig defaults: disabled, summary-only, PII masking on."""
        cfg = LangfuseConfig()
        assert cfg.enabled is False
        assert cfg.log_full_inputs is False
        assert cfg.log_full_outputs is False
        assert cfg.mask_pii is True

    def test_observability_config_default_holds_langfuse_subconfig(self) -> None:
        """ObservabilityConfig wraps a LangfuseConfig by default."""
        cfg = ObservabilityConfig()
        assert isinstance(cfg.langfuse, LangfuseConfig)
        assert cfg.langfuse.enabled is False

    def test_observability_config_forbids_unknown_keys(self) -> None:
        """Typos in YAML config raise rather than silently fall back."""
        with pytest.raises(ValidationError):
            ObservabilityConfig.model_validate({"langfues": {"enabled": True}})  # typo

    def test_observability_config_flows_through_merge_config(self) -> None:
        """observability from StarterTemplate survives merge_config round-trip."""
        from bewerbungs_agent.config.models import RunInput
        from bewerbungs_agent.utils.merge import merge_config

        template = StarterTemplate(
            template_id="test",
            observability=ObservabilityConfig(
                langfuse=LangfuseConfig(enabled=True, log_full_inputs=True, mask_pii=False)
            ),
        )
        run = RunInput(starter_template_id="test", job_file=Path("job.md"))
        merged = merge_config(template, run)
        assert merged.observability.langfuse.enabled is True
        assert merged.observability.langfuse.log_full_inputs is True
        assert merged.observability.langfuse.log_full_outputs is False
        assert merged.observability.langfuse.mask_pii is False


class TestWriterRules:
    """T013 — feature 008 WriterRules + per-template propagation."""

    def test_defaults_match_spec(self) -> None:
        rules = WriterRules()
        assert rules.tool_density_max == 4
        # Default ban list contains the 7 documented entries (FR-008).
        for phrase in (
            "expert-level", "deep expertise", "world-class",
            "guru", "rockstar", "10x", "ninja",
        ):
            assert phrase in rules.banned_phrases

    def test_tool_density_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            WriterRules(tool_density_max=0)
        with pytest.raises(ValidationError):
            WriterRules(tool_density_max=21)
        # Valid bounds work
        WriterRules(tool_density_max=1)
        WriterRules(tool_density_max=20)

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            WriterRules.model_validate({
                "tool_density_max": 4,
                "banned_phrases": [],
                "unknown_typo": True,
            })

    def test_writer_rules_flows_through_merge_config(self) -> None:
        """writer_rules from StarterTemplate survives merge_config round-trip."""
        from bewerbungs_agent.config.models import RunInput
        from bewerbungs_agent.utils.merge import merge_config

        template = StarterTemplate(
            template_id="test",
            writer_rules=WriterRules(
                tool_density_max=6,
                banned_phrases=["expert-level", "top-tier"],
            ),
        )
        run = RunInput(starter_template_id="test", job_file=Path("job.md"))
        merged = merge_config(template, run)
        assert merged.writer_rules.tool_density_max == 6
        assert merged.writer_rules.banned_phrases == ["expert-level", "top-tier"]


class TestNarrativePolishConfig:
    """Feature 013 — NarrativePolishConfig defaults + merge round-trip."""

    def test_narrative_polish_config_defaults(self) -> None:
        from bewerbungs_agent.config.models import NarrativePolishConfig

        cfg = NarrativePolishConfig()
        assert cfg.narrative_strategy_enabled is True
        assert cfg.story_polish_enabled is True
        assert cfg.restrained_aida is True
        assert cfg.tool_registry is None

    def test_narrative_polish_flows_through_merge_config(self) -> None:
        from bewerbungs_agent.config.models import NarrativePolishConfig, RunInput
        from bewerbungs_agent.utils.merge import merge_config

        template = StarterTemplate(
            template_id="t",
            narrative_polish=NarrativePolishConfig(
                story_polish_enabled=False,
                tool_registry=["Foo", "Bar"],
            ),
        )
        run = RunInput(starter_template_id="t", job_file=Path("job.md"))
        merged = merge_config(template, run)
        assert merged.narrative_polish.story_polish_enabled is False
        assert merged.narrative_polish.narrative_strategy_enabled is True
        assert merged.narrative_polish.tool_registry == ["Foo", "Bar"]

    def test_narrative_polish_extra_keys_forbidden(self) -> None:
        from bewerbungs_agent.config.models import NarrativePolishConfig

        with pytest.raises(ValidationError):
            NarrativePolishConfig.model_validate({
                "narrative_strategy_enabled": True,
                "unknown_typo": True,
            })
