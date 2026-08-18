# Tasks: Langfuse Prompt Registry & Sync

**Input**: Design documents from `/specs/007-langfuse-prompt-registry/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: REQUIRED. Spec FR-021..FR-026 explicitly mandate automated tests, and Constitution Principle VI mandates TDD. Tests are written FIRST and MUST FAIL before the corresponding implementation task begins.

**Organization**: Tasks grouped by user story. Each story is independently testable via a mocked Langfuse client.

---

## Phase 1: Setup

**Purpose**: No new dependencies required (`langfuse>=2.0` already in pyproject.toml from feature 006). No project-structure changes. This phase is a no-op verification step.

- [X] T001 Verify `langfuse>=2.0` is present in `pyproject.toml` `dependencies` array and that `.venv/bin/python -c "import langfuse; print(langfuse.__version__)"` returns a 2.x or 4.x version; no edits needed unless missing

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Three changes ALL three user stories depend on: (1) the `STAGE_PROMPT_MAP` constant moves into a single source of truth, (2) Pydantic records for the registry exist and validate, (3) the `Observability` Protocol gains the `underlying_client()` accessor so the runtime resolver can reach Langfuse from inside `_wrap_stage`.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Write failing tests for `STAGE_PROMPT_MAP` and the four new Pydantic records in `tests/unit/test_prompt_registry.py` (start the file with just these 6 tests: `STAGE_PROMPT_MAP` contains a known set of stage keys with the correct prompt-name values; `PromptTemplateRecord` accepts a valid construction and rejects bad name regex; `PromptReference` requires `prompt_name` and `content_hash`; `SyncResult.error_message` MUST be set iff `action==failed`; `ListEntry` accepts `status=no_langfuse` with `latest_version=None`; `SyncAction` and `ListStatus` enums have the documented values)
- [X] T003 Create `src/bewerbungs_agent/utils/prompt_registry.py` with module skeleton: imports, `STAGE_PROMPT_MAP` constant, `SyncAction` enum, `ListStatus` enum, `PromptTemplateRecord` / `PromptReference` / `SyncResult` / `ListEntry` Pydantic models per data-model.md §1–§4, and the `compute_content_hash(text: str) -> str` helper that returns the 16-char SHA-256 hex prefix of `text.encode("utf-8")`
- [X] T004 Add `underlying_client(self) -> Any | None` to the `Observability` Protocol and both `NoOpObservability` (returns `None`) and `LangfuseObservability` (returns `self._client` when `self._healthy`, else `None`) in `src/bewerbungs_agent/utils/observability.py`
- [X] T005 Add `set_prompt_reference(self, reference: "PromptReference") -> None` method to the `StageSpan` Protocol, `NoOpStageSpan` (no-op pass body), and `LangfuseStageSpan` (writes `metadata={"prompt_name": ..., "prompt_version": ... or "unsynced", "prompt_content_hash": ..., "prompt_label_at_resolve": ...}` via `self._safe_update`) in `src/bewerbungs_agent/utils/observability.py` — use a `TYPE_CHECKING` forward import of `PromptReference` to avoid circularity
- [X] T006 Replace the inline `prompt_name=...` strings in `src/bewerbungs_agent/graph/workflow.py` `build_graph()` with reads from the new `STAGE_PROMPT_MAP` — import it at the top of the file; each `_wrap_stage(...)` call uses `prompt_name=STAGE_PROMPT_MAP[stage_name]`; the existing 178-test suite MUST still pass after this refactor (single-source invariant from research.md §R3 / FR-001)
- [X] T007 Confirm all tests in `tests/unit/test_prompt_registry.py` (T002) pass and the full existing suite (`.venv/bin/pytest tests/`) still reports 178+ passed

**Checkpoint**: Pydantic records validate; the stage-to-prompt mapping has one source of truth; the observability layer exposes the underlying client and a prompt-reference setter; T002 tests pass; pre-existing 178 tests still pass.

---

## Phase 3: User Story 1 — Sync Local Prompts to a Langfuse Registry (Priority: P1) 🎯 MVP

**Goal**: `jobagent prompts sync [--label LABEL]` discovers every local `prompts/**/*.md`, computes a stable content hash, compares against the latest Langfuse version, and creates a new version only when content changed. Re-runs with no changes upload nothing. One edited prompt produces one new version on that prompt.

**Independent Test**: With a mocked Langfuse client, run `sync_prompts(records, label="staging", client=mock_client)`; assert correct `SyncResult.action` per record. Run it again with identical mock state; assert all `unchanged`. Edit one record's content; assert exactly one `created`. Then test the CLI end-to-end (`CliRunner`): without credentials → exit 1; with mocked credentials → exit 0 + summary line.

### Tests for User Story 1 ⚠️ WRITE FIRST — MUST FAIL BEFORE T015

- [X] T008 [P] [US1] Write failing test `test_discover_prompts_returns_record_per_md_file` in `tests/unit/test_prompt_registry.py` — create a temp directory tree with `planner.md`, `system.md`, `styles/standard.md`, plus a stray `.hidden.md` and `_skip.md`; call `discover_prompts(prompts_dir=tmp_path)`; assert returned `PromptTemplateRecord`s correspond exactly to the three real files (hidden/underscore-prefixed are skipped), sorted by `relative_path`
- [X] T009 [P] [US1] Write failing test `test_discover_prompts_assigns_stage_from_map` in `tests/unit/test_prompt_registry.py` — create `planner.md` and `system.md`; assert the record for `planner.md` has `stage="plan_content"`, the record for `system.md` has `stage=None`
- [X] T010 [US1] Write failing test `test_compute_content_hash_stable_across_calls` in `tests/unit/test_prompt_registry.py` — same string in, same hash out, twice (FR-022 positive)
- [X] T011 [US1] Write failing test `test_compute_content_hash_differs_on_byte_change` in `tests/unit/test_prompt_registry.py` — change one byte → different hash (FR-022 negative)
- [X] T012 [US1] Write failing test `test_sync_creates_versions_first_time` in `tests/unit/test_prompt_registry.py` — mock `client.get_prompt` to raise NotFound; pass 3 records; assert `client.create_prompt` called 3 times; each `SyncResult.action == created`; each `version_after_sync == mock.version`
- [X] T013 [US1] Write failing test `test_sync_idempotent_when_no_changes` in `tests/unit/test_prompt_registry.py` — mock `client.get_prompt` to return an existing prompt whose `config["content_hash"]` matches the local record's hash and whose `labels` already includes the requested label; assert `create_prompt` NOT called; all results `unchanged` (FR-006, FR-023)
- [X] T014 [US1] Write failing test `test_sync_creates_new_version_on_change` in `tests/unit/test_prompt_registry.py` — mock `client.get_prompt` to return content_hash that differs from one record's local hash (matches for the others); assert exactly one `create_prompt` call; only that record's `SyncResult.action == created` (FR-007, FR-024)
- [X] T015 [US1] Write failing test `test_sync_moves_label_to_new_version` in `tests/unit/test_prompt_registry.py` — mock `client.get_prompt` returns matching hash but `labels=["development"]`; sync with `label="production"`; assert `client.update_prompt` called with `new_labels=["development","production"]`; result is `relabeled` (FR-008)
- [X] T016 [US1] Write failing test `test_sync_per_record_failure_does_not_abort_batch` in `tests/unit/test_prompt_registry.py` — three records; mock `create_prompt` raises `RuntimeError("API down")` on the second one only; assert results length == 3, second is `failed` with error_message containing "API down", first and third are `created` (FR-011)
- [X] T017 [US1] Write failing test `test_sync_default_label_is_staging` in `tests/unit/test_prompt_registry.py` — call `sync_prompts(records, client=mock)` without `label=` argument; assert `mock.create_prompt` was called with `labels=["staging"]` (FR-009)
- [X] T018 [P] [US1] Write failing test `test_cli_prompts_sync_exits_nonzero_without_credentials` in `tests/unit/test_cli_prompts.py` — use Typer's `CliRunner`; `monkeypatch.delenv(...)` for both credentials; invoke `prompts sync`; assert exit code 1 and stderr contains the documented "Langfuse disabled" message (FR-015, FR-025)
- [X] T019 [US1] Write failing test `test_cli_prompts_sync_succeeds_with_mocked_client` in `tests/unit/test_cli_prompts.py` — patch `build_observability` to return an observability whose `underlying_client()` returns a mock that simulates all-new prompts; invoke `prompts sync --label staging`; assert exit code 0; stdout contains "Summary:" and "created" lines (FR-010)
- [X] T020 [US1] Write failing test `test_cli_prompts_sync_partial_failure_exit_code_2` in `tests/unit/test_cli_prompts.py` — same setup as T019 but the mock raises on one specific prompt name; assert exit code 2; stdout contains the failed prompt name (FR-011)

### Implementation for User Story 1

- [X] T021 [US1] Implement `discover_prompts(prompts_dir=None, *, name_prefix="bewerbungs-agent")` in `src/bewerbungs_agent/utils/prompt_registry.py` per contracts §1 — recurse through `*.md` files (skip `.` and `_` prefixes; skip non-UTF-8 with warning), build `PromptTemplateRecord` for each via a private `_from_file(path, *, stage_map, name_prefix)` helper that reads bytes, computes hash, infers name from path stem (joining subdir names with `/`), looks up stage in `_PROMPT_TO_STAGE = {v: k for k, v in STAGE_PROMPT_MAP.items() if v is not None}`, captures git metadata via `subprocess.run(["git", "rev-parse", "HEAD"], ...)` and `subprocess.run(["git", "status", "--porcelain"], ...)` — both wrapped in try/except so non-git trees just leave fields None
- [X] T022 [US1] Implement `sync_prompts(records, *, label="staging", client)` in `src/bewerbungs_agent/utils/prompt_registry.py` per contracts §2 — per-record loop: try `client.get_prompt(record.name, cache_ttl_seconds=0)`, on the documented `NotFoundError` (or generic Exception that looks like 404) call `create_prompt(...)` with the full metadata block from data-model.md §1; on success compare `existing.config.get("content_hash")` vs `record.content_hash`; emit the right `SyncResult`; isolate per-record errors in try/except so the loop continues (FR-011)
- [X] T023 [US1] Add the `prompts` Typer sub-app to `src/bewerbungs_agent/cli.py` per research.md §R8 — create `prompts_app = typer.Typer(name="prompts", help="...", no_args_is_help=True)`; mount via `app.add_typer(prompts_app, name="prompts")`; implement `@prompts_app.command("sync")` accepting `--label` option (default `"staging"`); call `build_observability(ObservabilityConfig(langfuse=LangfuseConfig(enabled=True)))`, fetch `underlying_client()`, branch on `None` (exit 1 with the documented message) or otherwise call `discover_prompts()` → `sync_prompts(...)`; print per-record lines and summary; exit 2 if any failed
- [X] T024 [US1] Confirm all US1 tests in `tests/unit/test_prompt_registry.py` (T008–T017) and `tests/unit/test_cli_prompts.py` (T018–T020) pass; confirm the existing 178-test suite still passes

**Checkpoint**: `jobagent prompts sync` works end-to-end. Idempotence verified. Partial-failure semantics verified. Missing-creds exit code 1 verified. The MVP is shippable from here — operators can sync prompts to Langfuse with full version tracking even before US2/US3 land.

---

## Phase 4: User Story 2 — Inspect What Is Local, What Is Synced (Priority: P2)

**Goal**: `jobagent prompts list [--json]` prints one row per local prompt with its hash, the matching Langfuse name, the latest synced version, the labels on that version, and a status indicator. Works locally-only when credentials are missing.

**Independent Test**: With three records and a mocked client returning specific states (matching hash / differing hash / NotFound), call `list_prompts(records, client=mock)`; assert returned `ListEntry`s carry the documented `status` values. Then test the CLI: without credentials → exit 0 + every row shows `no-langfuse`; `--json` → parseable JSON of `ListEntry[]`.

### Tests for User Story 2 ⚠️ WRITE FIRST — MUST FAIL BEFORE T029

- [X] T025 [P] [US2] Write failing test `test_list_prompts_status_up_to_date_when_hash_matches` in `tests/unit/test_prompt_registry.py` — mock `get_prompt` returns matching content_hash; assert returned entry status == `up_to_date`
- [X] T026 [P] [US2] Write failing test `test_list_prompts_status_local_differs_when_hash_mismatches` in `tests/unit/test_prompt_registry.py` — mock `get_prompt` returns differing content_hash; assert status == `local_differs`
- [X] T027 [US2] Write failing test `test_list_prompts_status_not_synced_when_get_prompt_raises_not_found` in `tests/unit/test_prompt_registry.py` — mock `get_prompt` raises NotFound; assert status == `not_synced`; latest_version is None
- [X] T028 [US2] Write failing test `test_list_prompts_status_no_langfuse_when_client_is_none` in `tests/unit/test_prompt_registry.py` — pass `client=None`; assert every entry has status == `no_langfuse`, latest_version=None, labels=[]; no SDK call attempted (FR-013)
- [X] T029 [P] [US2] Write failing test `test_cli_prompts_list_runs_locally_without_credentials` in `tests/unit/test_cli_prompts.py` — CliRunner, no credentials env; invoke `prompts list`; assert exit code 0; stdout contains every discovered file and a `no-langfuse` indicator for each (FR-013)
- [X] T030 [US2] Write failing test `test_cli_prompts_list_json_output_shape` in `tests/unit/test_cli_prompts.py` — CliRunner; invoke `prompts list --json`; parse stdout as JSON; assert it's a list with the documented keys per entry (file, local_hash, langfuse_name, latest_version, labels, status) (FR-014)

### Implementation for User Story 2

- [X] T031 [US2] Implement `list_prompts(records, *, client=None)` in `src/bewerbungs_agent/utils/prompt_registry.py` per contracts §3 — when `client is None`, return one `ListEntry(status=no_langfuse, latest_version=None, labels=[])` per record; when `client` provided, try `client.get_prompt(record.name)` per record, on NotFound emit `not_synced`, on success compare hashes and emit `up_to_date` or `local_differs`; never raise — any SDK exception per record collapses to `not_synced` with no SDK detail leaked to stdout
- [X] T032 [US2] Implement `@prompts_app.command("list")` in `src/bewerbungs_agent/cli.py` accepting `--json / -j` option (default False); call `discover_prompts()` then `list_prompts(records, client=client_or_none)`; for `--json` mode use `json.dumps([e.model_dump(mode="json") for e in entries], indent=2)`; for table mode print the documented aligned 6-column layout per contracts §7; always exit 0 unless discovery itself failed (then exit 3)
- [X] T033 [US2] Confirm all US2 tests pass (T025–T030); confirm full test suite still passes

**Checkpoint**: `jobagent prompts list` works in both modes (with creds + without). CI integration via `--json` is functional. Operators can audit registry state without opening the Langfuse UI.

---

## Phase 5: User Story 3 — Runtime Traces Reference the Prompt Version They Used (Priority: P3)

**Goal**: Each LLM-stage Langfuse trace span (from feature 006) carries `prompt_name` + `prompt_version` (or `unsynced`) pointing at the registry entry that produced it. Resolution is cached per process — at most one Langfuse round-trip per `(name, hash)` per process. Privacy invariant from feature 006 preserved: no raw prose on spans.

**Independent Test**: Call `runtime_reference("bewerbungs-agent/planner", local_hash, client=mock)` where mock returns a matching version; assert returned `PromptReference.prompt_version == mock.version`. Call again with same args; assert `client.get_prompt` was called exactly once. Call with `client=None`; assert `prompt_version is None`. Then assert the integration test for `_wrap_stage` records both fields on the span.

### Tests for User Story 3 ⚠️ WRITE FIRST — MUST FAIL BEFORE T040

- [X] T034 [P] [US3] Write failing test `test_runtime_reference_returns_version_when_hash_matches` in `tests/unit/test_prompt_registry.py` — mock `client.get_prompt` returns `config={"content_hash": local_hash}` and `version=7`; call `runtime_reference("bewerbungs-agent/planner", local_hash, client=mock)`; assert `prompt_version == 7`, `content_hash == local_hash` (FR-017, FR-026 case 1)
- [X] T035 [P] [US3] Write failing test `test_runtime_reference_returns_none_when_hash_mismatches` in `tests/unit/test_prompt_registry.py` — mock returns `config={"content_hash": "deadbeef0000beef"}` (differs); assert `prompt_version is None` (FR-017 unsynced marker; FR-026 case 2)
- [X] T036 [US3] Write failing test `test_runtime_reference_returns_none_when_get_prompt_raises_not_found` in `tests/unit/test_prompt_registry.py` — mock raises NotFound; assert `prompt_version is None` (FR-017)
- [X] T037 [US3] Write failing test `test_runtime_reference_returns_none_without_client` in `tests/unit/test_prompt_registry.py` — call with `client=None`; assert `prompt_version is None`; no SDK call attempted (FR-016)
- [X] T038 [US3] Write failing test `test_runtime_reference_cached_after_first_lookup` in `tests/unit/test_prompt_registry.py` — `clear_cache()`; call twice with identical `(name, hash, client)`; assert `client.get_prompt` called exactly ONCE (FR-018)
- [X] T039 [US3] Write failing test `test_runtime_reference_new_hash_triggers_new_lookup` in `tests/unit/test_prompt_registry.py` — call with hash_a → 1 SDK call; call with hash_b → 1 more SDK call (cache key differs)
- [X] T040 [US3] Write failing integration test `test_full_pipeline_span_carries_prompt_reference` in `tests/integration/test_full_run.py` — extend the existing `_RecordingObservability` pattern with a `_RecordingSpan` that captures `set_prompt_reference(reference)` calls; run the full pipeline with a mocked Langfuse client whose `get_prompt` always returns matching hash + version=3; assert at least one stage span received a `PromptReference` with `prompt_version=3`; assert NO span input/output payload contains raw CV or letter prose (FR-019 privacy retained, SC-008)

### Implementation for User Story 3

- [X] T041 [US3] Implement `runtime_reference(prompt_name, local_content_hash, *, client=None)` and `clear_cache()` and the `_VERSION_CACHE` module-level dict in `src/bewerbungs_agent/utils/prompt_registry.py` per contracts §4 — cache key is `(prompt_name, local_content_hash)`; on cache hit return the stored `PromptReference`; on miss + `client is None` build `PromptReference(prompt_name, prompt_version=None, content_hash=local_content_hash, label_at_resolve=None)`, cache, return; on miss + client present try `client.get_prompt(prompt_name, cache_ttl_seconds=0)` wrapped in try/except, compare `config.get("content_hash")` to `local_content_hash`, build the appropriate `PromptReference`, cache, return; any SDK exception → cache and return the unsynced reference
- [X] T042 [US3] Wire the resolver into `_wrap_stage` in `src/bewerbungs_agent/utils/observability.py` — when the wrapper has a non-None `prompt_name`, after the existing `_compute_prompt_hash(prompt_name)` call also compute `qualified = f"bewerbungs-agent/{prompt_name}"`, fetch the Langfuse client via `obs.underlying_client()`, call `prompt_registry.runtime_reference(qualified, local_hash, client=...)`, and call `span.set_prompt_reference(reference)`; the existing `span.set_prompt(prompt_name, local_hash)` call MUST remain for backward compatibility (data-model.md §5)
- [X] T043 [US3] Confirm all US3 tests pass (T034–T040); confirm full test suite still passes; confirm `_VERSION_CACHE` is properly cleared between tests via a `clear_cache()` call in the relevant `pytest` fixtures

**Checkpoint**: Runtime stage spans now carry registry references. Cache invariant verified. Unsynced marker visible when local content drifts. Privacy invariant preserved.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T044 [P] Update `ENGINEERING.md` with a new Section 18 "Prompt Registry" describing: the `STAGE_PROMPT_MAP` single-source convention, `jobagent prompts sync --label X` workflow, `jobagent prompts list [--json]` shape, runtime cross-reference behaviour, the staging→production promotion workflow, and the disabled-mode fallbacks. Renumber the existing "Environment variables" section to 19. Update its env-vars table to note that `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` now also gate the `prompts` subcommand
- [X] T045 [P] Update `CLAUDE.md` "Active Technologies" entry for feature 007 if `update-agent-context.sh` did not already do so, to mention "Langfuse Prompt Management surface via existing langfuse>=2.0 dependency"
- [X] T046 Add `dev` extra in `pyproject.toml` for `pytest` and `pytest-mock` if missing (these are needed but the venv has them; this task is a no-op verification — confirm `.venv/bin/pytest` resolves)
- [X] T047 Run `.venv/bin/ruff check src/bewerbungs_agent/utils/prompt_registry.py src/bewerbungs_agent/cli.py src/bewerbungs_agent/utils/observability.py src/bewerbungs_agent/graph/workflow.py tests/unit/test_prompt_registry.py tests/unit/test_cli_prompts.py tests/integration/test_full_run.py` and fix any reported errors in files this feature owns
- [X] T048 Run `.venv/bin/mypy src/bewerbungs_agent/utils/prompt_registry.py src/bewerbungs_agent/cli.py src/bewerbungs_agent/utils/observability.py src/bewerbungs_agent/graph/workflow.py` and fix any reported errors in files this feature owns
- [X] T049 Final full test suite run: `.venv/bin/pytest tests/ --tb=short`; expect zero failures, total count = previous total + (US1 + US2 + US3 test counts)
- [X] T050 Run the quickstart.md §10 smoke test (or document why it's deferred to manual operator validation) — sync → idempotent re-sync → edit + sync → list → revert + list shows `local-differs` → run agent + inspect span carries `unsynced` marker

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: trivial, no real dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Phase 1. **BLOCKS all user stories.** T002 (failing tests) before T003–T006 (implementations); T007 verifies.
- **User Story 1 (Phase 3)**: depends on Phase 2 completion. T008–T020 (tests) written before T021–T023 (implementations); T024 verifies.
- **User Story 2 (Phase 4)**: depends on Phase 2 + reads `discover_prompts` from US1. Tests T025–T030 may be written in parallel with US1 implementation; cannot pass until US1's `discover_prompts` exists.
- **User Story 3 (Phase 5)**: depends on Phase 2 + needs `discover_prompts` (US1) for the integration test. Resolver itself is independent of US1/US2 implementation. Tests T034–T039 (unit) can be written + implemented in parallel with US1/US2 once Phase 2 lands; T040 (integration) needs the full graph wiring to exist.
- **Polish (Phase 6)**: depends on US1+US2+US3 completion.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle VI).
- Within US1: T021 (discovery) → T022 (sync logic) → T023 (CLI) → T024 (verify).
- Within US2: T031 (list logic) → T032 (CLI command) → T033 (verify).
- Within US3: T041 (resolver + cache) → T042 (wrapper wiring) → T043 (verify).

---

## Parallel Opportunities

```bash
# Phase 1: trivial single-task verification.

