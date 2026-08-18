# Phase 0 Research: Langfuse Prompt Registry & Sync

**Feature**: 007-langfuse-prompt-registry
**Date**: 2026-05-13

Resolves implementation-relevant unknowns the spec deliberately left out. Does not re-litigate scope decisions documented in `spec.md > Assumptions`.

---

## R1 — Which Langfuse SDK surface does the registry call?

**Decision**: Three methods on the existing `langfuse.Langfuse` client:
- `create_prompt(name, prompt, labels, type="text", config, commit_message)` → returns a `TextPromptClient`/`ChatPromptClient` with `.version`, `.config`, `.labels`. Always creates a NEW version of the named prompt.
- `get_prompt(name, version=None, label=None, type="text", cache_ttl_seconds=0)` → fetches latest (or specific) version. Returns a prompt client with `.prompt` (text), `.version`, `.config`, `.labels`. Raises on 404.
- `update_prompt(name, version, new_labels)` → moves a label to a different version. Idempotent if `new_labels` already includes the same label.

**Rationale**:
- The SDK has no built-in "create only if content changed" semantics. We layer this client-side by calling `get_prompt(name)` first, comparing the stored hash in `config["content_hash"]` to the local hash, and only calling `create_prompt` when they differ.
- The SDK also lacks a "list all prompts" endpoint usable from `Langfuse` — but we don't need one. Our list of names is derived from the local `STAGE_PROMPT_MAP`. For each name we call `get_prompt(name)` to check existence and version.
- `update_prompt(new_labels=[...])` is the way to move labels independently of creating versions. We use it when the local content matches an existing version but the requested label isn't already on it.

**Alternatives considered**:
- `langfuse.get_prompts()` (plural) — not stable in v4 SDK; relying on the per-name path is safer.
- Direct REST calls to Langfuse — rejected; the SDK already handles auth, batching, retries.

---

## R2 — How to store the content hash on Langfuse for cheap idempotence checks?

**Decision**: Store the local content hash in `config["content_hash"]` when calling `create_prompt`. On every sync, `get_prompt(name)` returns the latest version; we read `.config.get("content_hash")` and compare to `compute_content_hash(local_text)`. If equal → skip; if absent or differing → create new version.

**Rationale**:
- The hash is in the metadata Langfuse already returns with `get_prompt`. Zero extra network calls.
- Re-hashing the returned `.prompt` text and comparing would also work, but content-normalisation (line-ending differences, encoding) could produce false mismatches; storing the canonical hash side-by-side with the content is the durable choice.
- Pre-existing prompts that lack `content_hash` (e.g., manually created in the Langfuse UI) are treated as "no match" → next sync creates a new version with the hash. This is the correct conservative behaviour.

**Alternatives considered**:
- Store the hash in `commit_message`: rejected — `commit_message` is a free-form description for humans, not structured metadata.
- Use Langfuse `tags` for the hash: rejected — tags are intended for prompt-level labels, not per-version metadata.

---

## R3 — How is the stage-to-prompt mapping kept in sync?

**Decision**: Extract the mapping into a module-level constant in `utils/prompt_registry.py`:

```python
STAGE_PROMPT_MAP: dict[str, str | None] = {
    "load_job": None,
    "extract_requirements": "requirements",
    "load_profile": None,
    "select_cv_variant": None,
    "build_evidence_map": "evidence",
    "plan_content": "planner",
    "write_letter": "writer",
    "tailor_cv": "tailor_cv",
    "hiring_review": "hiring_reviewer",
    "targeted_rewrite": "targeted_rewriter",
    "validate_outputs": None,
    "rewrite_if_needed": "writer",
}
```

`graph/workflow.py` imports this dict and threads each entry into `_wrap_stage(stage_fn, name, prompt_name=STAGE_PROMPT_MAP[name])`. The registry's `discover_prompts()` also reads this dict — adding a new stage prompt = edit one line, both sites pick it up automatically (FR-001).

