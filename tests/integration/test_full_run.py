"""Integration test: full pipeline run with mocked LLM client.

Invokes the compiled LangGraph pipeline with the fixture job + template and a
mock LLM client that returns canned responses at each stage. Asserts that:
- letter.md is produced
- All required artifact files are present and loadable as their Pydantic types
- No evidence source path references files outside data/examples/
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bewerbungs_agent.config.models import (
    CVSelectionMode,
    LengthMode,
    MergedConfig,
    WritingMode,
)
from bewerbungs_agent.models.state import (
    EvidenceMap,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Fixture LLM responses — one per LLM-calling stage
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "data" / "examples"

_REQUIREMENTS_RESPONSE: dict[str, Any] = {
    "core_requirement": "Design and operate Python-based data pipelines",
    "technical_requirements": ["Python", "Spark"],
    "domain_requirement": "data infrastructure",
    "collaboration_requirement": "cross-functional teams, mentoring junior engineers",
    "must_include": [],
    "must_avoid": [],
}

_SELECT_CV_RESPONSE: dict[str, Any] = {
    "variant_id": "cv_software",
    "selection_reason": "Software variant best matches data pipeline requirements",
}

_EVIDENCE_MAP_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "claim": "Led Python-based data pipeline development at DataStream GmbH",
            "source_type": "cv_variant",
            "source_file": "cvs/cv_software.md",
            "passage": "Designed and maintained Python data pipelines.",
            "relevance_note": "Directly evidences Python pipeline experience.",
        },
        {
            "claim": "Experience with cross-functional team collaboration",
            "source_type": "master_profile",
            "source_file": "profile/master_profile.json",
            "passage": "Worked across data science and product teams.",
            "relevance_note": "Evidences collaboration requirement.",
        },
    ],
    "known_gaps": ["Spark / Beam experience not documented"],
    "assumptions": [],
}

_PLAN_RESPONSE: dict[str, Any] = {
    "template_id": "default_de_neutral",
    "selected_cv_variant": "cv_software",
    "mode": "standard",
    "sections": [
        {
            "title": "role_fit",
            "key_claims": ["Led Python-based data pipeline development at DataStream GmbH"],
            "evidence_refs": ["Led Python-based data pipeline development at DataStream GmbH"],
            "anchor_passages": ["Designed and maintained Python data pipelines."],
            "soft_skills": [],
        }
    ],
    "selected_soft_skills": [],
    "evidence_map": {
        "items": [
            {
                "claim": "Led Python-based data pipeline development at DataStream GmbH",
                "source_type": "cv_variant",
                "source_file": "cvs/cv_software.md",
                "passage": "Designed and maintained Python data pipelines.",
                "relevance_note": "Directly evidences Python pipeline experience.",
            }
        ],
        "known_gaps": [],
        "assumptions": [],
    },
    "open_questions": [],
    "assumptions": [],
}

_LETTER_RESPONSE: dict[str, Any] = {
    "text": "Sehr geehrte Damen und Herren,\n\n"
            + "x" * 2200  # enough to pass length validation
            + "\n\nMit freundlichen Grüßen\nAlex Mustermann\n",
    "mode": "standard",
}

_TAILOR_CV_RESPONSE: dict[str, Any] = {
    "base_variant_id": "cv_software",
    "tailored_text": "# Lebenslauf\n\nAlex Mustermann\n\n## Erfahrung\n\n"
                     "Senior Software Engineer — DataStream GmbH\n",
    "changes": [
        {
            "section": "Experience",
            "action": "emphasise",
            "rationale": "Highlights Python pipeline work matching core requirement",
            "evidence_ref": "Led Python-based data pipeline development at DataStream GmbH",
        }
    ],
}


_HIRING_REVIEW_RESPONSE: dict[str, Any] = {
    "sections": [
        {
            "section_name": "opening",
            "strengths": ["Clear introduction"],
            "weaknesses": [
                {
                    "text": "Opening is somewhat generic",
                    "severity": "medium",
                    "priority_fix": "Reference the specific role title",
                }
            ],
            "assessment": "Decent but could be more targeted.",
        },
        {
            "section_name": "experience",
            "strengths": ["Specific project with Python pipelines", "Quantified results"],
            "weaknesses": [],
            "assessment": "Strong, evidence-grounded section.",
        },
    ],
    "overall_assessment": "Letter is adequate; opening needs tailoring.",
}

_TARGETED_REWRITE_RESPONSE: dict[str, Any] = {
    "text": "Sehr geehrte Damen und Herren,\n\n"
            + "Ich bewerbe mich als Data Engineer.\n\n"
            + "x" * 2100
            + "\n\nMit freundlichen Grüßen\nAlex Mustermann\n",
}

_ROLE_POSITION_RESPONSE: dict[str, Any] = {
    "role_family": "backend infrastructure engineering",
    "primary_selling_point": "Built Python data pipelines for DataStream GmbH.",
    "secondary_selling_points": [],
    "emphasise": ["data infrastructure"],
    "deemphasise": [],
    "opening_angle": "Lead with hands-on Python pipeline experience.",
    "risky_or_gap_areas": [],
}

_NARRATIVE_STRATEGY_RESPONSE: dict[str, Any] = {
    "candidate_story": "An engineer who built and operates Python data pipelines.",
    "role_story": "DataStream needs someone who can own pipeline reliability.",
    "bridge": "The candidate already owns the pipelines this role needs maintained.",
    "opening_angle": "Lead with hands-on Python pipeline experience.",
    "proof_points_to_use": [
        "Led Python-based data pipeline development at DataStream GmbH",
    ],
    "proof_points_to_avoid": [],
    "transfer_framing_guidance": "",
    "tone_guidance": "Calm, senior, credible, institutional voice.",
    "anti_patterns": [
        "Do not open with 'Although my background is...' — defensive framing",
    ],
}

_STORY_POLISH_RESPONSE: dict[str, Any] = {
    # Returns text identical to draft so the post-check passes trivially.
    "polished_text": (
        "Sehr geehrte Damen und Herren,\n\n"
        + "x" * 2200
        + "\n\nMit freundlichen Grüßen\nAlex Mustermann\n"
    ),
}

_RESPONSES_BY_SCHEMA_TITLE: dict[str, dict] = {
    "extract_requirements": _REQUIREMENTS_RESPONSE,
    "select_cv_variant": _SELECT_CV_RESPONSE,
    "build_evidence_map": _EVIDENCE_MAP_RESPONSE,
    "role_position": _ROLE_POSITION_RESPONSE,
    "narrative_strategy": _NARRATIVE_STRATEGY_RESPONSE,
    "plan_content": _PLAN_RESPONSE,
    "write_letter": _LETTER_RESPONSE,
    "story_polish": _STORY_POLISH_RESPONSE,
    "hiring_review": _HIRING_REVIEW_RESPONSE,
    "targeted_rewrite": _TARGETED_REWRITE_RESPONSE,
    "tailor_cv": _TAILOR_CV_RESPONSE,
}


def _make_llm_mock() -> MagicMock:
    """Return a MagicMock LLM client that dispatches by tool schema title.

    Parallel branches (write_letter, tailor_cv) may be invoked in any order;
    dispatching by schema title is order-independent.
    """
    client = MagicMock()

    def _call(messages: list, tool_schema: dict, **kwargs: Any) -> dict:
        title = tool_schema.get("title", "")
        if title not in _RESPONSES_BY_SCHEMA_TITLE:
            raise ValueError(f"No fixture response for schema title '{title}'")
        return _RESPONSES_BY_SCHEMA_TITLE[title]

    client.call.side_effect = _call
    return client


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestFullPipelineRun:
    def test_produces_letter_and_artifacts(self, tmp_path: Path) -> None:
        """Full graph run with mock LLM → letter.md + all artifact files."""
        from bewerbungs_agent.graph.workflow import build_graph
        from bewerbungs_agent.io.loader import load_starter_template
        from bewerbungs_agent.io.writer import write_artifacts, write_final_outputs
        from bewerbungs_agent.utils.merge import merge_config

        template_path = EXAMPLES_DIR / "templates" / "default_de_neutral.yaml"
        starter = load_starter_template(template_path)

        from bewerbungs_agent.config.models import RunInput

        run_input = RunInput(
            starter_template_id="default_de_neutral",
            job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
            output_dir=tmp_path / "outputs",
        )
        config = merge_config(starter, run_input, profile_dir=str(EXAMPLES_DIR))

        initial_state = WorkflowState(config=config, run_id="integration-test")

        mock_client = _make_llm_mock()

        graph = build_graph()

        with patch(
            "bewerbungs_agent.utils.llm_client.get_llm_client", return_value=mock_client
        ), patch(
            "bewerbungs_agent.stages.select_cv_variant.get_llm_client",
            return_value=mock_client,
        ):
            raw = graph.invoke(initial_state)

        # LangGraph returns a dict of accumulated state updates; reconstruct model
        if isinstance(raw, dict):
            final_state = initial_state.model_copy(update=raw)
        else:
            final_state = raw

        output_dir = tmp_path / "outputs"
        write_artifacts(final_state, output_dir)
        write_final_outputs(final_state, output_dir)

        # letter.md must exist
        letter_path = output_dir / "letter.md"
        assert letter_path.exists(), "letter.md not produced"
        assert len(letter_path.read_text(encoding="utf-8")) > 100

        # All required artifact files
        artifacts = output_dir / "artifacts"
        required_files = [
            "requirements.json",
            "evidence_map.json",
            "known_gaps.json",
            "content_plan.json",
        ]
        for fname in required_files:
            fpath = artifacts / fname
            assert fpath.exists(), f"artifacts/{fname} not produced"

        # evidence_map.json must be loadable as EvidenceMap
        evidence_data = json.loads((artifacts / "evidence_map.json").read_text())
        evidence_map = EvidenceMap.model_validate(evidence_data)
        assert isinstance(evidence_map, EvidenceMap)

        # No source path may reference files outside EXAMPLES_DIR
        examples_str = str(EXAMPLES_DIR)
        for item in evidence_map.items:
            path = Path(item.source_file)
            if path.is_absolute():
                assert str(path).startswith(examples_str), (
                    f"Source file '{item.source_file}' is outside examples dir"
                )
            else:
                # Relative paths must start with an approved prefix
                assert any(
                    item.source_file.startswith(prefix)
                    for prefix in ("profile/", "cvs/", "letters/")
                ), f"Unapproved relative source path: '{item.source_file}'"

    def test_deep_cv_achievement_surfaces_in_letter(self, tmp_path: Path) -> None:
        """SC-003: A deep-CV achievement (beyond char 3000) must reach the letter.

        build_evidence_map now passes the full CV text. We verify the sentinel
        achievement is present in the build_prompt output (prompt test) rather
        than doing an end-to-end LLM call (which would require a real API key).
        The prompt test ensures the full text is available to the LLM, which is
        the root cause fix validated by this test.
        """
        from pathlib import Path as PPath

        from bewerbungs_agent.models.state import (
            CVVariantMetadata,
            InternalKnowledge,
            RequirementExtraction,
            SelectedCV,
        )
        from bewerbungs_agent.stages.build_evidence_map import build_prompt

        sentinel = "SENTINEL_DEEP_ACHIEVEMENT_BEYOND_3000"
        prefix = "x" * 3100
        long_cv_text = prefix + " " + sentinel

        cv_file = tmp_path / "cv_deep.md"
        cv_file.write_text(long_cv_text)
        meta = CVVariantMetadata(
            variant_id="cv_deep",
            file_path=PPath(str(cv_file)),
            role_families=["software"],
        )
        knowledge = InternalKnowledge(
            master_profile={"name": "Test"},
            cv_variants=[meta],
            personal_skills="skills",
        )
        selected_cv = SelectedCV(
            variant_id="cv_deep", metadata=meta, full_text=long_cv_text
        )
        reqs = RequirementExtraction(core_requirement="Python expertise")

        from bewerbungs_agent.config.models import (
            CVSelectionMode,
            LengthMode,
            MergedConfig,
            WritingMode,
        )

        config = MergedConfig(
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
            job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
            output_dir=tmp_path / "outputs",
            profile_dir=EXAMPLES_DIR,
        )
        from bewerbungs_agent.models.state import WorkflowState as WS

        state = WS(
            config=config,
            knowledge=knowledge,
            selected_cv=selected_cv,
            requirements=reqs,
        )
        messages = build_prompt(state)
        combined = " ".join(str(m) for m in messages)
        assert sentinel in combined, (
            "Deep-CV sentinel must appear in build_evidence_map prompt (SC-003: "
            "full CV text passed, not truncated head)"
        )

    def test_known_gaps_written_even_when_empty(self, tmp_path: Path) -> None:
        """known_gaps.json must be written even when the list is empty."""
        from bewerbungs_agent.io.writer import write_artifacts
        from bewerbungs_agent.models.state import EvidenceMap, WorkflowState

        config = MergedConfig(
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
            job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
            output_dir=tmp_path / "outputs",
            profile_dir=EXAMPLES_DIR,
        )
        state = WorkflowState(
            config=config,
            evidence_map=EvidenceMap(items=[], known_gaps=[], assumptions=[]),
        )

        write_artifacts(state, tmp_path / "outputs")

        gaps_path = tmp_path / "outputs" / "artifacts" / "known_gaps.json"
        assert gaps_path.exists(), "known_gaps.json not written when gaps list is empty"
        data = json.loads(gaps_path.read_text())
        assert data == []

    def test_full_run_with_stage_thinking(self, tmp_path: Path) -> None:
        """Stage-specific thinking enabled for build_evidence_map and plan_content only.

        Verifies that mock client receives thinking=ThinkingConfig(enabled=True) for
        the two configured stages, and thinking=ThinkingConfig(enabled=False) for others.
        """
        from bewerbungs_agent.config.models import RunInput, ThinkingConfig, ThinkingEffort
        from bewerbungs_agent.graph.workflow import build_graph
        from bewerbungs_agent.io.loader import load_starter_template
        from bewerbungs_agent.utils.merge import merge_config

        template_path = EXAMPLES_DIR / "templates" / "default_de_neutral.yaml"
        starter = load_starter_template(template_path)

        run_input = RunInput(
            starter_template_id="default_de_neutral",
            job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
            output_dir=tmp_path / "outputs",
        )
        config = merge_config(starter, run_input, profile_dir=str(EXAMPLES_DIR))

        # Enable thinking only for two stages
        config = config.model_copy(update={
            "thinking": ThinkingConfig(enabled=False),
            "stage_thinking": {
                "build_evidence_map": ThinkingConfig(enabled=True, effort=ThinkingEffort.medium),
                "plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high),
            },
        })

        # Track thinking kwargs per schema title
        captured_thinking: dict[str, Any] = {}

        mock_client = MagicMock()

        def _call(messages: list, tool_schema: dict, **kwargs: Any) -> dict:
            title = tool_schema.get("title", "")
            captured_thinking[title] = kwargs.get("thinking")
            if title not in _RESPONSES_BY_SCHEMA_TITLE:
                raise ValueError(f"No fixture response for schema title '{title}'")
            return _RESPONSES_BY_SCHEMA_TITLE[title]

        mock_client.call.side_effect = _call

        initial_state = WorkflowState(config=config, run_id="thinking-test")
        graph = build_graph()

        with patch(
            "bewerbungs_agent.utils.llm_client.get_llm_client", return_value=mock_client
        ), patch(
            "bewerbungs_agent.stages.select_cv_variant.get_llm_client",
            return_value=mock_client,
        ):
            graph.invoke(initial_state)

        # build_evidence_map and plan_content must receive thinking enabled
        assert captured_thinking.get("build_evidence_map") is not None
        assert captured_thinking["build_evidence_map"].enabled is True
        assert captured_thinking["build_evidence_map"].effort == ThinkingEffort.medium

        assert captured_thinking.get("plan_content") is not None
        assert captured_thinking["plan_content"].enabled is True
        assert captured_thinking["plan_content"].effort == ThinkingEffort.high

        # Stages without override use global default (thinking disabled)
        assert captured_thinking.get("extract_requirements") is not None
        assert captured_thinking["extract_requirements"].enabled is False

        assert captured_thinking.get("write_letter") is not None
        assert captured_thinking["write_letter"].enabled is False

        assert captured_thinking.get("tailor_cv") is not None
        assert captured_thinking["tailor_cv"].enabled is False

    def test_full_pipeline_with_hiring_review(self, tmp_path: Path) -> None:
        """Full pipeline run: hiring_review and targeted_rewrite stages fire.

        Asserts:
        - letter_review is populated with a LetterReviewReport
        - letter_draft reflects the targeted_rewrite output (mock rewritten text)
        - sections_to_rewrite is non-empty (medium-severity weakness triggers it)
        """
        from bewerbungs_agent.config.models import RunInput
        from bewerbungs_agent.graph.workflow import build_graph
        from bewerbungs_agent.io.loader import load_starter_template
        from bewerbungs_agent.models.state import LetterReviewReport
        from bewerbungs_agent.utils.merge import merge_config

        template_path = EXAMPLES_DIR / "templates" / "default_de_neutral.yaml"
        starter = load_starter_template(template_path)

        run_input = RunInput(
            starter_template_id="default_de_neutral",
            job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
            output_dir=tmp_path / "outputs",
        )
        config = merge_config(starter, run_input, profile_dir=str(EXAMPLES_DIR))

        initial_state = WorkflowState(config=config, run_id="review-test")
        mock_client = _make_llm_mock()
        graph = build_graph()

        with patch(
            "bewerbungs_agent.utils.llm_client.get_llm_client", return_value=mock_client
        ), patch(
            "bewerbungs_agent.stages.select_cv_variant.get_llm_client",
            return_value=mock_client,
        ):
            raw = graph.invoke(initial_state)

        if isinstance(raw, dict):
            final_state = initial_state.model_copy(update=raw)
        else:
            final_state = raw

        # hiring_review populated letter_review
        assert final_state.letter_review is not None
        assert isinstance(final_state.letter_review, LetterReviewReport)
        assert len(final_state.letter_review.sections) == 2

        # medium-severity weakness on "opening" triggers rewrite
        assert "opening" in final_state.letter_review.sections_to_rewrite

        # targeted_rewrite produced updated letter_draft
        assert final_state.letter_draft is not None
        assert final_state.letter_draft.text == _TARGETED_REWRITE_RESPONSE["text"]


# ---------------------------------------------------------------------------
# User Story 1 integration tests (Langfuse observability)
# ---------------------------------------------------------------------------


def _run_pipeline_to_disk(
    output_root: Path,
    *,
    observability_obj: Any = None,
) -> WorkflowState:
    """Helper: run the full pipeline with a deterministic mock LLM and write
    every artifact to *output_root*. Returns the final state.
    """
    from bewerbungs_agent.config.models import RunInput
    from bewerbungs_agent.graph.workflow import build_graph
    from bewerbungs_agent.io.loader import load_starter_template
    from bewerbungs_agent.io.writer import write_artifacts, write_final_outputs
    from bewerbungs_agent.utils.merge import merge_config

    template_path = EXAMPLES_DIR / "templates" / "default_de_neutral.yaml"
    starter = load_starter_template(template_path)

    run_input = RunInput(
        starter_template_id="default_de_neutral",
        job_file=EXAMPLES_DIR / "jobs" / "sample_software_engineer.md",
        output_dir=output_root,
    )
    config = merge_config(starter, run_input, profile_dir=str(EXAMPLES_DIR))

    initial_state = WorkflowState(config=config, run_id="byteidem-test")
    if observability_obj is not None:
        initial_state = initial_state.model_copy(update={"observability": observability_obj})

    mock_client = _make_llm_mock()
    graph = build_graph()

    with patch(
        "bewerbungs_agent.utils.llm_client.get_llm_client", return_value=mock_client
    ), patch(
        "bewerbungs_agent.stages.select_cv_variant.get_llm_client",
        return_value=mock_client,
    ):
        raw = graph.invoke(initial_state)

    if isinstance(raw, dict):
        final_state = initial_state.model_copy(update=raw)
    else:
        final_state = raw

    write_artifacts(final_state, output_root)
    write_final_outputs(final_state, output_root)
    return final_state


class TestLangfuseObservabilityIntegration:
    def test_full_pipeline_succeeds_with_no_langfuse_creds(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """FR-022: pipeline must run cleanly when Langfuse env vars are absent.

        Even without explicit observability injection, the wrapper must handle
        state.observability is None.
        """
        for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
            monkeypatch.delenv(var, raising=False)

        output_dir = tmp_path / "out_no_creds"
        final_state = _run_pipeline_to_disk(output_dir)

        assert (output_dir / "letter.md").exists()
        assert (output_dir / "artifacts" / "evidence_map.json").exists()
        assert final_state.letter_draft is not None

    def test_full_pipeline_records_spans_when_enabled(self, tmp_path: Path) -> None:
        """FR-002 / FR-023: with an injected recording observability, every
        stage emits one span."""
        from bewerbungs_agent.utils.observability import NoOpObservability

        # Use the _RecordingObservability shape inline (importing the test class
        # would create a circular dependency between integration and unit tests).
        spans_seen: list[str] = []

        class _RecordingObs(NoOpObservability):
            def stage_span(self_inner, stage_name: str, *, prompt_name: Any = None) -> Any:
                spans_seen.append(stage_name)
                return super().stage_span(stage_name, prompt_name=prompt_name)

        output_dir = tmp_path / "out_enabled"
        _run_pipeline_to_disk(output_dir, observability_obj=_RecordingObs())

        # Every expected stage emitted at least one span.
        expected = {
            "load_job", "extract_requirements", "load_profile", "select_cv_variant",
            "build_evidence_map", "plan_content", "write_letter", "tailor_cv",
            "hiring_review", "targeted_rewrite", "validate_outputs",
        }
        assert expected.issubset(set(spans_seen)), (
            f"missing spans: {expected - set(spans_seen)}; got {spans_seen}"
        )

    def test_full_pipeline_outputs_byte_identical_enabled_vs_disabled(
        self, tmp_path: Path
    ) -> None:
        """FR-013 / FR-025 / SC-004: outputs must be byte-identical regardless
        of whether observability is enabled."""
        import filecmp

        from bewerbungs_agent.utils.observability import NoOpObservability

        out_a = tmp_path / "out_disabled"
        out_b = tmp_path / "out_enabled"

        # Run A: no observability at all.
        _run_pipeline_to_disk(out_a, observability_obj=None)

        # Run B: with a (recording) observability attached.
        class _RecordingObs(NoOpObservability):
            def __init__(self_inner) -> None:
                self_inner.recorded: list[str] = []

            def stage_span(self_inner, stage_name: str, *, prompt_name: Any = None) -> Any:
                self_inner.recorded.append(stage_name)
                return super().stage_span(stage_name, prompt_name=prompt_name)

        _run_pipeline_to_disk(out_b, observability_obj=_RecordingObs())

        # Compare every artifact file: must be byte-identical.
        compare_paths = [
            "letter.md",
            "artifacts/requirements.json",
            "artifacts/evidence_map.json",
            "artifacts/known_gaps.json",
            "artifacts/content_plan.json",
        ]
        for rel in compare_paths:
            path_a = out_a / rel
            path_b = out_b / rel
            assert path_a.exists() and path_b.exists(), f"missing: {rel}"
            assert filecmp.cmp(str(path_a), str(path_b), shallow=False), (
                f"FR-013 regression: {rel} differs between observability-disabled "
                f"and observability-enabled runs"
            )

    def test_full_pipeline_captures_stage_exception_on_span(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """FR-008 / FR-024: an exception inside a stage is captured on its
        span with the error type and message, then re-raised."""
        from bewerbungs_agent.utils.observability import NoOpObservability

        captured_errors: list[tuple[str, BaseException]] = []

        class _ErrorCapturingSpan:
            __slots__ = ("_name",)

            def __init__(self_inner, name: str) -> None:
                self_inner._name = name

            def set_prompt(self_inner, *a: Any, **k: Any) -> None: pass
            def set_model(self_inner, *a: Any, **k: Any) -> None: pass
            def set_input(self_inner, *a: Any, **k: Any) -> None: pass
            def set_output(self_inner, *a: Any, **k: Any) -> None: pass
            def set_token_usage(self_inner, *a: Any, **k: Any) -> None: pass
            def set_artifact_path(self_inner, *a: Any, **k: Any) -> None: pass

            def set_error(self_inner, exc: BaseException) -> None:
                captured_errors.append((self_inner._name, exc))

        class _ErrorCapturingObs(NoOpObservability):
            def stage_span(self_inner, stage_name: str, *, prompt_name: Any = None) -> Any:
                span = _ErrorCapturingSpan(stage_name)
                from contextlib import contextmanager

                @contextmanager
                def _cm() -> Any:
                    yield span

                return _cm()

        # Inject a failure into the load_profile stage.
        from bewerbungs_agent.stages import load_profile as load_profile_mod

        def _boom(_: Any) -> Any:
            raise RuntimeError("synthetic failure for span-capture test")

        monkeypatch.setattr(load_profile_mod, "load_profile", _boom)

        # Force the graph to be rebuilt with the patched stage.
        import bewerbungs_agent.graph.workflow as wf_mod

        wf_mod._compiled_graph = None

        output_dir = tmp_path / "out_error"
        try:
            with pytest.raises(Exception):
                _run_pipeline_to_disk(
                    output_dir, observability_obj=_ErrorCapturingObs()
                )
        finally:
            wf_mod._compiled_graph = None

        assert any(name == "load_profile" for name, _ in captured_errors), (
            f"expected load_profile span to capture the error; got {captured_errors}"
        )
        assert any(isinstance(exc, RuntimeError) for _, exc in captured_errors)

    def test_full_pipeline_span_carries_prompt_reference(self, tmp_path: Path) -> None:
        """Feature 007 / FR-017 / FR-026: every LLM-stage span receives a
        PromptReference carrying the matching Langfuse version.

        Also verifies FR-019 / SC-008 (privacy retained): no raw CV / profile /
        letter prose appears in any captured span payload.
        """
        from bewerbungs_agent.utils.observability import NoOpObservability
        from bewerbungs_agent.utils.prompt_registry import (
            PromptReference,
            clear_cache,
        )

        clear_cache()

        captured_refs: list[tuple[str, PromptReference]] = []
        captured_inputs: list[Any] = []
        captured_outputs: list[Any] = []

        class _RecordingPromptSpan:
            __slots__ = ("_stage",)

            def __init__(self_inner, stage: str) -> None:
                self_inner._stage = stage

            def set_prompt(self_inner, *a: Any, **k: Any) -> None: pass
            def set_model(self_inner, *a: Any, **k: Any) -> None: pass

            def set_input(self_inner, payload: Any, full: bool = False) -> None:
                captured_inputs.append(payload)

            def set_output(self_inner, payload: Any, full: bool = False) -> None:
                captured_outputs.append(payload)

            def set_token_usage(self_inner, *a: Any, **k: Any) -> None: pass
            def set_artifact_path(self_inner, *a: Any, **k: Any) -> None: pass
            def set_error(self_inner, *a: Any, **k: Any) -> None: pass

            def set_prompt_reference(self_inner, reference: PromptReference) -> None:
                captured_refs.append((self_inner._stage, reference))

        # Fake Langfuse client whose get_prompt always returns a matching hash
        # so the resolver lands version=3 for every LLM-stage prompt.
        fake_client = MagicMock()

        def _get(name: str, **kwargs: Any) -> Any:
            # Compute the local hash on-the-fly via the existing util so the
            # resolver's "remote hash matches local hash" branch fires.
            from bewerbungs_agent.utils.tracker import _compute_prompt_hash

            stem = name.rsplit("/", 1)[-1]
            return MagicMock(
                version=3,
                config={"content_hash": _compute_prompt_hash(stem)},
                labels=["production"],
            )

        fake_client.get_prompt.side_effect = _get

        class _PromptCapturingObs(NoOpObservability):
            def underlying_client(self_inner) -> Any:
                return fake_client

            def stage_span(self_inner, stage_name: str, *, prompt_name: Any = None) -> Any:
                from contextlib import contextmanager

                @contextmanager
                def _cm() -> Any:
                    yield _RecordingPromptSpan(stage_name)

                return _cm()

        output_dir = tmp_path / "out_prompt_ref"
        _run_pipeline_to_disk(output_dir, observability_obj=_PromptCapturingObs())

        # At least one LLM stage span carried a PromptReference with the
        # mocked Langfuse version (3) — i.e. resolution actually fired.
        llm_refs = [(stage, ref) for stage, ref in captured_refs if ref.prompt_version is not None]
        assert llm_refs, f"no prompt references captured; got {captured_refs}"
        stages_with_version = {stage for stage, _ in llm_refs}
        # Spot-check a couple of LLM-stage names from STAGE_PROMPT_MAP
        assert "plan_content" in stages_with_version
        assert "write_letter" in stages_with_version
        for _, ref in llm_refs:
            assert ref.prompt_version == 3
            assert ref.prompt_name.startswith("bewerbungs-agent/")

        # Privacy invariant retained: no raw CV / profile / letter prose in
        # any captured payload (summary mode is the default).
        combined_payloads = repr(captured_inputs) + repr(captured_outputs)
        # The fixture letter contains 2200+ 'x' chars; if raw prose leaked
        # we'd see a very long run of them.
        assert "x" * 100 not in combined_payloads, (
            "raw letter prose appears to have leaked into a span payload"
        )