# Phase 2: tests can be written in parallel with reading the spec, but
# implementations (T003, T004, T005, T006) touch different files in dependency order:
Task T002: Write Pydantic+enum tests in tests/unit/test_prompt_registry.py
# (T003 → T004 → T005 → T006 sequential — each depends on the previous)

# Phase 3 US1 — failing tests in different files can be written in parallel:
Task T008: test_discover_prompts_returns_record_per_md_file   # tests/unit/test_prompt_registry.py
Task T018: test_cli_prompts_sync_exits_nonzero_without_credentials  # [P] — different file (tests/unit/test_cli_prompts.py)

# Phase 4 US2 — list-logic tests in test_prompt_registry.py are in the same file (sequential),
# but the CLI test (test_cli_prompts.py) is a different file:
Task T025: test_list_prompts_status_up_to_date_when_hash_matches      # [P]
Task T029: test_cli_prompts_list_runs_locally_without_credentials      # [P] — different file

# Phase 5 US3 — runtime-reference tests are all in test_prompt_registry.py (sequential),
# integration test is a different file:
Task T034: test_runtime_reference_returns_version_when_hash_matches    # [P]
Task T040: test_full_pipeline_span_carries_prompt_reference            # [P] — different file

# Phase 6: ENGINEERING.md and CLAUDE.md edits are in different files:
Task T044: Update ENGINEERING.md  # [P]
Task T045: Update CLAUDE.md       # [P]
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 1 (Setup — trivial)
2. Complete Phase 2 (Foundational) — Pydantic records + Protocol additions + STAGE_PROMPT_MAP single-source
3. Complete Phase 3 (US1) — sync + CLI sync command; operators can now register their prompts in Langfuse with idempotent uploads
4. **STOP**: registry visibility in the Langfuse UI is already useful by itself; list/runtime cross-reference can come later.

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ✓
2. Phase 3 (US1) → Operator can register prompts in Langfuse ✓
3. Phase 4 (US2) → Operator can audit registry state from the CLI / CI ✓
4. Phase 5 (US3) → Operator can navigate from any runtime trace to the exact prompt version ✓
5. Phase 6 → Docs, lint, type-check, smoke test ✓

