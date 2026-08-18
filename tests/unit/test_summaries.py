"""Unit tests for state→summary functions.

User Story 2 (P2): each summary function returns the documented fields and
contains NO free-text body content (FR-018 default-mode invariant).
"""

from __future__ import annotations

from pathlib import Path

from bewerbungs_agent.config.models import WeaknessSeverity, WritingMode
from bewerbungs_agent.models.state import (
    ContentPlan,
    CVTailoringChange,
    CVTailoringPlan,
    CVVariantMetadata,
    EvidenceItem,
    EvidenceMap,
    InternalKnowledge,
    JobContext,
    LetterDraft,
    LetterReviewReport,
    RequirementExtraction,
    RuleStatus,
    SectionPlan,
    SectionReview,
    SelectedCV,
    ValidationReport,
    ValidationResult,
    WeaknessEntry,
)
from bewerbungs_agent.utils.summaries import (
    summarise_content_plan,
    summarise_cv_tailoring_plan,
    summarise_evidence_map,
    summarise_job_context,
    summarise_knowledge,
    summarise_letter_draft,
    summarise_letter_review,
    summarise_partial_update,
    summarise_requirements,
    summarise_selected_cv,
    summarise_state_for_stage,
    summarise_validation_report,
)

# Sentinel string we'll plant in raw-text fields and assert is NEVER present
# anywhere in a summary's output (FR-018 default mode).
SENTINEL = "THIS_IS_RAW_PROSE_THAT_MUST_NEVER_LEAK"


