# Phase 1 Data Model: Langfuse Prompt Registry & Sync

**Feature**: 007-langfuse-prompt-registry
**Date**: 2026-05-13

Four new typed records live in `src/bewerbungs_agent/utils/prompt_registry.py`. No existing models are modified except `StageSpan` in `utils/observability.py`, which gains one new mutator.

---

## 1. `PromptTemplateRecord` — discovered local prompt + collected metadata

```python
class PromptTemplateRecord(BaseModel):
    """Everything we know about ONE local prompt template.

    Produced by ``discover_prompts()``. Consumed by ``sync_prompts()``
    and ``list_prompts()``.
    """
    model_config = ConfigDict(extra="forbid")

    # Identity
    name: str                          # e.g., "bewerbungs-agent/planner"
    stage: str | None                  # stage that loads it, or None for shared/auxiliary (system.md, styles/*.md)
    path: Path                         # absolute path on disk
    relative_path: str                 # repo-root-relative path for display

    # Content
    content: str                       # full UTF-8 text of the file
    content_hash: str                  # 16-char SHA-256 prefix of content.encode("utf-8")

    # Metadata (sent to Langfuse via create_prompt(config=...))
    template_format: str = "markdown"
    model: str | None = None           # e.g., "claude-sonnet-4-6"; None for non-LLM prompts
    schema_version: str | None = None  # reserved for future use; None today
    git_commit: str | None = None      # short HEAD SHA, or None outside a git tree
    git_dirty: bool = False            # True when working tree has uncommitted changes

    # Labels to apply on next sync (filled by caller, not by discovery)
    labels: list[str] = Field(default_factory=list)
```

**Validation rules**:
- `content_hash` regex: `^[0-9a-f]{16}$`.
- `name` regex: `^[A-Za-z0-9._/-]+$` (Langfuse-safe).
- `relative_path` MUST start with `prompts/` (defensive — prevents accidental sync of files outside the prompts tree).

**Construction**:
- `PromptTemplateRecord.from_file(path: Path, *, stage_map: dict[str, str | None]) -> PromptTemplateRecord` — reads bytes, computes hash, infers `name`, looks up `stage` from `STAGE_PROMPT_MAP` (or `None`), captures git metadata via `git rev-parse HEAD` + `git status --porcelain`.

---

## 2. `PromptReference` — runtime resolver output

```python
class PromptReference(BaseModel):
    """Returned by ``PromptRegistry.runtime_reference(...)``.

    Attached to LLM-stage trace spans by feature 006's ``_wrap_stage``.
    """
    model_config = ConfigDict(extra="forbid")

    prompt_name: str                   # e.g., "bewerbungs-agent/planner"
    content_hash: str                  # local hash, 16-char hex
    prompt_version: int | None         # Langfuse version number; None ⇒ unsynced
    label_at_resolve: str | None = None  # label currently pointing at this version (informational)
```

**Semantics**:
- `prompt_version=None` is the "unsynced" marker (FR-017). Callers MUST render it as the string `"unsynced"` in spans.
- `label_at_resolve` is best-effort: when the version was resolved via `get_prompt(name)` it's set to the most-recent matching label; when resolved via cache hit, it's preserved from the original lookup.

---

## 3. `SyncResult` — per-prompt outcome of one sync invocation

```python
class SyncAction(str, Enum):
    created   = "created"     # new Langfuse version was created
    unchanged = "unchanged"   # hash matched the latest version; nothing uploaded
    relabeled = "relabeled"   # unchanged content, but the --label was moved onto this version
    failed    = "failed"      # upstream error; see error_message


class SyncResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    action: SyncAction
    version_after_sync: int | None      # None when action == failed
    label_applied: str | None = None    # populated for created/relabeled
    error_message: str | None = None    # populated for failed only
```

**Validation rules**:
- `error_message` MUST be non-None iff `action == failed`.
- `version_after_sync` MUST be non-None iff `action ∈ {created, unchanged, relabeled}`.

---

## 4. `ListEntry` — `prompts list` row record

```python
class ListStatus(str, Enum):
    up_to_date     = "up-to-date"
    local_differs  = "local-differs"
    not_synced     = "not-synced"
    no_langfuse    = "no-langfuse"   # credentials missing; can't determine remote
    local_missing  = "local-missing" # synced previously but file gone from disk


class ListEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str                          # relative path under prompts/ (e.g., "planner.md")
    local_hash: str | None             # 16-char hex; None when file is missing
    langfuse_name: str
    latest_version: int | None         # None when never synced or langfuse missing
    labels: list[str] = Field(default_factory=list)
    status: ListStatus
```

The CLI serialises a `list[ListEntry]` to JSON (with `--json`) or formats it into the tabular layout.

---

## 5. Modification to `StageSpan` Protocol (`utils/observability.py`)

One new method added — backward-compatible.