### Parallel Team Strategy

With two contributors after Phase 2:

- Contributor A: US1 (the sync workflow, the CLI subcommand).
- Contributor B: US3 (the runtime resolver + cache + integration test) — the resolver only needs `STAGE_PROMPT_MAP` and `compute_content_hash` which are already in Phase 2.
- US2 picks up either contributor when US1's `discover_prompts` lands.

---

## Notes

- `[P]` = different files, safe to run in parallel with other [P] tasks in the same phase.
- `[USN]` = maps to user story N in spec.md.
- The `STAGE_PROMPT_MAP` move (T006) is technically a refactor of feature 006's hard-coded wiring. The existing test suite (~178 tests) MUST still pass after this move with no semantic change to the running pipeline — this is the durable guarantee that feature 007 does not alter generation (FR-020-equivalent / Principle I).
- The runtime resolver (T041) MUST NEVER raise. Any SDK exception is caught and converted to `PromptReference(prompt_version=None)` so the span gets the `unsynced` marker — never an error span (FR-017, FR-019).
- The version cache (T041) is process-local. No persistent file artefact; not thread-safe (single-threaded CLI by design).
- `_wrap_stage` MUST continue to call the existing `span.set_prompt(prompt_name, hash)` mutator from feature 006 alongside the new `span.set_prompt_reference(reference)` — backward compatibility (data-model.md §5).
- `jobagent prompts sync` exit-code taxonomy is deliberately distinct from `jobagent run`: 0 success, 1 missing creds, 2 partial Langfuse failure, 3 local discovery failure. Mirrors feature 001 CLI conventions.
- This feature does NOT support deleting Langfuse prompts, archiving versions, or A/B-testing labels — explicitly out of scope per spec Assumptions.
