"""Stage: validate — deterministic rule checks on letter and CV outputs."""

from __future__ import annotations

import hashlib
from typing import Any

from bewerbungs_agent.config.models import LengthMode
from bewerbungs_agent.models.state import (
    RuleStatus,
    ValidationReport,
    ValidationResult,
    WorkflowState,
)

# Character-count ranges per length mode
_LENGTH_RANGES: dict[LengthMode, tuple[int, int]] = {
    LengthMode.short: (1200, 1800),
    LengthMode.normal: (2000, 3000),
    LengthMode.long: (3200, 4000),
}


def _check_source_compliance(state: WorkflowState) -> ValidationResult:
    """Verify that the letter was generated from the current ContentPlan.

    Compares LetterDraft.content_plan_hash against a freshly computed hash of
    the current ContentPlan. A mismatch means the letter may have been written
    outside the evidence-grounded pipeline.
    """
    letter = state.letter_draft
    plan = state.content_plan

    if not letter:
        return ValidationResult(
            rule="source_compliance",
            status=RuleStatus.fail,
            detail="No letter draft available.",
        )

    if not plan:
        # Standalone validate (no pipeline context) — cannot check hash
        return ValidationResult(
            rule="source_compliance",
            status=RuleStatus.warning,
            detail="No content plan available; source compliance cannot be verified in standalone mode.",
        )

    expected = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
    actual = letter.content_plan_hash

    if not actual:
        return ValidationResult(
            rule="source_compliance",
            status=RuleStatus.fail,
            detail="content_plan_hash is missing — letter was not generated via the pipeline.",
        )

    if actual != expected:
        return ValidationResult(
            rule="source_compliance",
            status=RuleStatus.fail,
            detail=(
                f"content_plan_hash mismatch: letter hash '{actual[:12]}…' "
                f"≠ current plan hash '{expected[:12]}…'. "
                "Letter may have been generated from a stale or modified plan."
            ),
        )

    return ValidationResult(rule="source_compliance", status=RuleStatus.pass_)


def _check_length(state: WorkflowState) -> ValidationResult:
    """Verify the letter character count falls within the configured length range."""
    letter = state.letter_draft
    if not letter:
        return ValidationResult(
            rule="length",
            status=RuleStatus.fail,
            detail="No letter draft to check.",
        )

    length_mode = state.config.length
    lo, hi = _LENGTH_RANGES[length_mode]
    count = letter.char_count

    if count < lo or count > hi:
        return ValidationResult(
            rule="length",
            status=RuleStatus.fail,
            detail=(
                f"Letter is {count} chars; expected {lo}–{hi} for mode '{length_mode.value}'."
            ),
        )

    return ValidationResult(rule="length", status=RuleStatus.pass_)


def _check_soft_skill_count(state: WorkflowState) -> ValidationResult:
    """Verify the content plan does not exceed soft_skill_max."""
    plan = state.content_plan
    if not plan:
        return ValidationResult(rule="soft_skill_count", status=RuleStatus.pass_)

    count = len(plan.selected_soft_skills)
    max_allowed = state.config.soft_skill_max

    if count > max_allowed:
        return ValidationResult(
            rule="soft_skill_count",
            status=RuleStatus.fail,
            detail=(
                f"Content plan has {count} soft skills; "
                f"soft_skill_max is {max_allowed}."
            ),
        )

    return ValidationResult(rule="soft_skill_count", status=RuleStatus.pass_)


def _check_must_not_mention(state: WorkflowState) -> ValidationResult:
    """Check the letter for any terms listed in config.must_not_mention."""
    letter = state.letter_draft
    if not letter:
        return ValidationResult(rule="must_not_mention", status=RuleStatus.pass_)

    forbidden = state.config.must_not_mention
    text_lower = letter.text.lower()

    found = [term for term in forbidden if term.lower() in text_lower]
    if found:
        return ValidationResult(
            rule="must_not_mention",
            status=RuleStatus.fail,
            detail=f"Forbidden terms found in letter: {found}",
        )

    return ValidationResult(rule="must_not_mention", status=RuleStatus.pass_)


def run_deterministic_rules(
    state: WorkflowState, target: str
) -> list[ValidationResult]:
    """Run all deterministic validation rules for *target* ('letter' or 'cv').

    Returns a list of ValidationResult objects, one per rule.
    """
    if target == "letter":
        return [
            _check_source_compliance(state),
            _check_length(state),
            _check_soft_skill_count(state),
            _check_must_not_mention(state),
        ]
    # CV target: only must_not_mention applies for now
    return [_check_must_not_mention(state)]


def _build_report(results: list[ValidationResult], target: str) -> ValidationReport:
    violations = [r.rule for r in results if r.status == RuleStatus.fail]
    return ValidationReport(
        target=target,
        results=results,
        passed=len(violations) == 0,
        violations=violations,
    )


def validate_outputs(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node: run deterministic validation rules on letter and CV outputs."""
    letter_results = run_deterministic_rules(state, "letter")
    letter_report = _build_report(letter_results, "letter")

    cv_results = run_deterministic_rules(state, "cv")
    cv_report = _build_report(cv_results, "cv")

    return {
        "letter_validation": letter_report,
        "cv_validation": cv_report,
    }


# Alias used by the graph builder
validate = validate_outputs