```python
class StageSpan(Protocol):
    # ... existing methods unchanged ...

    def set_prompt_reference(self, reference: PromptReference) -> None:
        """Attach a Langfuse prompt registry reference to this span.

        For NoOpStageSpan: no-op.
        For LangfuseStageSpan: writes
            metadata={
                "prompt_name": reference.prompt_name,
                "prompt_version": reference.prompt_version or "unsynced",
                "prompt_content_hash": reference.content_hash,
                "prompt_label_at_resolve": reference.label_at_resolve,
            }
        on the SDK span.
    """
```

Feature 006's existing `set_prompt(prompt_name, prompt_hash)` mutator is retained for backward compatibility, but `_wrap_stage` will prefer `set_prompt_reference` when a `PromptReference` is available (i.e., always when `prompt_name` is set). The two mutators are semantically equivalent — only the field shape differs (the new one adds `prompt_version`).

---

## 6. `Observability` Protocol gains one accessor

```python
class Observability(Protocol):
    # ... existing methods unchanged ...

    def underlying_client(self) -> Any | None:
        """Return the underlying SDK client, or None when disabled.

        Used by the prompt registry's runtime resolver to call get_prompt(...)
        on a cache miss. NoOpObservability returns None ⇒ resolver short-circuits
        to PromptReference(prompt_version=None).
        """
```

Implementations:
- `NoOpObservability.underlying_client()` → `None`.
- `LangfuseObservability.underlying_client()` → `self._client` (the `Langfuse` instance) when `self._healthy`; otherwise `None`.

---

## 7. Module-level constant: `STAGE_PROMPT_MAP`

Lives in `utils/prompt_registry.py`. Single source of truth for "which prompt file does each stage load?".

```python
STAGE_PROMPT_MAP: dict[str, str | None] = {
    "load_job":            None,
    "extract_requirements": "requirements",
    "load_profile":        None,
    "select_cv_variant":   None,
    "build_evidence_map":  "evidence",
    "plan_content":        "planner",
    "write_letter":        "writer",
    "tailor_cv":           "tailor_cv",
    "hiring_review":       "hiring_reviewer",
    "targeted_rewrite":    "targeted_rewriter",
    "validate_outputs":    None,
    "rewrite_if_needed":   "writer",
}
```

- Both `graph/workflow.py` and the registry import this dict (FR-001 single-source invariant).
- Discovery walks `prompts/**/*.md`, builds a record per file, and uses the inverse mapping `prompt_file_stem → stage` to populate `PromptTemplateRecord.stage`.
- Files with no entry in the inverse map (e.g., `system.md`, `validator.md`, `styles/standard.md`) get `stage = None` — still synced, just not stage-bound at runtime.

---

## 8. Module-level cache for runtime resolution

```python
# In utils/prompt_registry.py
_VERSION_CACHE: dict[tuple[str, str], PromptReference] = {}
```

- Key: `(prompt_name, local_content_hash)`.
- Value: the `PromptReference` last resolved for that key.
- Lifetime: process (cleared on process exit; not persisted).
- Concurrency: single-threaded CLI, no lock needed.
- `clear_cache()` helper exposed for tests.

---

## 9. Configuration model

No new fields on `MergedConfig` or `StarterTemplate`. The registry reads:
- The existing `observability.langfuse.enabled` flag and credentials (from `utils/observability.build_observability(...)`).
- Environment variables `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (already documented in feature 006).

The CLI subcommand builds its own `Langfuse` client directly (via `build_observability(ObservabilityConfig(langfuse=LangfuseConfig(enabled=True)))` and then `obs.underlying_client()`) — no `WorkflowState` needed.

---

## 10. Backward-compatibility audit

- Existing `WorkflowState`: unchanged.
- Existing prompt loading (`utils/prompts.load_prompt`): unchanged. Local files remain canonical (FR-020).
- Existing stage modules: unchanged.
- Existing observability span shape: only additive (`set_prompt_reference` new method, NoOpStageSpan absorbs it).
- Existing CLI commands (`run`, `validate`, `list-templates`, `eval`): unchanged. `jobagent prompts ...` is purely additive.
- Existing config YAML: unchanged. No new fields required (registry uses feature 006's `observability.langfuse.*` block).

No migration step required.

---

## 11. State transitions for `SyncAction`

```
                        ┌─ get_prompt(name) succeeds ──────────────┐
                        │                                          │
                        ▼                                          │
                  hash matches latest?                             │
                  /              \                                 │
              yes /                \ no                             │
                 ▼                  ▼                              │
   label already on this version?    create_prompt(...)            │
        /        \                  └─▶ SyncAction.created         │
       yes        no                                               │
        ▼         ▼                                                │
  unchanged   update_prompt(new_labels)                            │
                  └─▶ SyncAction.relabeled                         │
                                                                   │
                        ┌──────────────── 404 / NotFound ◀─────────┘
                        ▼
                  create_prompt(...) → SyncAction.created (version 1)
```

Failure path: any SDK exception inside the try-block above → caught, recorded as `SyncAction.failed` with the upstream message; the per-prompt loop continues (FR-011).