**Rationale**:
- One source of truth eliminates the discovery-vs-wiring drift the spec calls out in FR-001 ("not by a hard-coded duplicate list").
- Module-level constant is simpler and faster than reflecting over workflow.py at import time.
- Stages that do not load a prompt map to `None`; the registry filters these out automatically when discovering prompts to sync.

**Alternatives considered**:
- Inspect `workflow.py` at runtime using AST parsing: rejected — fragile and expensive.
- Decorator-based stage registration: rejected — too invasive for a one-line dict.

---

## R4 — Are auxiliary prompts (`system.md`, `styles/*.md`) synced?

**Decision**: Yes. The discovery function walks `prompts/` recursively for every `*.md` file, regardless of whether the file appears in `STAGE_PROMPT_MAP`. Each discovered file becomes a registered prompt named `bewerbungs-agent/<file_stem>` (or `bewerbungs-agent/styles/<file_stem>` for nested files).

**Rationale**:
- The user explicitly listed "including planner, writer, hiring_review, requirement extraction, evidence mapping, targeted rewrite and validation prompts" — "validation" maps to `validator.md` which doesn't appear in `STAGE_PROMPT_MAP` (the validate stage is deterministic, not LLM-driven). Including it in the registry is correct: the prompt is being maintained even if not yet wired.
- Style prompts (`styles/standard.md`, `styles/aida.md`) are loaded conditionally by the writer stage. They're part of the prompt-engineering surface and benefit from registry visibility.
- `system.md` is the shared system prompt sent on every LLM call — high-leverage, definitely worth versioning.
- The runtime-resolver path (FR-017) only fires for stages that have an entry in `STAGE_PROMPT_MAP`; the extra registry entries are for sync-and-track only, not runtime span linkage.

**Alternatives considered**:
- Only sync prompts wired to a stage: rejected — losing visibility on validator/system/styles defeats the spec's stated coverage.
- Require explicit per-file opt-in via a metadata header: rejected — out of scope for v1; "every `*.md` under `prompts/`" is the simplest rule.

---

## R5 — Stable content hash function

**Decision**: Reuse the existing `_compute_prompt_hash(prompt_name)` from `utils/tracker.py` (introduced in feature 004) for the canonical hashing. Add a thin `compute_content_hash(text: str) -> str` helper in `prompt_registry.py` that hashes raw bytes the same way — `hashlib.sha256(text.encode("utf-8"))[:16].hex()`.

**Rationale**:
- FR-002 requires the local-vs-Langfuse hash comparison to be stable cross-platform. UTF-8 byte hashing is platform-independent.
- The 16-char SHA-256 prefix is already the convention used by feature 006 spans — operators comparing trace-span hashes to registry hashes will see the same shape.
- The two functions read from the same source (`prompts/<name>.md`) and use the same algorithm; a single tested helper for byte hashing serves both paths.

**Alternatives considered**:
- Full 64-char SHA-256: rejected — operators don't need 64 chars to disambiguate ~20 prompts; 16 is sufficient and matches the established convention.
- BLAKE2b: rejected — no reason to deviate from the project-wide SHA-256 choice.

---

## R6 — Runtime resolution and the version cache

**Decision**: Add `runtime_reference(prompt_name, local_hash, langfuse_client) -> PromptReference` to the registry. It returns:

```python
class PromptReference(BaseModel):
    prompt_name: str           # always set (e.g., "bewerbungs-agent/planner")
    prompt_version: int | None # None → unsynced
    content_hash: str          # the local hash (16-char hex)
    label_at_resolve: str | None  # which label currently points at the resolved version, if any
```

Cache shape: `dict[tuple[str, str], PromptReference]` keyed by `(prompt_name, local_hash)`. Lookup is lock-free (single-threaded CLI). Cache miss + Langfuse-enabled → one `get_prompt(name)` call to resolve. Cache miss + Langfuse-disabled → return `PromptReference(prompt_name, None, local_hash, None)` (unsynced marker) without any network attempt.

**Rationale**:
- FR-018: zero extra per-call network calls after the first lookup. The cache satisfies this trivially.
- A process-local in-memory cache is enough; persistent caching across processes is out of scope (spec Assumptions).
- The cache is keyed by hash so that a same-process prompt-file edit produces a new cache miss and a fresh resolution, not a stale hit.
- Returning `prompt_version=None` (rather than raising) for the unsynced case lets feature 006's `_wrap_stage` set `prompt_version=unsynced` as a plain field with no special-case error handling.

