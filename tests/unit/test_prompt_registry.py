"""Unit tests for utils.prompt_registry — feature 007 (Langfuse Prompt Registry).

Covers Phase 2 foundational, User Story 1 (sync), User Story 2 (list),
and User Story 3 (runtime resolver).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from bewerbungs_agent.utils.prompt_registry import (
    STAGE_PROMPT_MAP,
    ListEntry,
    ListStatus,
    PromptReference,
    PromptTemplateRecord,
    SyncAction,
    SyncResult,
    clear_cache,
    compute_content_hash,
    discover_prompts,
    list_prompts,
    runtime_reference,
    sync_prompts,
)


@pytest.fixture(autouse=True)
def _clear_module_cache() -> None:
    """Reset the process-local version cache between every test."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Phase 2 — Pydantic records, enums, STAGE_PROMPT_MAP, compute_content_hash
# ---------------------------------------------------------------------------


class TestStagePromptMap:
    def test_contains_known_stage_keys_with_correct_prompt_names(self) -> None:
        assert STAGE_PROMPT_MAP["extract_requirements"] == "requirements"
        assert STAGE_PROMPT_MAP["build_evidence_map"] == "evidence"
        assert STAGE_PROMPT_MAP["plan_content"] == "planner"
        assert STAGE_PROMPT_MAP["write_letter"] == "writer"
        assert STAGE_PROMPT_MAP["tailor_cv"] == "tailor_cv"
        assert STAGE_PROMPT_MAP["hiring_review"] == "hiring_reviewer"
        assert STAGE_PROMPT_MAP["targeted_rewrite"] == "targeted_rewriter"
        assert STAGE_PROMPT_MAP["rewrite_if_needed"] == "writer"
        # Non-LLM stages map to None
        assert STAGE_PROMPT_MAP["load_job"] is None
        assert STAGE_PROMPT_MAP["load_profile"] is None
        assert STAGE_PROMPT_MAP["select_cv_variant"] is None
        assert STAGE_PROMPT_MAP["validate_outputs"] is None


class TestPydanticRecords:
    def test_prompt_template_record_valid_construction(self) -> None:
        r = PromptTemplateRecord(
            name="bewerbungs-agent/planner",
            stage="plan_content",
            path=Path("/abs/prompts/planner.md"),
            relative_path="prompts/planner.md",
            content="hello",
            content_hash="0123456789abcdef",
        )
        assert r.name == "bewerbungs-agent/planner"
        assert r.template_format == "markdown"
        assert r.git_dirty is False

    def test_prompt_template_record_rejects_bad_hash_format(self) -> None:
        with pytest.raises(ValidationError):
            PromptTemplateRecord(
                name="bewerbungs-agent/x",
                stage=None,
                path=Path("/abs/x.md"),
                relative_path="prompts/x.md",
                content="",
                content_hash="not-a-hash",
            )

    def test_prompt_template_record_rejects_relative_path_outside_prompts(self) -> None:
        with pytest.raises(ValidationError):
            PromptTemplateRecord(
                name="bewerbungs-agent/x",
                stage=None,
                path=Path("/abs/x.md"),
                relative_path="other/x.md",  # not under prompts/
                content="",
                content_hash="0123456789abcdef",
            )

    def test_prompt_reference_requires_name_and_hash(self) -> None:
        ref = PromptReference(
            prompt_name="bewerbungs-agent/planner",
            content_hash="0123456789abcdef",
        )
        assert ref.prompt_version is None
        assert ref.label_at_resolve is None

    def test_sync_result_error_message_required_iff_failed(self) -> None:
        with pytest.raises(ValidationError):
            SyncResult(name="x", action=SyncAction.failed, version_after_sync=None)
        with pytest.raises(ValidationError):
            SyncResult(
                name="x",
                action=SyncAction.created,
                version_after_sync=1,
                error_message="should not be here",
            )

    def test_list_entry_no_langfuse_status(self) -> None:
        e = ListEntry(
            file="planner.md",
            local_hash="0123456789abcdef",
            langfuse_name="bewerbungs-agent/planner",
            latest_version=None,
            labels=[],
            status=ListStatus.no_langfuse,
        )
        assert e.status == ListStatus.no_langfuse

    def test_enums_have_expected_values(self) -> None:
        assert {a.value for a in SyncAction} == {"created", "unchanged", "relabeled", "failed"}
        assert {s.value for s in ListStatus} == {
            "up-to-date", "local-differs", "not-synced", "no-langfuse", "local-missing",
        }


class TestComputeContentHash:
    def test_stable_across_calls(self) -> None:
        text = "hello world\n"
        assert compute_content_hash(text) == compute_content_hash(text)

    def test_differs_on_byte_change(self) -> None:
        assert compute_content_hash("hello") != compute_content_hash("hellp")

    def test_returns_16_char_hex(self) -> None:
        h = compute_content_hash("anything")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# User Story 1 — Discovery + sync
# ---------------------------------------------------------------------------


