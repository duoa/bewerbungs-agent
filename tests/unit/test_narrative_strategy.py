"""Unit tests for NarrativeStrategy schema + stage — feature 013 US1."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _valid_narrative_strategy_payload() -> dict:
    return {
        "candidate_story": "An engineer who built Python ML platforms.",
        "role_story": "The company wants a senior platform owner.",
        "bridge": "Candidate's systems thinking matches the role's reliability ask.",
        "opening_angle": "Lead with infrastructure-builder identity.",
        "proof_points_to_use": ["Built Python ML inference platform"],
        "proof_points_to_avoid": [],
        "transfer_framing_guidance": "",
        "tone_guidance": "Calm, senior, credible voice.",
        "anti_patterns": ["Do not open with 'Although my background is...'"],
    }


class TestNarrativeStrategySchema:
    """T009 – T012 — schema bounds and required fields."""

    def test_narrative_strategy_schema_required_fields(self) -> None:
        """T009 — FR-002 through FR-006, FR-010."""
        from bewerbungs_agent.models.state import NarrativeStrategy

        ns = NarrativeStrategy.model_validate(_valid_narrative_strategy_payload())
        assert isinstance(ns.candidate_story, str)
        assert isinstance(ns.role_story, str)
        assert isinstance(ns.bridge, str)
        assert isinstance(ns.opening_angle, str)
        assert isinstance(ns.proof_points_to_use, list)
        assert isinstance(ns.proof_points_to_avoid, list)
        assert isinstance(ns.tone_guidance, str)
        assert isinstance(ns.anti_patterns, list)

        # Required fields raise when missing
        for required in ("candidate_story", "role_story", "bridge", "opening_angle", "tone_guidance"):
            bad = _valid_narrative_strategy_payload()
            del bad[required]
            with pytest.raises(ValidationError):
                NarrativeStrategy.model_validate(bad)

    def test_narrative_strategy_schema_bounds(self) -> None:
        """T010 — German length rationale: 800/400/600 chars; min_length=1 enforced."""
        from bewerbungs_agent.models.state import NarrativeStrategy

        bad = _valid_narrative_strategy_payload()
        bad["candidate_story"] = "x" * 801
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

        bad = _valid_narrative_strategy_payload()
        bad["opening_angle"] = "x" * 401
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

        bad = _valid_narrative_strategy_payload()
        bad["tone_guidance"] = "x" * 601
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

        bad = _valid_narrative_strategy_payload()
        bad["candidate_story"] = ""
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

    def test_narrative_strategy_list_bounds(self) -> None:
        """T011 — list-length bounds + per-entry anti_pattern length."""
        from bewerbungs_agent.models.state import NarrativeStrategy

        for field in ("proof_points_to_use", "proof_points_to_avoid"):
            bad = _valid_narrative_strategy_payload()
            bad[field] = ["claim"] * 13
            with pytest.raises(ValidationError):
                NarrativeStrategy.model_validate(bad)

        bad = _valid_narrative_strategy_payload()
        bad["anti_patterns"] = ["p"] * 21
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

        bad = _valid_narrative_strategy_payload()
        bad["anti_patterns"] = ["x" * 241]
        with pytest.raises(ValidationError):
            NarrativeStrategy.model_validate(bad)

    def test_narrative_strategy_unknown_field_forbidden(self) -> None:
        """T012 — extra='forbid' rejects typo fields."""
        from bewerbungs_agent.models.state import NarrativeStrategy

        bad = _valid_narrative_strategy_payload()
        bad["candiate_story"] = "typo"  # misspelled
        with pytest.raises(ValidationError) as exc_info:
            NarrativeStrategy.model_validate(bad)
        assert "candiate_story" in str(exc_info.value)


class TestProofPointsCrossCheck:
    """T013 — stage-level proof_points cross-check against evidence_map."""

    def test_proof_points_must_trace_to_evidence_map(self) -> None:
        from bewerbungs_agent.models.state import EvidenceItem, EvidenceMap
        from bewerbungs_agent.stages.narrative_strategy import parse_response

        evidence_map = EvidenceMap(
            items=[
                EvidenceItem(
                    claim="X",
                    source_type="cv_variant",
                    source_file="cv.md",
                    passage="X",
                ),
            ]
        )

        payload = _valid_narrative_strategy_payload()
        payload["proof_points_to_use"] = ["X", "Y"]  # Y is not in evidence_map
        with pytest.raises(ValueError) as exc_info:
            parse_response(payload, evidence_map)
        assert "proof_points_to_use[1]" in str(exc_info.value)
        assert "'Y'" in str(exc_info.value) or '"Y"' in str(exc_info.value)

        # All claims trace → succeeds
        payload["proof_points_to_use"] = ["X"]
        ns = parse_response(payload, evidence_map)
        assert ns.proof_points_to_use == ["X"]
