"""Starter-template + run-override merge logic.

Merge precedence: starter_template defaults < run_overrides.
"""

from __future__ import annotations

from typing import Any

from bewerbungs_agent.config.models import MergedConfig, RunInput, StarterTemplate


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overrides* on top of *base*.

    For nested dicts the merge recurses; for all other types the override value
    wins. Neither input dict is mutated.
    """
    result = dict(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_config(template: StarterTemplate, run: RunInput, profile_dir: str = "data") -> MergedConfig:
    """Produce a *MergedConfig* by applying *run.overrides* on top of *template*.

    Args:
        template:    Validated starter template (baseline defaults).
        run:         Per-run inputs including optional overrides dict.
        profile_dir: Root directory for user profile data.

    Returns:
        A fully validated *MergedConfig* instance.

    Raises:
        pydantic.ValidationError: If the merged result is invalid (e.g. an
            override supplies an unrecognised or type-mismatched key).
    """
    # IMPORTANT: every field on StarterTemplate that should flow into MergedConfig
    # MUST be listed explicitly below. Pydantic does not auto-propagate fields —
    # omitted fields silently fall back to MergedConfig defaults, bypassing
    # whatever the user configured in their template YAML.
    base: dict[str, Any] = {
        "template_id": template.template_id,
        "language": template.language,
        "length": template.length,
        "tone": template.tone,
        "mode": template.mode,
        "cv_selection": template.cv_selection,
        "cv_tailoring": template.cv_tailoring,
        "soft_skill_max": template.soft_skill_max,
        "output_sections": list(template.output_sections),
        "validation_rules": dict(template.validation_rules),
        "thinking": template.thinking,
        "stage_thinking": dict(template.stage_thinking),
        "tracking": template.tracking,
        "review_config": template.review_config,
        "observability": template.observability,
        "writer_rules": template.writer_rules,
        "narrative_polish": template.narrative_polish,
        # run-specific fields
        "job_file": run.job_file,
        "company_file": run.company_file,
        "storyboard_file": run.storyboard_file,
        "prioritized_projects": list(run.prioritized_projects),
        "must_not_mention": list(run.must_not_mention),
        "why_company": list(run.why_company),
        "cv_variant_override": run.cv_variant_override,
        "output_dir": run.output_dir,
        "profile_dir": profile_dir,
    }

    merged = _deep_merge(base, run.overrides)

    # Pydantic validation catches unknown keys (extra="forbid" must be set on
    # MergedConfig for this to raise; otherwise unknown keys are silently dropped).
    return MergedConfig.model_validate(merged)