class TestDiscoverPrompts:
    def test_returns_record_per_md_file(self, tmp_path: Path) -> None:
        (tmp_path / "planner.md").write_text("plan content")
        (tmp_path / "system.md").write_text("system content")
        (tmp_path / "styles").mkdir()
        (tmp_path / "styles" / "standard.md").write_text("standard")
        (tmp_path / ".hidden.md").write_text("nope")
        (tmp_path / "_skip.md").write_text("nope")

        records = discover_prompts(prompts_dir=tmp_path)
        names = sorted(r.relative_path for r in records)
        assert names == ["prompts/planner.md", "prompts/styles/standard.md", "prompts/system.md"]

    def test_assigns_stage_from_map(self, tmp_path: Path) -> None:
        (tmp_path / "planner.md").write_text("hello")
        (tmp_path / "system.md").write_text("hello")
        records = discover_prompts(prompts_dir=tmp_path)
        by_path = {r.relative_path: r for r in records}
        assert by_path["prompts/planner.md"].stage == "plan_content"
        assert by_path["prompts/system.md"].stage is None

    def test_returns_empty_list_when_dir_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        records = discover_prompts(prompts_dir=missing)
        assert records == []


# ---------------------------------------------------------------------------
# Helpers for sync tests
# ---------------------------------------------------------------------------


def _make_record(name: str, content: str, *, stage: str | None = None) -> PromptTemplateRecord:
    return PromptTemplateRecord(
        name=name,
        stage=stage,
        path=Path("/abs") / "prompts" / f"{name.split('/')[-1]}.md",
        relative_path=f"prompts/{name.split('/')[-1]}.md",
        content=content,
        content_hash=compute_content_hash(content),
    )


def _existing_prompt_obj(
    *, content_hash: str, version: int = 1, labels: list[str] | None = None
) -> Any:
    """A stand-in for what Langfuse get_prompt() returns."""
    obj = MagicMock()
    obj.version = version
    obj.config = {"content_hash": content_hash}
    obj.labels = labels if labels is not None else []
    return obj


class _NotFoundError(Exception):
    """Stand-in for langfuse not-found error."""


class TestSyncPrompts:
    def test_creates_versions_first_time(self) -> None:
        client = MagicMock()
        client.get_prompt.side_effect = _NotFoundError("404")
        client.create_prompt.return_value = MagicMock(version=1)
        records = [
            _make_record("bewerbungs-agent/a", "alpha"),
            _make_record("bewerbungs-agent/b", "beta"),
        ]
        results = sync_prompts(records, label="staging", client=client)
        assert [r.action for r in results] == [SyncAction.created, SyncAction.created]
        assert client.create_prompt.call_count == 2
        # Each call carries the label and the metadata block.
        for call in client.create_prompt.call_args_list:
            kwargs = call.kwargs
            assert kwargs["labels"] == ["staging"]
            assert "content_hash" in kwargs["config"]
            assert "file_path" in kwargs["config"]

    def test_idempotent_when_no_changes(self) -> None:
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        existing = _existing_prompt_obj(
            content_hash=records[0].content_hash, version=4, labels=["staging"]
        )
        client = MagicMock()
        client.get_prompt.return_value = existing

        results = sync_prompts(records, label="staging", client=client)
        assert results[0].action == SyncAction.unchanged
        assert results[0].version_after_sync == 4
        client.create_prompt.assert_not_called()
        client.update_prompt.assert_not_called()

    def test_creates_new_version_on_change(self) -> None:
        records = [
            _make_record("bewerbungs-agent/a", "alpha"),
            _make_record("bewerbungs-agent/b", "beta NEW"),
        ]
        # Both prompts exist on Langfuse. The first matches local; the second's
        # remote hash differs (still old "beta" content).
        existing_a = _existing_prompt_obj(content_hash=records[0].content_hash, version=2, labels=["staging"])
        existing_b = _existing_prompt_obj(content_hash=compute_content_hash("beta"), version=5, labels=["staging"])
        client = MagicMock()
        client.get_prompt.side_effect = [existing_a, existing_b]
        client.create_prompt.return_value = MagicMock(version=6)

        results = sync_prompts(records, label="staging", client=client)
        assert results[0].action == SyncAction.unchanged
        assert results[1].action == SyncAction.created
        assert results[1].version_after_sync == 6
        assert client.create_prompt.call_count == 1

    def test_moves_label_to_new_version(self) -> None:
        # Local hash matches remote, but the requested label isn't on the remote version yet.
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        existing = _existing_prompt_obj(
            content_hash=records[0].content_hash, version=3, labels=["development"]
        )
        client = MagicMock()
        client.get_prompt.return_value = existing

        results = sync_prompts(records, label="production", client=client)
        assert results[0].action == SyncAction.relabeled
        client.update_prompt.assert_called_once()
        # The new_labels list contains the existing label plus the new one.
        kwargs = client.update_prompt.call_args.kwargs
        assert "production" in kwargs["new_labels"]
        assert "development" in kwargs["new_labels"]
        assert kwargs["version"] == 3

    def test_per_record_failure_does_not_abort_batch(self) -> None:
        records = [
            _make_record("bewerbungs-agent/a", "alpha"),
            _make_record("bewerbungs-agent/b", "beta"),
            _make_record("bewerbungs-agent/c", "gamma"),
        ]
        client = MagicMock()
        client.get_prompt.side_effect = _NotFoundError("404")

        def _create(*, name: str, **kwargs: Any) -> Any:
            if name == "bewerbungs-agent/b":
                raise RuntimeError("API down")
            return MagicMock(version=1)

        client.create_prompt.side_effect = _create

        results = sync_prompts(records, label="staging", client=client)
        assert len(results) == 3
        assert results[0].action == SyncAction.created
        assert results[1].action == SyncAction.failed
        assert "API down" in (results[1].error_message or "")
        assert results[2].action == SyncAction.created

    def test_default_label_is_staging(self) -> None:
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        client = MagicMock()
        client.get_prompt.side_effect = _NotFoundError("404")
        client.create_prompt.return_value = MagicMock(version=1)

        sync_prompts(records, client=client)
        kwargs = client.create_prompt.call_args.kwargs
        assert kwargs["labels"] == ["staging"]


