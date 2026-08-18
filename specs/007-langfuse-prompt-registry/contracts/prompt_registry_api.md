# Contract: `PromptRegistry` Internal API

**Feature**: 007-langfuse-prompt-registry
**Module**: `src/bewerbungs_agent/utils/prompt_registry.py`
**Date**: 2026-05-13

The registry exposes one module and three public functions. All other symbols are implementation detail.

---

## 1. Discovery

```python
def discover_prompts(
    prompts_dir: Path | None = None,
    *,
    name_prefix: str = "bewerbungs-agent",
) -> list[PromptTemplateRecord]:
    """Walk the prompts directory and return a record per *.md file.

    Args:
        prompts_dir:  Defaults to `<package_root>/../../prompts/` (i.e. the
                      repo-root `prompts/` directory). Override for tests.
        name_prefix:  Langfuse name prefix. Default "bewerbungs-agent" gives
                      names like "bewerbungs-agent/planner". Set to "" to
                      use bare stems.

    Returns:
        One PromptTemplateRecord per discovered *.md file, sorted by
        relative_path for deterministic output. Files outside the prompts
        tree are not included.

    Behaviour:
        - Recurses into subdirectories (e.g., `styles/`).
        - Skips files starting with '.' or '_'.
        - On non-UTF-8 file: logs a warning, skips the file, continues.
        - Captures git_commit via `git rev-parse HEAD` (best-effort).
        - Captures git_dirty via `git status --porcelain` (true if any output).
        - Looks up `stage` via the inverse of STAGE_PROMPT_MAP; None when no
          stage uses the prompt directly (e.g., system.md, validator.md).
    """
```

**Invariants**:
- Pure function w.r.t. the filesystem at call time.
- Deterministic ordering.
- Never raises on a single malformed file; always returns a list.

---

## 2. Sync

```python
def sync_prompts(
    records: list[PromptTemplateRecord],
    *,
    label: str = "staging",
    client: Any | None = None,
) -> list[SyncResult]:
    """Upload or update each prompt to Langfuse.

    Args:
        records: Output of discover_prompts().
        label:   Label to apply to whichever version ends up "current"
                 after this sync (the newly-created one, or the matching
                 existing one if hash unchanged).
        client:  Langfuse SDK client. Required and non-None — when missing,
                 callers MUST short-circuit before calling this function
                 (see CLI contract §4 for the no-creds path).

    Returns:
        One SyncResult per input record, in the same order.

    Per-record behaviour:
        1. Try `client.get_prompt(record.name)`.
           - On NotFound: call create_prompt(...) with labels=[label] →
             SyncResult.created.
           - On other SDK exception: caught → SyncResult.failed with
             error_message.
        2. If existing.config.get("content_hash") == record.content_hash:
           a. If label in existing.labels → SyncResult.unchanged.
           b. Else → client.update_prompt(name, version=existing.version,
              new_labels=[*existing.labels, label]) → SyncResult.relabeled.
        3. Else (hash differs):
           call create_prompt(name, prompt=record.content, labels=[label],
                              config={...metadata...},
                              commit_message=f"sync from {record.relative_path}@{record.content_hash}")
           → SyncResult.created (with version_after_sync = client.version).

    Failure isolation:
        Any per-record SDK exception is caught; the loop continues. The
        caller sees a SyncResult.failed for the offending record and
        normal results for the rest (FR-011).
    """
```

**Metadata block written to `config`** on every `create_prompt`:

```python
{
    "stage": record.stage,                    # may be None
    "file_path": record.relative_path,
    "content_hash": record.content_hash,
    "template_format": record.template_format,
    "model": record.model,
    "schema_version": record.schema_version,
    "git_commit": record.git_commit,
    "git_dirty": record.git_dirty,
}
```

---

## 3. List

