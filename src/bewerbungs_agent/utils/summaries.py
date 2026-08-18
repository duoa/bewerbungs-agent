"""State → summary helpers used by the observability wrapper.

In summary mode (default), each summary function returns a small dict of
counts, lengths, IDs, hashes, and enum labels — never free text, never raw
profile/CV/job/letter content. This is the chokepoint that satisfies FR-018.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bewerbungs_agent.models.state import WorkflowState


# ---------------------------------------------------------------------------
# Per-state-field summary helpers
# ---------------------------------------------------------------------------


def summarise_job_context(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "has_company_file": value.raw_company_text is not None,
        "has_storyboard_file": value.raw_storyboard_text is not None,
        "job_title": value.job_title,
        "company_name": value.company_name,
        "raw_job_text_len": len(value.raw_job_text or ""),
    }


def summarise_requirements(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "core_present": bool(value.core_requirement),
        "technical_count": len(value.technical_requirements),
        "has_collaboration": value.collaboration_requirement is not None,
        "has_domain": value.domain_requirement is not None,
        "has_optional": value.optional_requirement is not None,
        "tone_signals_count": len(value.tone_signals),
        "must_include_count": len(value.must_include),
        "must_avoid_count": len(value.must_avoid),
    }


def summarise_knowledge(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "cv_variants_count": len(value.cv_variants),
        "project_docs_count": len(value.project_docs),
        "previous_letters_count": len(value.previous_letters),
        "personal_skills_len": len(value.personal_skills or ""),
        "master_profile_keys": sorted(list(value.master_profile.keys())) if value.master_profile else [],
    }


def summarise_selected_cv(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "variant_id": value.variant_id,
        "full_text_len": len(value.full_text or ""),
    }


def summarise_evidence_map(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    passage_total = sum(len(item.passage or "") for item in value.items)
    return {
        "items_count": len(value.items),
        "known_gaps_count": len(value.known_gaps),
        "assumptions_count": len(value.assumptions),
        "passage_total_len": passage_total,
    }


def summarise_content_plan(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "sections_count": len(value.sections),
        "selected_soft_skills_count": len(value.selected_soft_skills),
        "template_id": value.template_id,
        "mode": value.mode.value if hasattr(value.mode, "value") else str(value.mode),
        "selected_cv_variant": value.selected_cv_variant,
        # Feature 008: one-bit signal whether positioning was recorded.
        # Prose contents (primary_role_family etc.) intentionally NOT included
        # so feature 006's summary-mode privacy default is preserved.
        "role_positioning_present": getattr(value, "role_positioning", None) is not None,
    }


def summarise_letter_draft(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "char_count": value.char_count,
        "mode": value.mode.value if hasattr(value.mode, "value") else str(value.mode),
        "content_plan_hash": value.content_plan_hash,
    }


def summarise_cv_tailoring_plan(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "base_variant_id": value.base_variant_id,
        "changes_count": len(value.changes),
        "tailored_text_len": len(value.tailored_text or ""),
    }


def summarise_letter_review(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    weak_high = weak_medium = weak_low = 0
    for section in value.sections:
        for w in section.weaknesses:
            severity = w.severity.value if hasattr(w.severity, "value") else str(w.severity)
            if severity == "high":
                weak_high += 1
            elif severity == "medium":
                weak_medium += 1
            elif severity == "low":
                weak_low += 1
    return {
        "sections_count": len(value.sections),
        "sections_to_rewrite_count": len(value.sections_to_rewrite),
        "weakness_high_count": weak_high,
        "weakness_medium_count": weak_medium,
        "weakness_low_count": weak_low,
    }


def summarise_validation_report(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "target": value.target,
        "passed": value.passed,
        "violations": list(value.violations),
        "results_count": len(value.results),
    }


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------


# Maps the state attribute name → summary function.
_STATE_FIELD_SUMMARISERS: dict[str, Any] = {
    "job_context": summarise_job_context,
    "requirements": summarise_requirements,
    "knowledge": summarise_knowledge,
    "selected_cv": summarise_selected_cv,
    "evidence_map": summarise_evidence_map,
    "content_plan": summarise_content_plan,
    "letter_draft": summarise_letter_draft,
    "cv_tailoring_plan": summarise_cv_tailoring_plan,
    "letter_review": summarise_letter_review,
    "letter_validation": summarise_validation_report,
    "cv_validation": summarise_validation_report,
}


# Per-stage: which state fields it reads (used to build the input summary).
_STAGE_INPUT_FIELDS: dict[str, list[str]] = {
    "load_job": [],
    "extract_requirements": ["job_context"],
    "load_profile": [],
    "select_cv_variant": ["knowledge", "requirements"],
    "build_evidence_map": ["requirements", "selected_cv", "knowledge"],
    "plan_content": ["requirements", "evidence_map"],
    "write_letter": ["content_plan"],
    "tailor_cv": ["selected_cv", "requirements", "evidence_map"],
    "hiring_review": ["letter_draft", "requirements"],
    "targeted_rewrite": ["letter_draft", "letter_review", "requirements"],
    "validate_outputs": ["letter_draft", "content_plan"],
    "rewrite_if_needed": ["letter_draft", "letter_validation", "content_plan"],
}


def summarise_state_for_stage(
    stage_name: str,
    state: "WorkflowState",
    *,
    full: bool = False,
) -> dict[str, Any]:
    """Return either a summary of (or, in full mode, the raw view of) the
    state fields the named stage reads.
    """
    fields = _STAGE_INPUT_FIELDS.get(stage_name, [])
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(state, field, None)
        if value is None:
            continue
        if full:
            # In full mode, dump the typed model to a plain dict for transmission.
            try:
                result[field] = value.model_dump(mode="json")
            except Exception:  # noqa: BLE001
                result[field] = repr(value)
        else:
            summariser = _STATE_FIELD_SUMMARISERS.get(field)
            if summariser is not None:
                result[field] = summariser(value)
    return result


def summarise_partial_update(stage_name: str, update: dict[str, Any]) -> dict[str, Any]:
    """Summarise the partial-update dict returned by a stage."""
    result: dict[str, Any] = {}
    for key, value in update.items():
        if value is None:
            continue
        summariser = _STATE_FIELD_SUMMARISERS.get(key)
        if summariser is not None:
            result[key] = summariser(value)
        elif isinstance(value, (int, float, bool, str)):
            result[key] = value
        else:
            # Unknown shape: record only the type name and a length hint.
            length: int | None = None
            try:
                length = len(value)
            except TypeError:
                pass
            result[key] = {"type": type(value).__name__, "length": length}
    return result
