"""Unit tests for the validate stage (US4)."""

from __future__ import annotations

import hashlib
from typing import Any

from bewerbungs_agent.config.models import WritingMode
from bewerbungs_agent.models.state import (
    ContentPlan,
    EvidenceItem,
    EvidenceMap,
    LetterDraft,
    RuleStatus,
    SectionPlan,
    SoftSkill,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evidence_item(claim: str = "Led backend migration to Kubernetes") -> EvidenceItem:
    return EvidenceItem(
        claim=claim,
        source_type="cv_variant",
        source_file="cvs/cv_software.md",
        passage=claim,
    )


def _make_content_plan(
    soft_skills: list[SoftSkill] | None = None,
    mode: WritingMode = WritingMode.standard,
) -> ContentPlan:
    return ContentPlan(
        template_id="default_de_neutral",
        selected_cv_variant="cv_software",
        mode=mode,
        sections=[
            SectionPlan(
                title="role_fit",
                key_claims=["Led backend migration to Kubernetes"],
                evidence_refs=["Led backend migration to Kubernetes"],
            )
        ],
        selected_soft_skills=soft_skills or [],
        evidence_map=EvidenceMap(
            items=[_make_evidence_item()],
            known_gaps=[],
        ),
    )


def _plan_hash(plan: ContentPlan) -> str:
    return hashlib.sha256(plan.model_dump_json().encode()).hexdigest()


def _make_letter(
    text: str = "Sehr geehrte Damen und Herren,\n\nIch bin geeignet.\n",
    char_count: int | None = None,
    content_plan_hash: str = "",
    mode: WritingMode = WritingMode.standard,
) -> LetterDraft:
    return LetterDraft(
        text=text,
        char_count=char_count if char_count is not None else len(text),
        mode=mode,
        content_plan_hash=content_plan_hash,
    )


def _state_with(
    minimal_state: WorkflowState,
    letter: LetterDraft | None = None,
    content_plan: ContentPlan | None = None,
    config_overrides: dict | None = None,
) -> WorkflowState:
    updates: dict[str, Any] = {}
    if letter:
        updates["letter_draft"] = letter
    if content_plan:
        updates["content_plan"] = content_plan
    if config_overrides:
        new_config = minimal_state.config.model_copy(update=config_overrides)
        updates["config"] = new_config
    return minimal_state.model_copy(update=updates)


# ---------------------------------------------------------------------------
# Tests: source_compliance rule
# ---------------------------------------------------------------------------


class TestSourceCompliance:
    def test_matching_hash_passes(self, minimal_state: WorkflowState) -> None:
        """Letter with correct content_plan_hash → source_compliance passes."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        results = run_deterministic_rules(state, "letter")
        sc = next(r for r in results if r.rule == "source_compliance")
        assert sc.status == RuleStatus.pass_

    def test_mismatched_hash_fails(self, minimal_state: WorkflowState) -> None:
        """Letter with wrong content_plan_hash → source_compliance fails with detail."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash="deadbeef" * 8)
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        results = run_deterministic_rules(state, "letter")
        sc = next(r for r in results if r.rule == "source_compliance")
        assert sc.status == RuleStatus.fail
        assert sc.detail is not None

    def test_missing_hash_fails(self, minimal_state: WorkflowState) -> None:
        """Letter with no content_plan_hash (empty string) → source_compliance fails."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash="")
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        results = run_deterministic_rules(state, "letter")
        sc = next(r for r in results if r.rule == "source_compliance")
        assert sc.status == RuleStatus.fail


# ---------------------------------------------------------------------------
# Tests: length rule
# ---------------------------------------------------------------------------


class TestLengthRule:
    def test_normal_length_within_range_passes(self, minimal_state: WorkflowState) -> None:
        """Letter char_count within normal mode range → length passes."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        text = "x" * 2500  # within normal range (2000–3000)
        letter = _make_letter(text=text, char_count=2500, content_plan_hash=_plan_hash(plan))
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        results = run_deterministic_rules(state, "letter")
        length_r = next(r for r in results if r.rule == "length")
        assert length_r.status == RuleStatus.pass_

    def test_too_short_fails(self, minimal_state: WorkflowState) -> None:
        """Letter char_count below normal mode minimum → length fails."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        text = "x" * 100
        letter = _make_letter(text=text, char_count=100, content_plan_hash=_plan_hash(plan))
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        results = run_deterministic_rules(state, "letter")
        length_r = next(r for r in results if r.rule == "length")
        assert length_r.status == RuleStatus.fail
        assert length_r.detail is not None


# ---------------------------------------------------------------------------
# Tests: soft_skill_count rule
# ---------------------------------------------------------------------------


class TestSoftSkillCount:
    def test_exceeding_max_fails(self, minimal_state: WorkflowState) -> None:
        """ContentPlan with 4 soft skills and soft_skill_max=3 → fail."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        soft_skills = [
            SoftSkill(
                name=f"skill_{i}",
                behaviour="observed behaviour",
                evidence_item=_make_evidence_item(),
            )
            for i in range(4)
        ]
        plan = _make_content_plan(soft_skills=soft_skills)
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        state = _state_with(
            minimal_state,
            letter=letter,
            content_plan=plan,
            config_overrides={"soft_skill_max": 3},
        )

        results = run_deterministic_rules(state, "letter")
        ss_r = next(r for r in results if r.rule == "soft_skill_count")
        assert ss_r.status == RuleStatus.fail

    def test_within_max_passes(self, minimal_state: WorkflowState) -> None:
        """ContentPlan with 2 soft skills and soft_skill_max=3 → pass."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        soft_skills = [
            SoftSkill(
                name=f"skill_{i}",
                behaviour="observed",
                evidence_item=_make_evidence_item(),
            )
            for i in range(2)
        ]
        plan = _make_content_plan(soft_skills=soft_skills)
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        state = _state_with(
            minimal_state,
            letter=letter,
            content_plan=plan,
            config_overrides={"soft_skill_max": 3},
        )

        results = run_deterministic_rules(state, "letter")
        ss_r = next(r for r in results if r.rule == "soft_skill_count")
        assert ss_r.status == RuleStatus.pass_


# ---------------------------------------------------------------------------
# Tests: must_not_mention rule
# ---------------------------------------------------------------------------


class TestMustNotMention:
    def test_forbidden_term_in_letter_fails(self, minimal_state: WorkflowState) -> None:
        """Letter text containing a must_not_mention term → fail with excerpt."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        forbidden = "FORBIDDEN_COMPETITOR"
        text = f"Wir haben bei {forbidden} gelernt, wie man Software baut."
        letter = _make_letter(text=text, content_plan_hash=_plan_hash(plan))
        state = _state_with(
            minimal_state,
            letter=letter,
            content_plan=plan,
            config_overrides={"must_not_mention": [forbidden]},
        )

        results = run_deterministic_rules(state, "letter")
        mnm = next(r for r in results if r.rule == "must_not_mention")
        assert mnm.status == RuleStatus.fail
        assert forbidden in (mnm.detail or "")

    def test_no_forbidden_terms_passes(self, minimal_state: WorkflowState) -> None:
        """Letter with no must_not_mention terms → pass."""
        from bewerbungs_agent.stages.validate import run_deterministic_rules

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        state = _state_with(
            minimal_state,
            letter=letter,
            content_plan=plan,
            config_overrides={"must_not_mention": ["FORBIDDEN_COMPETITOR"]},
        )

        results = run_deterministic_rules(state, "letter")
        mnm = next(r for r in results if r.rule == "must_not_mention")
        assert mnm.status == RuleStatus.pass_


