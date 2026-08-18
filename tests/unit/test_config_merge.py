"""Unit tests for starter-template + run-override config merge (US3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LengthMode,
    RunInput,
    StarterTemplate,
    WritingMode,
)
from bewerbungs_agent.utils.merge import merge_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _template(**kwargs) -> StarterTemplate:
    defaults = dict(
        template_id="default_de_neutral",
        language="DE",
        length=LengthMode.normal,
        tone="neutral-professionell",
        mode=WritingMode.standard,
        cv_selection=CVSelectionMode.automatic,
        cv_tailoring=True,
        soft_skill_max=3,
        output_sections=["letter"],
        validation_rules={},
    )
    defaults.update(kwargs)
    return StarterTemplate.model_validate(defaults)


def _run(overrides: dict | None = None, job_file: Path | None = None) -> RunInput:
    return RunInput(
        starter_template_id="default_de_neutral",
        job_file=job_file or Path("job.md"),
        overrides=overrides or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMergeConfig:
    def test_override_language_wins(self) -> None:
        """Override language=EN must beat the template default language=DE."""
        template = _template(language="DE")
        run = _run(overrides={"language": "EN"})
        config = merge_config(template, run, profile_dir="data")
        assert config.language == "EN"

    def test_no_override_uses_template_value(self) -> None:
        """When no override is given, template value is preserved unchanged."""
        template = _template(language="DE", tone="warm-professionell")
        run = _run(overrides={})
        config = merge_config(template, run, profile_dir="data")
        assert config.language == "DE"
        assert config.tone == "warm-professionell"

    def test_soft_skill_max_override_propagates(self) -> None:
        """soft_skill_max from override must reach MergedConfig."""
        template = _template(soft_skill_max=3)
        run = _run(overrides={"soft_skill_max": 1})
        config = merge_config(template, run, profile_dir="data")
        assert config.soft_skill_max == 1

    def test_mode_override_to_aida(self) -> None:
        """Override mode=aida must produce WritingMode.aida in MergedConfig."""
        template = _template(mode=WritingMode.standard)
        run = _run(overrides={"mode": "aida"})
        config = merge_config(template, run, profile_dir="data")
        assert config.mode == WritingMode.aida

    def test_invalid_override_key_raises(self) -> None:
        """An override key not in MergedConfig schema must raise ValidationError."""
        template = _template()
        run = _run(overrides={"nonexistent_field": "value"})
        with pytest.raises(ValidationError):
            merge_config(template, run, profile_dir="data")

    def test_invalid_soft_skill_max_out_of_range_raises(self) -> None:
        """soft_skill_max=6 violates the ge=0, le=5 constraint."""
        template = _template()
        run = _run(overrides={"soft_skill_max": 6})
        with pytest.raises(ValidationError):
            merge_config(template, run, profile_dir="data")

    def test_profile_dir_set_from_argument(self) -> None:
        """profile_dir argument must be stored in MergedConfig.profile_dir."""
        template = _template()
        run = _run()
        config = merge_config(template, run, profile_dir="/custom/profile")
        assert config.profile_dir == Path("/custom/profile")

    def test_multiple_overrides_all_applied(self) -> None:
        """Multiple override keys must all win over their template defaults."""
        template = _template(language="DE", tone="neutral-professionell", soft_skill_max=3)
        run = _run(overrides={"language": "EN", "tone": "formal", "soft_skill_max": 2})
        config = merge_config(template, run, profile_dir="data")
        assert config.language == "EN"
        assert config.tone == "formal"
        assert config.soft_skill_max == 2
