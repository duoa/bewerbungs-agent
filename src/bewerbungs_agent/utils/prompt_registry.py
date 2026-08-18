"""Langfuse Prompt Registry — feature 007.

Responsibilities:
- Discover local prompt files under ``prompts/``.
- Compute stable content hashes.
- Sync prompts to Langfuse Prompt Management with idempotent semantics
  (no duplicate version when content unchanged).
- Build an inspection view (`prompts list`).
- Resolve runtime stage spans to a Langfuse prompt name + version reference.

Stage modules and the runtime pipeline remain ignorant of this module —
integration happens via ``utils/observability._wrap_stage`` only.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import warnings
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Single source of truth: stage → prompt file stem (or None for non-LLM stages)
# ---------------------------------------------------------------------------

STAGE_PROMPT_MAP: dict[str, str | None] = {
    "load_job":             None,
    "extract_requirements": "requirements",
    "load_profile":         None,
    "select_cv_variant":    None,
    "build_evidence_map":   "evidence",
    "role_position":        "role_positioner",
    "narrative_strategy":   "narrative_strategist",
    "plan_content":         "planner",
    "write_letter":         "writer",
    "story_polish":         "story_polisher",
    "tailor_cv":            "tailor_cv",
    "hiring_review":        "hiring_reviewer",
    "targeted_rewrite":     "targeted_rewriter",
    "validate_outputs":     None,
    "rewrite_if_needed":    "writer",
}

# Inverse mapping (prompt stem → stage). Built once.
_PROMPT_TO_STAGE: dict[str, str] = {
    v: k for k, v in STAGE_PROMPT_MAP.items() if v is not None
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SyncAction(str, Enum):
    created = "created"
    unchanged = "unchanged"
    relabeled = "relabeled"
    failed = "failed"


class ListStatus(str, Enum):
    up_to_date = "up-to-date"
    local_differs = "local-differs"
    not_synced = "not-synced"
    no_langfuse = "no-langfuse"
    local_missing = "local-missing"


# ---------------------------------------------------------------------------
# Pydantic records
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_HASH_RE = re.compile(r"^[0-9a-f]{16}$")


class PromptTemplateRecord(BaseModel):
    """Everything we know about ONE local prompt template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    stage: str | None
    path: Path
    relative_path: str

    content: str
    content_hash: str

    template_format: str = "markdown"
    model: str | None = None
    schema_version: str | None = None
    git_commit: str | None = None
    git_dirty: bool = False

    labels: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"invalid prompt name: {v!r}")
        return v

    @field_validator("content_hash")
    @classmethod
    def _check_hash(cls, v: str) -> str:
        if not _HASH_RE.match(v):
            raise ValueError(f"content_hash must be 16-char lowercase hex; got {v!r}")
        return v

    @field_validator("relative_path")
    @classmethod
    def _check_relative_path(cls, v: str) -> str:
        if not v.startswith("prompts/"):
            raise ValueError(f"relative_path must start with 'prompts/'; got {v!r}")
        return v


class PromptReference(BaseModel):
    """Returned by ``runtime_reference``. Attached to LLM-stage trace spans."""

    model_config = ConfigDict(extra="forbid")

    prompt_name: str
    content_hash: str
    prompt_version: int | None = None
    label_at_resolve: str | None = None


class SyncResult(BaseModel):
    """Per-prompt outcome of one ``sync_prompts`` call."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action: SyncAction
    version_after_sync: int | None = None
    label_applied: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _check_error_consistency(self) -> "SyncResult":
        if self.action == SyncAction.failed:
            if not self.error_message:
                raise ValueError("error_message MUST be set when action == failed")
            if self.version_after_sync is not None:
                raise ValueError("version_after_sync MUST be None when action == failed")
        else:
            if self.error_message is not None:
                raise ValueError(
                    f"error_message MUST be None when action != failed (action={self.action})"
                )
        return self


class ListEntry(BaseModel):
    """One row of the ``prompts list`` output."""

    model_config = ConfigDict(extra="forbid")

    file: str
    local_hash: str | None
    langfuse_name: str
    latest_version: int | None = None
    labels: list[str] = Field(default_factory=list)
    status: ListStatus


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


def compute_content_hash(text: str) -> str:
    """Return a 16-char SHA-256 hex prefix of ``text.encode('utf-8')``.

    Cross-platform stable. Matches the algorithm in
    ``utils/tracker._compute_prompt_hash`` so local and registry hashes are
    directly comparable.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _default_prompts_dir() -> Path:
    """Locate the repo's prompts/ directory (sibling of `src/`)."""
    # This file lives at .../src/bewerbungs_agent/utils/prompt_registry.py
    # repo root is three parents up; prompts/ is at repo_root/prompts.
    return Path(__file__).resolve().parents[3] / "prompts"


