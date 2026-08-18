"""CLI tests for `jobagent prompts sync` and `jobagent prompts list`.

Covers feature 007 User Story 1 (sync) and User Story 2 (list) CLI surfaces.
Mocks the Langfuse client via build_observability monkey-patching.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from bewerbungs_agent.cli import app
from bewerbungs_agent.utils.prompt_registry import (
    PromptTemplateRecord,
    clear_cache,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each CLI test gets a clean env + clean cache."""
    for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        monkeypatch.delenv(var, raising=False)
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_prompts_dir(tmp_path: Path) -> Path:
    """A tiny on-disk prompts/ tree with three files."""
    (tmp_path / "planner.md").write_text("planner template\n")
    (tmp_path / "writer.md").write_text("writer template\n")
    (tmp_path / "system.md").write_text("system template\n")
    return tmp_path


def _records_for(prompts_dir: Path) -> list[PromptTemplateRecord]:
    """Build records the way the CLI will, but pointing at our temp dir."""
    from bewerbungs_agent.utils.prompt_registry import discover_prompts
    return discover_prompts(prompts_dir=prompts_dir)


# ---------------------------------------------------------------------------
# `jobagent prompts sync`
# ---------------------------------------------------------------------------


class TestPromptsSync:
    def test_exits_nonzero_without_credentials(
        self, runner: CliRunner, fake_prompts_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point the CLI at our temp prompts dir
        from bewerbungs_agent.cli import prompts_app  # noqa: F401  (ensure import)
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        result = runner.invoke(app, ["prompts", "sync"])
        assert result.exit_code == 1, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "Langfuse disabled" in combined
        assert "credentials missing" in combined

    def test_succeeds_with_mocked_client_all_new(
        self,
        runner: CliRunner,
        fake_prompts_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        # Mock the Langfuse SDK constructor so build_observability builds a
        # healthy LangfuseObservability whose underlying client is our mock.
        fake_sdk = MagicMock()

        class _NotFound(Exception):
            pass

        fake_sdk.get_prompt.side_effect = _NotFound("404")
        fake_sdk.create_prompt.return_value = MagicMock(version=1)
        monkeypatch.setattr("langfuse.Langfuse", lambda **kw: fake_sdk)

        result = runner.invoke(app, ["prompts", "sync", "--label", "staging"])
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert "Summary:" in result.stdout
        assert "3 created" in result.stdout
        assert "0 failed" in result.stdout
        assert fake_sdk.create_prompt.call_count == 3

    def test_partial_failure_exit_code_two(
        self,
        runner: CliRunner,
        fake_prompts_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        fake_sdk = MagicMock()
        class _NotFound(Exception):
            pass
        fake_sdk.get_prompt.side_effect = _NotFound("404")

        def _create(*, name: str, **kwargs: Any) -> Any:
            if "writer" in name:
                raise RuntimeError("synthetic API failure")
            return MagicMock(version=1)

        fake_sdk.create_prompt.side_effect = _create
        monkeypatch.setattr("langfuse.Langfuse", lambda **kw: fake_sdk)

        result = runner.invoke(app, ["prompts", "sync"])
        assert result.exit_code == 2, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "writer" in combined
        assert "FAILED" in combined or "failed" in combined


# ---------------------------------------------------------------------------
# `jobagent prompts list`
# ---------------------------------------------------------------------------


class TestPromptsList:
    def test_runs_locally_without_credentials(
        self,
        runner: CliRunner,
        fake_prompts_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        result = runner.invoke(app, ["prompts", "list"])
        assert result.exit_code == 0, (result.stdout, result.stderr)
        # Every discovered file appears once
        assert "planner.md" in result.stdout
        assert "writer.md" in result.stdout
        assert "system.md" in result.stdout
        # And every row carries the no-langfuse marker
        assert "no-langfuse" in result.stdout

    def test_json_output_shape(
        self,
        runner: CliRunner,
        fake_prompts_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        result = runner.invoke(app, ["prompts", "list", "--json"])
        assert result.exit_code == 0, (result.stdout, result.stderr)
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 3
        required_keys = {"file", "local_hash", "langfuse_name", "latest_version", "labels", "status"}
        for row in data:
            assert required_keys.issubset(row.keys())
            assert row["status"] == "no-langfuse"
            assert row["langfuse_name"].startswith("bewerbungs-agent/")

    def test_table_with_mocked_client_shows_up_to_date(
        self,
        runner: CliRunner,
        fake_prompts_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("BEWERBUNGS_PROMPTS_DIR", str(fake_prompts_dir))

        # Mock: every prompt has matching hash on the remote.
        records = _records_for(fake_prompts_dir)
        hash_by_name = {r.name: r.content_hash for r in records}

        fake_sdk = MagicMock()
        def _get(name: str, **kwargs: Any) -> Any:
            obj = MagicMock()
            obj.version = 1
            obj.config = {"content_hash": hash_by_name[name]}
            obj.labels = ["staging"]
            return obj
        fake_sdk.get_prompt.side_effect = _get
        monkeypatch.setattr("langfuse.Langfuse", lambda **kw: fake_sdk)

        result = runner.invoke(app, ["prompts", "list"])
        assert result.exit_code == 0, (result.stdout, result.stderr)
        # Every line should show the up-to-date status
        assert result.stdout.count("up-to-date") >= 3