```python
def list_prompts(
    records: list[PromptTemplateRecord],
    *,
    client: Any | None = None,
) -> list[ListEntry]:
    """Build the inspection view of every discovered prompt.

    Args:
        records: Output of discover_prompts().
        client:  Langfuse SDK client, or None when credentials are missing.

    Returns:
        One ListEntry per record (in the same order), plus extra entries
        with status=local_missing for any Langfuse-side prompts that share
        the configured name prefix but have no local file.
        (Detecting local_missing is best-effort: if the SDK does not expose
        a "list all prompts" endpoint, those entries are omitted in v1.
        FR-012 names them as a desirable status; their presence is not
        required for the test suite to pass.)

    Per-record behaviour:
        - client is None → ListEntry with status=no_langfuse, latest_version=None.
        - get_prompt(name) raises NotFound → status=not_synced.
        - get_prompt(name) returns existing → compare hashes:
            existing.config.get("content_hash") == record.content_hash →
                status=up_to_date
            else → status=local_differs
        - Always sets latest_version, labels from the SDK response when
          available.
    """
```

---

## 4. Runtime resolver

```python
def runtime_reference(
    prompt_name: str,
    local_content_hash: str,
    *,
    client: Any | None = None,
) -> PromptReference:
    """Resolve a (prompt_name, local_hash) to a PromptReference.

    Args:
        prompt_name:         Already-qualified Langfuse name (e.g.,
                             "bewerbungs-agent/planner").
        local_content_hash:  16-char hex hash of the current local content.
        client:              Langfuse SDK client when available, else None.

    Returns:
        PromptReference with:
          - prompt_name = input
          - content_hash = local_content_hash
          - prompt_version = matching Langfuse version, or None when:
              * cache miss + client is None
              * client.get_prompt raises NotFound
              * cache miss + existing.config["content_hash"] != local hash
          - label_at_resolve = labels[0] from the matching version, if any.

    Caching:
        Cache key is (prompt_name, local_content_hash). First lookup with
        a non-None client may call client.get_prompt(name) once. Subsequent
        lookups for the same key return the cached PromptReference with
        zero SDK calls (FR-018).

        A different local_content_hash for the same prompt_name produces a
        NEW cache key — never a stale hit.

    Concurrency:
        Single-threaded CLI assumed. No locking; no thread-safe contract.

    Exception safety:
        Any SDK exception is caught; the returned PromptReference has
        prompt_version=None (unsynced marker). Never raises.
    """
```

```python
def clear_cache() -> None:
    """Test-only helper: empties the version cache."""
```

---

## 5. Helper: `compute_content_hash`

```python
def compute_content_hash(text: str) -> str:
    """Return a 16-char SHA-256 hex prefix of text.encode('utf-8').

    Deterministic across platforms. Identical to the algorithm used by
    feature 006's _compute_prompt_hash so local and registry hashes are
    directly comparable.
    """
```

---

## 6. CLI contract — `jobagent prompts sync`

```
$ jobagent prompts sync [--label LABEL]

Options:
  --label TEXT  Label to apply to the synced versions (default: "staging").
```

**Exit codes**:
- `0` — all discovered prompts synced (any combination of created/unchanged/relabeled).
- `1` — Langfuse credentials missing in env. Stderr message:
  `[prompts] Langfuse disabled (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY missing); nothing uploaded.`
- `2` — at least one prompt's sync failed with an upstream error.
  Stderr message lists each failure: `[prompts] FAILED: <name>: <error>`.
- `3` — discovery failed (e.g., `prompts/` directory missing or unreadable).

**Stdout format** (success):
```
[prompts] Discovered 11 local prompt files.
[prompts] CREATED   bewerbungs-agent/planner       version 1   label=staging
[prompts] UNCHANGED bewerbungs-agent/writer        version 3   label=staging
[prompts] RELABELED bewerbungs-agent/evidence      version 2   label=staging (was: development)
[prompts] CREATED   bewerbungs-agent/system        version 1   label=staging
...
[prompts] Summary: 1 created, 9 unchanged, 1 relabeled, 0 failed.
```

**No-creds output** (exit 1):
```
[prompts] Langfuse disabled (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY missing); nothing uploaded.
```

---

## 7. CLI contract — `jobagent prompts list`

```
$ jobagent prompts list [--json]

Options:
  --json  Emit JSON array instead of the aligned table.
```

**Exit codes**:
- `0` — listing succeeded (regardless of remote availability).
- `3` — local discovery failed.

**Stdout format** (default table, no Langfuse credentials):
```
FILE                          HASH      LANGFUSE NAME                       VERSION  LABELS         STATUS
prompts/planner.md            a3f9c12d  bewerbungs-agent/planner            —        —              ✗ no-langfuse
prompts/writer.md             4e2b0a91  bewerbungs-agent/writer             —        —              ✗ no-langfuse
prompts/system.md             7e8c1f23  bewerbungs-agent/system             —        —              ✗ no-langfuse
...
```