**Alternatives considered**:
- Per-stage cache attached to each `WorkflowState`: rejected — state is request-scoped; the cache benefits from process-scope.
- Persistent JSON cache file: rejected — adds an artefact to manage; v1 scope is in-memory.
- Synchronous fetch on every span: rejected — violates FR-018.

---

## R7 — How does `_wrap_stage` integrate with the resolver?

**Decision**: In feature 006's `_wrap_stage(stage_fn, stage_name, prompt_name=...)`, when `prompt_name` is set, the wrapper additionally:

1. Computes `local_hash = _compute_prompt_hash(prompt_name)` (existing function).
2. Calls `registry.runtime_reference(qualified_name, local_hash, langfuse_client_or_none)`.
3. Calls `span.set_prompt_reference(reference)` on the StageSpan (NEW thin method) which records `prompt_name`, `prompt_version`, `content_hash`, `label_at_resolve` as span metadata.

The Langfuse client is obtained from `state.observability` (already attached in feature 006) via a new `get_underlying_client()` Protocol method that returns `Any | None`. `NoOpObservability` returns `None` → resolver short-circuits to `prompt_version=None`.

**Rationale**:
- Preserves feature 006's structural invariant: stage modules know nothing about Langfuse. The new metadata flows through the existing wrapper layer.
- The new `set_prompt_reference` is a one-method extension of the `StageSpan` Protocol; the no-op span absorbs it; the Langfuse span writes it as a `metadata` field on the SDK span.
- Resolving lazily inside the wrapper means non-Langfuse runs pay zero cost.

**Alternatives considered**:
- Replace the existing `span.set_prompt(name, hash)` setter from feature 006: rejected — would break that contract. Add a new setter that supersedes it semantically (the wrapper calls only the new one when the registry is wired; falls back to the old one otherwise).
- Resolve outside `_wrap_stage` (e.g., in CLI startup): rejected — every prompt would need a Langfuse call up front even if the corresponding stage doesn't run.

---

## R8 — CLI subcommand wiring with Typer

**Decision**: Add a `typer.Typer()` sub-app and mount under the existing `app`:

```python
prompts_app = typer.Typer(
    name="prompts",
    help="Manage Langfuse prompt registry (sync + list).",
    no_args_is_help=True,
)
app.add_typer(prompts_app, name="prompts")

@prompts_app.command("sync")
def prompts_sync(label: str = typer.Option("staging", "--label"), ...) -> None: ...

@prompts_app.command("list")
def prompts_list(as_json: bool = typer.Option(False, "--json"), ...) -> None: ...
```

**Rationale**:
- Typer's `add_typer` is the idiomatic way to namespace `jobagent prompts sync` and `jobagent prompts list`.
- Existing commands (`run`, `validate`, `list-templates`, `eval`) are unaffected — they remain top-level.
- `no_args_is_help=True` produces helpful output on a bare `jobagent prompts` invocation.

**Alternatives considered**:
- Top-level `jobagent prompts-sync` / `jobagent prompts-list` flat commands: rejected — less discoverable, doesn't compose, ages poorly when more prompts-related commands are added.
- A click-style subgroup: rejected — project already standardises on Typer.

---

## R9 — Exit codes for the sync command

**Decision**:
- `0` — all prompts synced successfully (any combination of created + unchanged).
- `1` — Langfuse credentials missing (operational mistake; surfaces in CI as failure).
- `2` — one or more prompts failed to sync due to upstream errors (network, auth, validation). The summary lists each.
- `3` — discovery itself failed (e.g., `prompts/` directory missing). Hard configuration error.

`list` always exits `0` unless the local discovery itself fails (exit `3`).

**Rationale**:
- Distinct exit codes let CI scripts differentiate "credentials forgotten" from "Langfuse is down" from "code is broken". The taxonomy mirrors feature 001's CLI exit codes (`0` success, `1` validation fail, `2` file not found, `3` config error).
- Spec FR-015: missing credentials non-zero exit is explicit. Code `1` is the right choice — operational, not a code bug.

