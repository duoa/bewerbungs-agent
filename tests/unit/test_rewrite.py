"""Unit tests for the rewrite stage (US4)."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from bewerbungs_agent.models.state import (
    ContentPlan,
    EvidenceItem,
    EvidenceMap,
    LetterDraft,
    RuleStatus,
    SectionPlan,
    ValidationReport,
    ValidationResult,
    WorkflowState,
    WritingMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_content_plan() -> ContentPlan:
    return ContentPlan(
        template_id="default_de_neutral",
        selected_cv_variant="cv_software",
        mode=WritingMode.standard,
        sections=[
            SectionPlan(
                title="role_fit",
                key_claims=["Kubernetes migration led by applicant"],
                evidence_refs=["Led migration to Kubernetes"],
            ),
        ],
        selected_soft_skills=[],
        evidence_map=EvidenceMap(
            items=[
                EvidenceItem(
                    claim="Led migration to Kubernetes",
                    source_type="cv_variant",
                    source_file="cvs/cv_software.md",
                    passage="Led migration to Kubernetes.",
                )
            ],
            known_gaps=[],
        ),
    )


def _plan_hash(plan: ContentPlan) -> str:
    return hashlib.sha256(plan.model_dump_json().encode()).hexdigest()


def _make_letter(
    text: str = "Sehr geehrte Damen,\n\nIch bin geeignet.\n",
    content_plan_hash: str = "",
) -> LetterDraft:
    t = text
    return LetterDraft(
        text=t,
        char_count=len(t),
        mode=WritingMode.standard,
        content_plan_hash=content_plan_hash,
    )


def _failed_report(rule: str = "length") -> ValidationReport:
    return ValidationReport(
        target="letter",
        results=[ValidationResult(rule=rule, status=RuleStatus.fail, detail="too short")],
        passed=False,
        violations=[rule],
    )


def _passed_report() -> ValidationReport:
    return ValidationReport(
        target="letter",
        results=[ValidationResult(rule="length", status=RuleStatus.pass_)],
        passed=True,
        violations=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRewriteIfNeeded:
    def test_rewrite_count_incremented(
        self, minimal_state: WorkflowState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each rewrite call must increment state.rewrite_count by 1."""
        from bewerbungs_agent.stages.rewrite import rewrite_if_needed

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        report = _failed_report("length")

        state = minimal_state.model_copy(
            update={
                "letter_draft": letter,
                "content_plan": plan,
                "letter_validation": report,
                "rewrite_count": 0,
            }
        )

        mock_client = MagicMock()
        mock_client.call.return_value = {
            "text": "x" * 2500,
            "mode": "standard",
        }
        monkeypatch.setattr(
            "bewerbungs_agent.stages.rewrite.get_llm_client", lambda: mock_client
        )

        result = rewrite_if_needed(state)
        assert result["rewrite_count"] == 1

    def test_max_rewrites_reached_skips_llm(
        self, minimal_state: WorkflowState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When rewrite_count >= max_rewrites, return state unchanged without LLM call."""
        from bewerbungs_agent.stages.rewrite import rewrite_if_needed

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        report = _failed_report("length")

        state = minimal_state.model_copy(
            update={
                "letter_draft": letter,
                "content_plan": plan,
                "letter_validation": report,
                "rewrite_count": 2,
                "max_rewrites": 2,
            }
        )

        mock_client = MagicMock()
        monkeypatch.setattr(
            "bewerbungs_agent.stages.rewrite.get_llm_client", lambda: mock_client
        )

        rewrite_if_needed(state)
        mock_client.call.assert_not_called()

    def test_prompt_contains_violation_detail(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must include violation details from the validation report."""
        from bewerbungs_agent.stages.rewrite import build_prompt

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        report = _failed_report("must_not_mention")
        report = report.model_copy(
            update={
                "results": [
                    ValidationResult(
                        rule="must_not_mention",
                        status=RuleStatus.fail,
                        detail="Term 'BadCorp' found",
                    )
                ]
            }
        )

        state = minimal_state.model_copy(
            update={
                "letter_draft": letter,
                "content_plan": plan,
                "letter_validation": report,
                "rewrite_count": 0,
            }
        )

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "must_not_mention" in content or "BadCorp" in content

    def test_prompt_contains_content_plan(
        self, minimal_state: WorkflowState
    ) -> None:
        """build_prompt must include ContentPlan JSON so the rewrite stays evidence-grounded."""
        from bewerbungs_agent.stages.rewrite import build_prompt

        plan = _make_content_plan()
        letter = _make_letter(content_plan_hash=_plan_hash(plan))
        report = _failed_report("length")

        state = minimal_state.model_copy(
            update={
                "letter_draft": letter,
                "content_plan": plan,
                "letter_validation": report,
                "rewrite_count": 0,
            }
        )

        messages = build_prompt(state)
        content = messages[0]["content"]
        assert "role_fit" in content or "Kubernetes" in content

    def test_no_letter_draft_returns_empty(
        self, minimal_state: WorkflowState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If no letter_draft in state, rewrite returns empty dict (no-op)."""
        from bewerbungs_agent.stages.rewrite import rewrite_if_needed

        state = minimal_state.model_copy(
            update={
                "letter_draft": None,
                "letter_validation": _failed_report(),
                "rewrite_count": 0,
            }
        )
        mock_client = MagicMock()
        monkeypatch.setattr(
            "bewerbungs_agent.stages.rewrite.get_llm_client", lambda: mock_client
        )

        result = rewrite_if_needed(state)
        assert result == {} or "letter_draft" not in result or result.get("letter_draft") is None
        mock_client.call.assert_not_called()