**Stdout format** (table, with credentials):
```
FILE                          HASH      LANGFUSE NAME                       VERSION  LABELS              STATUS
prompts/planner.md            a3f9c12d  bewerbungs-agent/planner            3        staging,production  ✓ up-to-date
prompts/writer.md             4e2b0a91  bewerbungs-agent/writer             7        staging             △ local-differs
prompts/system.md             7e8c1f23  bewerbungs-agent/system             —        —                   ✗ not-synced
```

**JSON output** (with `--json`):
```json
[
  {
    "file": "planner.md",
    "local_hash": "a3f9c12d4e7b8091",
    "langfuse_name": "bewerbungs-agent/planner",
    "latest_version": 3,
    "labels": ["staging", "production"],
    "status": "up-to-date"
  },
  ...
]
```

---

## 8. Runtime integration contract

`_wrap_stage` in `utils/observability.py` gains, when `prompt_name` argument is set:

```python
qualified_name = f"bewerbungs-agent/{prompt_name}"
local_hash = _compute_prompt_hash(prompt_name)
client = obs.underlying_client()
reference = prompt_registry.runtime_reference(
    qualified_name, local_hash, client=client
)
span.set_prompt_reference(reference)
```

Preconditions:
- `prompt_name` already exists in current wrapper signature.
- `obs.underlying_client()` is a new accessor returning `Any | None`.

Postconditions:
- The span carries `prompt_name`, `prompt_version` (or `unsynced`), `prompt_content_hash`, `prompt_label_at_resolve`.
- No raw prompt text is sent on the span (FR-019, SC-008).
- No per-call network round-trip after the first resolution per `(name, hash)` (FR-018).

---

## 9. Test surface implied by the contract

| Behaviour to test | Test file | Key assertion |
|---|---|---|
| Discovery enumerates every `*.md` under `prompts/` | `test_prompt_registry.py` | Set of returned names matches set of files on disk |
| Hash function stable across calls | `test_prompt_registry.py` | `compute_content_hash(x) == compute_content_hash(x)` |
| Hash function differentiates by byte | `test_prompt_registry.py` | `compute_content_hash("a") != compute_content_hash("b")` |
| Sync first time creates versions | `test_prompt_registry.py` | mocked `create_prompt` called N times; each `SyncResult.action==created` |
| Sync idempotent on unchanged content | `test_prompt_registry.py` | mock returns existing hash; `create_prompt` NOT called; results all `unchanged` |
| Sync on content change creates exactly one new version | `test_prompt_registry.py` | one record's hash differs; exactly one `create_prompt` call; that result is `created` |
| Label is moved on relabel path | `test_prompt_registry.py` | mock returns matching hash; label not in existing.labels; `update_prompt` called with new_labels |
| Per-record failure does not abort batch | `test_prompt_registry.py` | one mocked `create_prompt` raises; remaining records still produce non-failed SyncResults |
| Runtime resolver returns version on hash match | `test_prompt_registry.py` | mock returns matching config.content_hash; reference.prompt_version == mock.version |
| Runtime resolver returns None on hash mismatch | `test_prompt_registry.py` | mock returns differing hash; reference.prompt_version is None |
| Runtime resolver cached after first lookup | `test_prompt_registry.py` | call twice with same (name, hash); `client.get_prompt` called exactly once |
| Runtime resolver no-op without client | `test_prompt_registry.py` | client=None; reference.prompt_version is None; no SDK calls |
| CLI sync exits 1 without credentials | `test_cli_prompts.py` | typer CliRunner; expect exit code 1 and message |
| CLI list runs locally without credentials | `test_cli_prompts.py` | typer CliRunner; expect exit 0 and "no-langfuse" status |
| CLI list --json produces the documented shape | `test_cli_prompts.py` | parse stdout as JSON; verify keys |
| CLI sync with mocked client succeeds (exit 0) | `test_cli_prompts.py` | typer CliRunner; expect exit 0 and summary line |
| Full pipeline span carries prompt_name + prompt_version | `test_full_run.py` | recorded span has both metadata fields; privacy invariant retained |