**Alternatives considered**:
- Single exit code `1` for any failure: rejected — loses signal for CI scripting.

---

## R10 — Output format for `prompts list`

**Decision**: Default = aligned ASCII table. `--json` switch emits a JSON array compatible with the `PromptTemplateRecord` schema. Both formats include every discovered local file, with the remote columns showing `(no langfuse)` when credentials are missing.

Table columns (left-to-right): `file` (relative to `prompts/`), `hash` (8-char prefix for display only), `langfuse_name`, `version` (number or `—`), `labels` (comma-joined or `—`), `status` (`✓ up-to-date` / `△ local differs` / `✗ not synced` / `! local missing` for prompts that exist in Langfuse but not on disk — known by checking `STAGE_PROMPT_MAP` against discovered files).

**Rationale**:
- Aligned table is the operator's primary surface; FR-012 specifies the required columns.
- `--json` satisfies FR-014: CI consumption.
- Showing 8-char prefix in the table (not full 16) keeps rows narrow; JSON emits full hash.
- Status indicators chosen for unambiguous parsing (one symbol + one short label).

**Alternatives considered**:
- Rich-style formatted table: rejected — adds a dependency; plain alignment is enough.
- YAML output: rejected — JSON is more universally consumable in CI scripts.

---

## R11 — Test surface mapped to spec FRs

| Test | FR(s) covered | File |
|---|---|---|
| `test_discover_prompts_matches_stage_map_and_extra_files` | FR-001, FR-021 | `tests/unit/test_prompt_registry.py` |
| `test_content_hash_stable_across_calls` | FR-002, FR-022 (positive case) | same |
| `test_content_hash_changes_on_byte_difference` | FR-002, FR-022 (negative case) | same |
| `test_sync_creates_versions_first_time` | FR-005, FR-007, FR-010 | same |
| `test_sync_idempotent_when_no_changes` | FR-006, FR-023 | same |
| `test_sync_creates_new_version_on_change` | FR-007, FR-024 | same |
| `test_sync_moves_label_to_new_version` | FR-008 | same |
| `test_sync_label_default_is_staging` | FR-009 | same |
| `test_sync_reports_partial_failures_without_aborting` | FR-011 | same |
| `test_runtime_reference_returns_version_when_synced` | FR-017, FR-026 (case 1) | same |
| `test_runtime_reference_returns_unsynced_when_no_match` | FR-017, FR-026 (case 2) | same |
| `test_runtime_reference_cached_after_first_lookup` | FR-018 | same |
| `test_runtime_reference_returns_unsynced_without_credentials` | FR-016 | same |
| `test_cli_prompts_sync_exits_nonzero_without_credentials` | FR-015, FR-025 | `tests/unit/test_cli_prompts.py` |
| `test_cli_prompts_list_runs_locally_without_credentials` | FR-013, FR-025 | same |
| `test_cli_prompts_list_json_output_shape` | FR-014 | same |
| `test_cli_prompts_sync_succeeds_with_mocked_client` | FR-005, FR-010 | same |
| `test_full_pipeline_span_carries_prompt_reference` | FR-017, FR-019 (privacy retained), FR-026 | `tests/integration/test_full_run.py` (extension) |

This matrix is the input source for `/speckit.tasks`. Every FR with a "MUST provide an automated test" clause is pinned to a concrete test.

---

## Open questions resolved during research

- "Does Langfuse v4 `create_prompt` return the version number?" — Yes, on the returned `TextPromptClient.version`. Used by `SyncResult.version_after_sync`.
- "Does `get_prompt` raise on 404 or return None?" — Raises a typed exception. Wrap in `try/except` and treat as "not yet synced".
- "Is there a rate limit on `create_prompt`?" — Yes (operator-configurable in Langfuse Cloud). For ~10–20 prompts in one sync, well under any rate threshold. No batching needed in v1.

No remaining NEEDS CLARIFICATION markers. Phase 0 complete.