# ---------------------------------------------------------------------------
# Tests: validate_outputs node (full integration)
# ---------------------------------------------------------------------------


class TestValidateOutputsNode:
    def test_clean_draft_all_pass(self, minimal_state: WorkflowState) -> None:
        """A well-formed draft with correct hash and length → ValidationReport.passed=True."""
        from bewerbungs_agent.stages.validate import validate_outputs

        plan = _make_content_plan()
        text = "x" * 2500
        letter = _make_letter(
            text=text, char_count=2500, content_plan_hash=_plan_hash(plan)
        )
        state = _state_with(
            minimal_state,
            letter=letter,
            content_plan=plan,
            config_overrides={"must_not_mention": [], "soft_skill_max": 3},
        )

        result = validate_outputs(state)
        assert "letter_validation" in result
        assert result["letter_validation"].passed is True

    def test_bad_draft_produces_violations(self, minimal_state: WorkflowState) -> None:
        """A draft with wrong hash and too-short text → passed=False with violations."""
        from bewerbungs_agent.stages.validate import validate_outputs

        plan = _make_content_plan()
        text = "Too short."
        letter = _make_letter(text=text, char_count=len(text), content_plan_hash="wrong")
        state = _state_with(minimal_state, letter=letter, content_plan=plan)

        result = validate_outputs(state)
        report = result["letter_validation"]
        assert report.passed is False
        assert len(report.violations) >= 1