def _git_metadata(cwd: Path) -> tuple[str | None, bool]:
    """Return (short_commit_sha or None, dirty_flag).

    Both subprocess calls are wrapped in try/except — non-git trees just
    leave fields None / False.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None, False

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        dirty = bool(status.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        dirty = False

    return commit or None, dirty


def _record_from_file(
    path: Path,
    *,
    prompts_root: Path,
    name_prefix: str,
) -> PromptTemplateRecord | None:
    """Build a PromptTemplateRecord from one .md file. Returns None on skip."""
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        warnings.warn(
            f"prompt_registry: skipping {path} ({type(exc).__name__}: {exc})",
            stacklevel=2,
        )
        return None

    rel_to_root = path.relative_to(prompts_root)
    # Compose the Langfuse name from the path under prompts_root, dropping the
    # .md suffix. e.g. styles/standard.md → bewerbungs-agent/styles/standard.
    name_suffix = str(rel_to_root.with_suffix("")).replace("\\", "/")
    name = f"{name_prefix}/{name_suffix}" if name_prefix else name_suffix

    stage = _PROMPT_TO_STAGE.get(rel_to_root.stem)
    git_commit, git_dirty = _git_metadata(prompts_root)

    # Default model is the production Anthropic model used by feature 006.
    # Non-LLM stages don't have a model; we still capture it for visibility.
    model: str | None = None
    if stage is not None:
        try:
            from bewerbungs_agent.utils.llm_client import AnthropicLLMClient
            model = AnthropicLLMClient.MODEL
        except Exception:  # noqa: BLE001
            model = None

    return PromptTemplateRecord(
        name=name,
        stage=stage,
        path=path,
        relative_path=f"prompts/{rel_to_root.as_posix()}",
        content=content,
        content_hash=compute_content_hash(content),
        template_format="markdown",
        model=model,
        schema_version=None,
        git_commit=git_commit,
        git_dirty=git_dirty,
    )


def discover_prompts(
    prompts_dir: Path | None = None,
    *,
    name_prefix: str = "bewerbungs-agent",
) -> list[PromptTemplateRecord]:
    """Walk the prompts directory and return a record per ``*.md`` file.

    Recurses into subdirectories. Skips dot- and underscore-prefixed files.
    Returns [] when prompts_dir does not exist. Sorted by relative_path.
    """
    root = prompts_dir if prompts_dir is not None else _default_prompts_dir()
    if not root.is_dir():
        return []

    records: list[PromptTemplateRecord] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith(".") or path.name.startswith("_"):
            continue
        if not path.is_file():
            continue
        rec = _record_from_file(path, prompts_root=root, name_prefix=name_prefix)
        if rec is not None:
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _is_not_found(exc: BaseException) -> bool:
    """Heuristic: does this exception look like a Langfuse 404?"""
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    return (
        "notfound" in name
        or "not_found" in name
        or "404" in msg
        or "not found" in msg
    )


def _build_config_metadata(record: PromptTemplateRecord) -> dict[str, Any]:
    return {
        "stage": record.stage,
        "file_path": record.relative_path,
        "content_hash": record.content_hash,
        "template_format": record.template_format,
        "model": record.model,
        "schema_version": record.schema_version,
        "git_commit": record.git_commit,
        "git_dirty": record.git_dirty,
    }


def sync_prompts(
    records: list[PromptTemplateRecord],
    *,
    label: str = "staging",
    client: Any,
) -> list[SyncResult]:
    """Upload or update each prompt to Langfuse. See contracts §2.

    Per-record errors are caught; the loop continues. The returned list has
    one SyncResult per input record in the same order.
    """
    if client is None:
        raise ValueError("sync_prompts requires a non-None Langfuse client")

    results: list[SyncResult] = []
    for record in records:
        try:
            try:
                existing = client.get_prompt(record.name, label="latest", cache_ttl_seconds=0)
                existing_found = True
            except BaseException as exc:  # noqa: BLE001
                if _is_not_found(exc):
                    existing = None
                    existing_found = False
                else:
                    raise

            if existing_found and existing is not None:
                remote_hash = (getattr(existing, "config", None) or {}).get("content_hash")
                if remote_hash == record.content_hash:
                    # Hash matches; check label
                    existing_labels = list(getattr(existing, "labels", []) or [])
                    if label in existing_labels:
                        results.append(SyncResult(
                            name=record.name,
                            action=SyncAction.unchanged,
                            version_after_sync=existing.version,
                            label_applied=label,
                        ))
                    else:
                        new_labels = [*existing_labels, label]
                        client.update_prompt(
                            name=record.name,
                            version=existing.version,
                            new_labels=new_labels,
                        )
                        results.append(SyncResult(
                            name=record.name,
                            action=SyncAction.relabeled,
                            version_after_sync=existing.version,
                            label_applied=label,
                        ))
                    continue

            # Either no existing prompt or remote hash differs → create new version.
            created = client.create_prompt(
                name=record.name,
                prompt=record.content,
                labels=[label],
                type="text",
                config=_build_config_metadata(record),
                commit_message=f"sync from {record.relative_path}@{record.content_hash}",
            )
            results.append(SyncResult(
                name=record.name,
                action=SyncAction.created,
                version_after_sync=getattr(created, "version", None),
                label_applied=label,
            ))
        except BaseException as exc:  # noqa: BLE001
            results.append(SyncResult(
                name=record.name,
                action=SyncAction.failed,
                version_after_sync=None,
                error_message=f"{type(exc).__name__}: {exc}",
            ))

    return results


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def list_prompts(
    records: list[PromptTemplateRecord],
    *,
    client: Any | None = None,
) -> list[ListEntry]:
    """Build the inspection view of every discovered prompt. See contracts §3."""
    entries: list[ListEntry] = []
    for record in records:
        # Strip the leading "prompts/" for display brevity in the `file` column.
        file_display = record.relative_path[len("prompts/"):]

        if client is None:
            entries.append(ListEntry(
                file=file_display,
                local_hash=record.content_hash,
                langfuse_name=record.name,
                latest_version=None,
                labels=[],
                status=ListStatus.no_langfuse,
            ))
            continue

        try:
            existing = client.get_prompt(record.name, label="latest", cache_ttl_seconds=0)
        except BaseException as exc:  # noqa: BLE001
            if _is_not_found(exc):
                entries.append(ListEntry(
                    file=file_display,
                    local_hash=record.content_hash,
                    langfuse_name=record.name,
                    latest_version=None,
                    labels=[],
                    status=ListStatus.not_synced,
                ))
            else:
                # Treat any other SDK failure conservatively as not_synced;
                # no leakage of SDK exception detail to the table.
                entries.append(ListEntry(
                    file=file_display,
                    local_hash=record.content_hash,
                    langfuse_name=record.name,
                    latest_version=None,
                    labels=[],
                    status=ListStatus.not_synced,
                ))
            continue

        remote_hash = (getattr(existing, "config", None) or {}).get("content_hash")
        labels = list(getattr(existing, "labels", []) or [])
        version = getattr(existing, "version", None)
        if remote_hash == record.content_hash:
            status = ListStatus.up_to_date
        else:
            status = ListStatus.local_differs

        entries.append(ListEntry(
            file=file_display,
            local_hash=record.content_hash,
            langfuse_name=record.name,
            latest_version=version,
            labels=labels,
            status=status,
        ))

    return entries


# ---------------------------------------------------------------------------
# Runtime resolver + cache
# ---------------------------------------------------------------------------


_VERSION_CACHE: dict[tuple[str, str], PromptReference] = {}


def clear_cache() -> None:
    """Empty the process-local version cache (test helper)."""
    _VERSION_CACHE.clear()


def runtime_reference(
    prompt_name: str,
    local_content_hash: str,
    *,
    client: Any | None = None,
) -> PromptReference:
    """Resolve (prompt_name, local_hash) → PromptReference. See contracts §4.

    First call with a non-None client may invoke ``client.get_prompt(...)``
    once. Subsequent calls with the same key return the cached reference.
    Never raises.
    """
    key = (prompt_name, local_content_hash)
    cached = _VERSION_CACHE.get(key)
    if cached is not None:
        return cached

    if client is None:
        ref = PromptReference(
            prompt_name=prompt_name,
            content_hash=local_content_hash,
            prompt_version=None,
            label_at_resolve=None,
        )
        _VERSION_CACHE[key] = ref
        return ref

    try:
        existing = client.get_prompt(prompt_name, label="latest", cache_ttl_seconds=0)
    except BaseException:  # noqa: BLE001
        ref = PromptReference(
            prompt_name=prompt_name,
            content_hash=local_content_hash,
            prompt_version=None,
            label_at_resolve=None,
        )
        _VERSION_CACHE[key] = ref
        return ref

    remote_hash = (getattr(existing, "config", None) or {}).get("content_hash")
    labels = list(getattr(existing, "labels", []) or [])
    version = getattr(existing, "version", None)

    if remote_hash == local_content_hash and version is not None:
        ref = PromptReference(
            prompt_name=prompt_name,
            content_hash=local_content_hash,
            prompt_version=int(version),
            label_at_resolve=labels[0] if labels else None,
        )
    else:
        ref = PromptReference(
            prompt_name=prompt_name,
            content_hash=local_content_hash,
            prompt_version=None,
            label_at_resolve=None,
        )

    _VERSION_CACHE[key] = ref
    return ref