# ---------------------------------------------------------------------------
# User Story 2 — list_prompts
# ---------------------------------------------------------------------------


class TestListPrompts:
    def test_status_up_to_date_when_hash_matches(self) -> None:
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        existing = _existing_prompt_obj(
            content_hash=records[0].content_hash, version=2, labels=["staging"]
        )
        client = MagicMock()
        client.get_prompt.return_value = existing
        entries = list_prompts(records, client=client)
        assert entries[0].status == ListStatus.up_to_date
        assert entries[0].latest_version == 2
        assert entries[0].labels == ["staging"]

    def test_status_local_differs_when_hash_mismatches(self) -> None:
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        existing = _existing_prompt_obj(content_hash="deadbeefdeadbeef", version=1, labels=[])
        client = MagicMock()
        client.get_prompt.return_value = existing
        entries = list_prompts(records, client=client)
        assert entries[0].status == ListStatus.local_differs

    def test_status_not_synced_when_get_prompt_raises_not_found(self) -> None:
        records = [_make_record("bewerbungs-agent/a", "alpha")]
        client = MagicMock()
        client.get_prompt.side_effect = _NotFoundError("404")
        entries = list_prompts(records, client=client)
        assert entries[0].status == ListStatus.not_synced
        assert entries[0].latest_version is None

    def test_status_no_langfuse_when_client_is_none(self) -> None:
        records = [
            _make_record("bewerbungs-agent/a", "alpha"),
            _make_record("bewerbungs-agent/b", "beta"),
        ]
        entries = list_prompts(records, client=None)
        for e in entries:
            assert e.status == ListStatus.no_langfuse
            assert e.latest_version is None
            assert e.labels == []


# ---------------------------------------------------------------------------
# User Story 3 — runtime_reference + cache
# ---------------------------------------------------------------------------


class TestRuntimeReference:
    def test_returns_version_when_hash_matches(self) -> None:
        local_hash = "0123456789abcdef"
        client = MagicMock()
        client.get_prompt.return_value = _existing_prompt_obj(
            content_hash=local_hash, version=7, labels=["production"]
        )
        ref = runtime_reference("bewerbungs-agent/planner", local_hash, client=client)
        assert ref.prompt_version == 7
        assert ref.content_hash == local_hash
        assert ref.label_at_resolve == "production"

    def test_returns_none_when_hash_mismatches(self) -> None:
        client = MagicMock()
        client.get_prompt.return_value = _existing_prompt_obj(
            content_hash="0000000000000000", version=1, labels=[]
        )
        ref = runtime_reference("bewerbungs-agent/planner", "ffffffffffffffff", client=client)
        assert ref.prompt_version is None

    def test_returns_none_when_get_prompt_raises(self) -> None:
        client = MagicMock()
        client.get_prompt.side_effect = _NotFoundError("404")
        ref = runtime_reference("bewerbungs-agent/x", "0123456789abcdef", client=client)
        assert ref.prompt_version is None

    def test_returns_none_without_client(self) -> None:
        ref = runtime_reference("bewerbungs-agent/x", "0123456789abcdef", client=None)
        assert ref.prompt_version is None

    def test_cached_after_first_lookup(self) -> None:
        client = MagicMock()
        client.get_prompt.return_value = _existing_prompt_obj(
            content_hash="0123456789abcdef", version=1
        )
        runtime_reference("bewerbungs-agent/x", "0123456789abcdef", client=client)
        runtime_reference("bewerbungs-agent/x", "0123456789abcdef", client=client)
        assert client.get_prompt.call_count == 1

    def test_new_hash_triggers_new_lookup(self) -> None:
        client = MagicMock()
        client.get_prompt.return_value = _existing_prompt_obj(
            content_hash="0123456789abcdef", version=1
        )
        runtime_reference("bewerbungs-agent/x", "aaaaaaaaaaaaaaaa", client=client)
        runtime_reference("bewerbungs-agent/x", "bbbbbbbbbbbbbbbb", client=client)
        assert client.get_prompt.call_count == 2