def _contains_sentinel(value: object) -> bool:
    if isinstance(value, str):
        return SENTINEL in value
    if isinstance(value, dict):
        return any(_contains_sentinel(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_sentinel(v) for v in value)
    return False


class TestSummariseJobContext:
    def test_returns_counts_only(self) -> None:
        ctx = JobContext(
            raw_job_text=SENTINEL * 100,
            job_title="Data Engineer",
            company_name="Acme",
            raw_company_text=SENTINEL,
        )
        out = summarise_job_context(ctx)
        assert out["job_title"] == "Data Engineer"
        assert out["company_name"] == "Acme"
        assert out["has_company_file"] is True
        assert out["has_storyboard_file"] is False
        assert out["raw_job_text_len"] == len(SENTINEL) * 100
        assert not _contains_sentinel(out)


class TestSummariseRequirements:
    def test_returns_counts_only(self) -> None:
        reqs = RequirementExtraction(
            core_requirement=SENTINEL,
            technical_requirements=[SENTINEL, SENTINEL + "x"],
            collaboration_requirement=SENTINEL,
            must_include=[SENTINEL],
            must_avoid=[SENTINEL, SENTINEL],
        )
        out = summarise_requirements(reqs)
        assert out["core_present"] is True
        assert out["technical_count"] == 2
        assert out["has_collaboration"] is True
        assert out["has_domain"] is False
        assert out["must_include_count"] == 1
        assert out["must_avoid_count"] == 2
        assert not _contains_sentinel(out)


class TestSummariseKnowledge:
    def test_returns_counts_only(self) -> None:
        knowledge = InternalKnowledge(
            master_profile={"name": SENTINEL, "title": SENTINEL},
            cv_variants=[
                CVVariantMetadata(variant_id="cv_x", file_path=Path("cv_x.md")),
                CVVariantMetadata(variant_id="cv_y", file_path=Path("cv_y.md")),
            ],
            personal_skills=SENTINEL * 50,
            project_docs={"p1.md": SENTINEL, "p2.md": SENTINEL},
            previous_letters={"l1.md": SENTINEL},
        )
        out = summarise_knowledge(knowledge)
        assert out["cv_variants_count"] == 2
        assert out["project_docs_count"] == 2
        assert out["previous_letters_count"] == 1
        assert out["personal_skills_len"] == len(SENTINEL) * 50
        # Keys (not values) of master_profile are recorded for debugging.
        assert "name" in out["master_profile_keys"]
        assert "title" in out["master_profile_keys"]
        assert not _contains_sentinel(out)


class TestSummariseSelectedCV:
    def test_returns_id_and_length_only(self) -> None:
        meta = CVVariantMetadata(variant_id="cv_x", file_path=Path("cv_x.md"))
        sel = SelectedCV(variant_id="cv_x", metadata=meta, full_text=SENTINEL * 30)
        out = summarise_selected_cv(sel)
        assert out["variant_id"] == "cv_x"
        assert out["full_text_len"] == len(SENTINEL) * 30
        assert not _contains_sentinel(out)


class TestSummariseEvidenceMap:
    def test_returns_counts_only_no_passage_text(self) -> None:
        ev = EvidenceMap(
            items=[
                EvidenceItem(
                    claim=SENTINEL,
                    source_type="cv_variant",
                    source_file="cvs/cv.md",
                    passage=SENTINEL * 5,
                ),
                EvidenceItem(
                    claim=SENTINEL,
                    source_type="master_profile",
                    source_file="profile/master_profile.json",
                    passage=SENTINEL,
                ),
            ],
            known_gaps=[SENTINEL],
            assumptions=[],
        )
        out = summarise_evidence_map(ev)
        assert out["items_count"] == 2
        assert out["known_gaps_count"] == 1
        assert out["assumptions_count"] == 0
        assert out["passage_total_len"] == len(SENTINEL) * 5 + len(SENTINEL)
        assert not _contains_sentinel(out)


class TestSummariseContentPlan:
    def test_returns_metadata_only(self) -> None:
        plan = ContentPlan(
            template_id="tpl",
            selected_cv_variant="cv_x",
            mode=WritingMode.standard,
            sections=[
                SectionPlan(title="role_fit", key_claims=[SENTINEL], evidence_refs=[]),
                SectionPlan(title="motivation", key_claims=[SENTINEL], evidence_refs=[]),
            ],
        )
        out = summarise_content_plan(plan)
        assert out["sections_count"] == 2
        assert out["template_id"] == "tpl"
        assert out["mode"] == "standard"
        assert out["selected_cv_variant"] == "cv_x"
        assert not _contains_sentinel(out)


class TestSummariseLetterDraft:
    def test_returns_counts_only_no_prose(self) -> None:
        draft = LetterDraft(
            text=SENTINEL * 200,
            char_count=len(SENTINEL) * 200,
            mode=WritingMode.standard,
            content_plan_hash="abc123",
        )
        out = summarise_letter_draft(draft)
        assert out["char_count"] == len(SENTINEL) * 200
        assert out["mode"] == "standard"
        assert out["content_plan_hash"] == "abc123"
        assert not _contains_sentinel(out)


class TestSummariseCVTailoringPlan:
    def test_returns_counts_only_no_text(self) -> None:
        plan = CVTailoringPlan(
            base_variant_id="cv_x",
            changes=[
                CVTailoringChange(section="Experience", action="emphasise", rationale=SENTINEL),
            ],
            tailored_text=SENTINEL * 100,
        )
        out = summarise_cv_tailoring_plan(plan)
        assert out["base_variant_id"] == "cv_x"
        assert out["changes_count"] == 1
        assert out["tailored_text_len"] == len(SENTINEL) * 100
        assert not _contains_sentinel(out)


class TestSummariseLetterReview:
    def test_counts_weaknesses_by_severity(self) -> None:
        report = LetterReviewReport(
            sections=[
                SectionReview(
                    section_name="opening",
                    weaknesses=[
                        WeaknessEntry(text=SENTINEL, severity=WeaknessSeverity.high, priority_fix=SENTINEL),
                        WeaknessEntry(text=SENTINEL, severity=WeaknessSeverity.medium, priority_fix=SENTINEL),
                    ],
                ),
                SectionReview(
                    section_name="experience",
                    weaknesses=[
                        WeaknessEntry(text=SENTINEL, severity=WeaknessSeverity.low, priority_fix=SENTINEL),
                    ],
                ),
            ],
            sections_to_rewrite=["opening"],
        )
        out = summarise_letter_review(report)
        assert out["sections_count"] == 2
        assert out["sections_to_rewrite_count"] == 1
        assert out["weakness_high_count"] == 1
        assert out["weakness_medium_count"] == 1
        assert out["weakness_low_count"] == 1
        assert not _contains_sentinel(out)


class TestSummariseValidationReport:
    def test_returns_pass_and_violations(self) -> None:
        report = ValidationReport(
            target="letter",
            results=[ValidationResult(rule="length", status=RuleStatus.pass_)],
            passed=True,
            violations=[],
        )
        out = summarise_validation_report(report)
        assert out["target"] == "letter"
        assert out["passed"] is True
        assert out["results_count"] == 1


# ---------------------------------------------------------------------------
# Stage-level dispatcher tests
# ---------------------------------------------------------------------------


class TestSummariseStateForStage:
    def test_pulls_only_documented_fields_per_stage(self) -> None:
        # Build a state with all the relevant fields populated; sentinel never
        # appears in the summary output for plan_content (input fields).
        from bewerbungs_agent.config.models import (
            CVSelectionMode,
            LengthMode,
            MergedConfig,
        )
        from bewerbungs_agent.models.state import WorkflowState

        config = MergedConfig(
            template_id="tpl",
            language="DE",
            length=LengthMode.normal,
            tone="t",
            mode=WritingMode.standard,
            cv_selection=CVSelectionMode.automatic,
            cv_tailoring=True,
            soft_skill_max=2,
            output_sections=["letter"],
            validation_rules={},
            job_file=Path("j.md"),
            output_dir=Path("out"),
        )
        reqs = RequirementExtraction(core_requirement=SENTINEL)
        ev = EvidenceMap(items=[
            EvidenceItem(claim=SENTINEL, source_type="cv_variant", source_file="cvs/x.md", passage=SENTINEL)
        ])
        state = WorkflowState(config=config, requirements=reqs, evidence_map=ev)
        out = summarise_state_for_stage("plan_content", state)
        assert "requirements" in out and "evidence_map" in out
        assert not _contains_sentinel(out)


class TestSummarisePartialUpdate:
    def test_dispatches_by_key_name(self) -> None:
        draft = LetterDraft(
            text=SENTINEL * 20, char_count=200, mode=WritingMode.standard, content_plan_hash="h"
        )
        out = summarise_partial_update("write_letter", {"letter_draft": draft})
        assert out["letter_draft"]["char_count"] == 200
        assert not _contains_sentinel(out)

    def test_unknown_key_records_type_and_length(self) -> None:
        out = summarise_partial_update("any", {"weird_key": ["a", "b", "c"]})
        assert out["weird_key"]["type"] == "list"
        assert out["weird_key"]["length"] == 3
