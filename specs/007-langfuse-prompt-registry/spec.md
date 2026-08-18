# Feature Specification: Langfuse Prompt Registry & Sync

**Feature Branch**: `007-langfuse-prompt-registry`
**Created**: 2026-05-13
**Status**: Draft
**Input**: User description: "Add Langfuse Prompt Management for all local prompt templates in the application. The goal is to track and version prompt templates in Langfuse, not to log full runtime inputs and outputs. Add a prompt registry feature that can discover all local prompt template files, including planner, writer, hiring_review, requirement extraction, evidence mapping, targeted rewrite and validation prompts, compute a stable content hash for each template, and sync them to Langfuse Prompt Management as named prompts. Each synced prompt must include metadata such as local file path, stage name, content hash, template format, model config if available, schema version if available, and git commit hash if available. If a prompt with the same name and content hash already exists, do not create a duplicate version. If the content changed, create a new Langfuse prompt version and apply a configurable label such as staging, development or production. Add a CLI command such as jobagent prompts sync --label staging that uploads or updates all prompt templates. Add another command such as jobagent prompts list that shows local prompt files, hashes, Langfuse prompt names, latest synced version and label status. Runtime tracing should only reference the Langfuse prompt object or prompt name/version used for each LLM stage; it must not log full CV, profile, job description, cover letter drafts, or raw prompt-filled inputs by default. Keep local prompt files as the source of truth initially. Langfuse is used for version tracking, comparison and prompt registry visibility. The feature must be optional and must degrade to local-only behavior when Langfuse credentials are missing. Add tests for prompt discovery, hash stability, duplicate prevention, changed prompt version creation, missing credentials no-op behavior, and runtime stage metadata referencing the correct prompt name and version."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Sync Local Prompts to a Langfuse Registry (Priority: P1) 🎯 MVP

A prompt engineer working on the agent's templates wants a record of every prompt change in one place — when a teammate edits `planner.md`, both can see in Langfuse that a new version landed, what it says, and when. The engineer runs `jobagent prompts sync --label staging` from their working tree. The command finds every prompt file the agent uses, hashes each, uploads any new content as a new version of a named prompt in Langfuse, and moves the `staging` label to the newly-synced version. Re-running the same command immediately afterwards uploads nothing — every hash already matches the latest Langfuse version. Editing one file and re-running creates exactly one new version on Langfuse for that one prompt.

**Why this priority**: This is the foundation. Without a working sync command, there is no registry to inspect, no version history to compare against, and no metadata for runtime traces to reference. Idempotence (no duplicate versions when nothing changed) is essential; without it the registry fills with noise.

**Independent Test**: Point the CLI at a Langfuse project (real or mocked), run `jobagent prompts sync --label staging` from a clean working tree, confirm every prompt file is present as a Langfuse prompt with the expected content. Run it again, confirm zero new versions. Edit one file, run again, confirm exactly one new version on exactly that prompt and that the `staging` label now points to it.

**Acceptance Scenarios**:

1. **Given** a project with N local prompt files and no prior sync history, **When** the engineer runs `jobagent prompts sync --label staging`, **Then** N named Langfuse prompts exist, each at version 1, each carrying the documented metadata (local file path, stage name, content hash, template format, model name, git commit hash), and the `staging` label points at each version 1.
2. **Given** the same project where every local file is byte-identical to its latest Langfuse version, **When** the engineer re-runs the sync, **Then** zero new Langfuse versions are created, the existing label assignments are unchanged, and the command exits with a "0 prompts changed" summary.
3. **Given** exactly one local file has been edited since the last sync, **When** the engineer runs the sync with `--label production`, **Then** exactly one new Langfuse version is created (for that prompt only), the `production` label moves from the previous version to the new one, and unedited prompts remain at their previous version with whatever labels they already had.
4. **Given** no Langfuse credentials are configured, **When** the engineer runs the sync, **Then** the command exits cleanly with a clear "Langfuse disabled (credentials missing); nothing uploaded" message and a non-zero status to signal that no upload happened — the local working tree is unaffected.

---

### User Story 2 — Inspect What Is Local, What Is Synced (Priority: P2)

The same engineer wants to know, at a glance, which of their local prompts have been synced, which have changed since the last sync, and which labels point where. They run `jobagent prompts list`. The command prints one row per local prompt file showing: filename, short hash of local content, the matching Langfuse prompt name, the latest synced version, the labels pointing at that version, and a clear flag when the local content differs from the latest synced version.

**Why this priority**: P1 makes the registry usable; P2 makes it auditable. Without a list view, the only way to check sync state is to open Langfuse in a browser and cross-reference each prompt manually. P2 closes that loop.

**Independent Test**: Set up a project with three prompts, sync two of them, edit one of the synced two locally, leave the third unsynced. Run `jobagent prompts list`. Confirm each prompt row reports the correct state — "synced & up-to-date" for the unmodified one, "synced but local differs" for the edited one, and "not synced" for the third.

**Acceptance Scenarios**:

1. **Given** every local prompt is in sync with its latest Langfuse version, **When** the engineer runs `jobagent prompts list`, **Then** every row shows the local hash, the matching Langfuse prompt name, the latest version number, the labels on that version, and a "✓ up-to-date" indicator.
2. **Given** one local prompt has been edited since the last sync, **When** the engineer runs `jobagent prompts list`, **Then** that prompt's row shows "△ local differs" along with both the local and remote hash prefixes so the engineer can spot which side is ahead.
3. **Given** a local prompt file has never been synced, **When** the engineer runs `jobagent prompts list`, **Then** its row shows "✗ not synced" and a hint to run `jobagent prompts sync` to upload it.
4. **Given** Langfuse credentials are missing, **When** the engineer runs `jobagent prompts list`, **Then** every row still shows local file and local hash, the remote columns show "—" or "(no langfuse)", and the command exits 0 — local-only inspection still works.

---

### User Story 3 — Runtime Traces Reference the Prompt Version They Used (Priority: P3)

When a real `jobagent run` executes, each LLM-calling stage produces a Langfuse trace span (this already exists from feature 006). That span should now also point back to the specific Langfuse prompt name and version it loaded — so the engineer reading a six-week-old trace can immediately answer "which planner prompt produced this letter?" by clicking through to the registry.

The runtime continues to load prompts from local files (local stays the source of truth). The span gains two structured fields: `prompt_name` (the registry name) and `prompt_version` (the version number whose content hash matches the local file currently in use). When the local file does not match any synced Langfuse version, `prompt_version` is recorded as `unsynced` so the gap is visible in the trace rather than silently hidden.

**Why this priority**: P3 closes the loop between the registry (P1+P2) and the existing runtime observability (feature 006). It is not required to make the registry functional; without it, traces still show prompt content hashes that an engineer can manually match against the registry. With it, the navigation is a click instead of a copy-paste.

**Independent Test**: Sync a prompt to Langfuse (version 1, `staging` label). Run the agent end-to-end with a mocked Langfuse client. Inspect the span for the stage that used that prompt. Confirm the span carries `prompt_name=...` and `prompt_version=1`. Then edit the local prompt, do not re-sync, run again. Confirm the span now carries `prompt_version=unsynced` (or a similar explicit marker) and a freshly computed local content hash.

**Acceptance Scenarios**:

1. **Given** a prompt has been synced to Langfuse and the local file is unchanged, **When** the agent runs an LLM stage that uses that prompt, **Then** the stage's Langfuse trace span carries the `prompt_name` and the `prompt_version` matching the synced version.
2. **Given** a local prompt has been edited but not synced, **When** the agent runs the stage using it, **Then** the span carries the `prompt_name` of the most recently synced version and an explicit `prompt_version` marker indicating the local file is not currently registered.
3. **Given** the project has never synced any prompt, **When** the agent runs any LLM stage, **Then** spans carry `prompt_name` only (derived from the stage's prompt file name) and `prompt_version=unsynced`; the run completes normally.
4. **Given** the runtime is configured in default privacy mode (feature 006), **When** any LLM stage's span is inspected, **Then** the span carries the prompt name and version reference, the existing summary metadata, and NO raw CV, profile, job description, or letter prose — the new fields do not loosen the existing privacy default.

---

### Edge Cases

- A prompt file is added between syncs: discovered on the next sync, registered as a new Langfuse prompt at version 1.
- A prompt file is deleted locally: Langfuse keeps the registered prompt and its history. The list view shows the deleted local prompt as "(no longer present locally)" so the gap is not silent. Out-of-scope for this feature: removing or archiving the Langfuse-side prompt.
- A prompt file is renamed locally: treated as a delete + add, producing a new Langfuse prompt under the new name. The old name is left intact in Langfuse for historical traceability; no automatic re-link.
- Two different files have identical content (rare): each remains a distinct Langfuse prompt; identical content does not collapse them.
- The git working tree is dirty when sync runs: the recorded git commit hash is the most recent HEAD commit, with an explicit `dirty=true` flag in the metadata so reviewers know the synced content was not from a clean commit.
- Langfuse is reachable but the project's API key has been revoked: the first sync call fails clearly with the upstream error; the engineer sees the failure and can retry. No partial sync state is left around.
- Network failure mid-sync after some prompts have been uploaded: already-uploaded prompts stay; the failed ones are clearly reported. Re-running picks up where it left off (idempotent per-prompt, so no duplicate versions for the ones that succeeded).
- The Langfuse-side prompt has been edited directly in the Langfuse UI by another engineer (drift): the next local sync will overwrite the label and create a new version from the local content. The previous edit remains in version history but loses the label. (Local is the source of truth, per the description.)
- A prompt file contains non-UTF-8 bytes: discovery skips the file and reports it as malformed; remaining prompts sync normally.

## Requirements *(mandatory)*

### Functional Requirements

#### Discovery & hashing

- **FR-001**: The system MUST discover all prompt template files the agent uses, including (but not limited to) the planner, writer, hiring-review, requirement-extraction, evidence-mapping, targeted-rewrite, and validation prompts. Discovery MUST be driven by inspection of the agent's actual stage-to-prompt mapping, not by a hard-coded duplicate list, so adding a new stage prompt is picked up automatically.
- **FR-002**: For each discovered file, the system MUST compute a stable content hash. "Stable" means the hash MUST be identical across operating systems and machines for byte-identical content. Line-ending or filesystem differences MUST NOT affect the hash.
- **FR-003**: For each discovered file, the system MUST collect the documented metadata fields: local file path (relative to the repo root), the stage name that loads the prompt, the content hash, the template format identifier, the model name used by that stage (when known to the agent), the schema/structured-output version (when known to the agent), and the current git HEAD commit hash (when the working tree is a git repository).
- **FR-004**: When the git working tree contains uncommitted changes at sync time, the system MUST flag the recorded git commit hash with an explicit "dirty" marker so reviewers can tell synced content was not from a clean commit.

#### Sync & versioning

- **FR-005**: The system MUST provide a CLI command (e.g., `jobagent prompts sync`) that uploads every discovered prompt to Langfuse Prompt Management under a deterministic prompt name. The default name is `bewerbungs-agent/<prompt_file_stem>` (e.g., `bewerbungs-agent/planner`).
- **FR-006**: For each prompt, if the latest Langfuse version's content hash already matches the local content hash, the system MUST NOT create a new Langfuse version. This idempotence guarantee is essential — repeated syncs with no local changes must not bloat the registry.
- **FR-007**: For each prompt, if the local content hash differs from the latest Langfuse version's content hash, the system MUST create a new Langfuse version carrying the local content and the full metadata block from FR-003 + FR-004.
- **FR-008**: The sync command MUST accept a `--label` argument with a configurable value (e.g., `staging`, `development`, `production`) and MUST apply that label to the version it produced, moving the label from any older version that previously carried it.
- **FR-009**: When `--label` is not provided, the default applied label MUST be `staging`.
- **FR-010**: The sync command MUST report, for each prompt: the prompt name, whether it was created or unchanged, the new version number when applicable, and the label state. A summary line at the end MUST give totals (e.g., "3 created, 4 unchanged, 0 failed").
- **FR-011**: A network or API failure on any one prompt MUST NOT abort the remaining prompts. The command MUST report failed prompts at the end with the upstream error message and exit with a non-zero status if any failed.

#### Inspection

- **FR-012**: The system MUST provide a CLI command (e.g., `jobagent prompts list`) that prints one row per discovered local prompt showing: local file path, short content hash, matching Langfuse prompt name, latest synced version number, labels on that version, and a status indicator (`up-to-date`, `local differs`, `not synced`, or `local missing` for prompts that exist in Langfuse but not locally).
- **FR-013**: `jobagent prompts list` MUST work locally-only when Langfuse credentials are missing — local file paths and hashes are shown, the remote columns show a clear "(no langfuse)" placeholder, and the command exits 0.
- **FR-014**: `jobagent prompts list` MUST support a machine-readable output format (e.g., `--json`) so CI and scripts can consume the registry state without parsing tabular text.

#### Optional / degraded mode

- **FR-015**: The entire prompts subcommand group MUST degrade safely when Langfuse credentials (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are missing: `prompts list` runs locally; `prompts sync` prints a clear "Langfuse disabled (credentials missing); nothing uploaded" message and exits non-zero (so CI catches an unintentionally missing credential) without attempting any network call.
- **FR-016**: When Langfuse credentials are missing, the runtime pipeline MUST continue to load prompts from local files and run normally — this feature MUST NOT add a runtime dependency on Langfuse being reachable.

#### Runtime referencing

- **FR-017**: When an LLM-using pipeline stage runs and observability is enabled (feature 006), the stage's trace span MUST carry the `prompt_name` and `prompt_version` for the prompt it used. `prompt_version` MUST be the Langfuse version whose content hash matches the local file currently in use. When no Langfuse version matches the local content, the span MUST carry `prompt_version=unsynced` (or an equivalent explicit marker) so the gap is visible in the trace.
- **FR-018**: The runtime resolution of `prompt_version` MUST NOT require a Langfuse network call per stage. The mapping between local content hash and Langfuse version MUST be cached after the first sync (or first runtime resolution) so subsequent stage spans incur no per-call latency overhead.
- **FR-019**: The runtime span MUST NOT log the rendered prompt text, the agent's CV, profile, job description, cover letter draft, or raw prompt-filled inputs. The new `prompt_name`/`prompt_version` fields ride alongside the existing summary-mode payload from feature 006; they MUST NOT cause raw prose to be sent. The privacy defaults from feature 006 remain in force.

#### Source-of-truth invariant

- **FR-020**: Local prompt files MUST remain the source of truth for runtime behaviour. The runtime MUST NOT silently substitute a Langfuse-fetched prompt for a local file. Langfuse acts only as a version-tracking registry; behaviour is determined by the local files on disk.

#### Tests

- **FR-021**: The system MUST provide an automated test that discovers all current prompt files and asserts the discovered set matches the agent's actual stage-to-prompt mapping (no missing, no extra).
- **FR-022**: The system MUST provide an automated test that calls the hash function twice on the same byte content and asserts the hashes are equal; another that asserts byte-different content produces different hashes.
- **FR-023**: The system MUST provide an automated test that mocks the Langfuse client, runs sync twice with no content changes, and asserts that the second sync creates zero new versions.
- **FR-024**: The system MUST provide an automated test that mocks the Langfuse client, runs sync, modifies one prompt's content, runs sync again, and asserts that exactly one new version is created on exactly that prompt and the configured label is moved to the new version.
- **FR-025**: The system MUST provide an automated test that runs the sync and list commands with no Langfuse credentials in the environment and asserts the documented no-op / local-only behaviour (correct exit codes and human-readable messages).
- **FR-026**: The system MUST provide an automated test that runs a single LLM stage with observability enabled and a synced prompt, and asserts the resulting span carries the correct `prompt_name` and `prompt_version` values; another that runs the same stage with a locally-edited unsynced prompt and asserts the `prompt_version=unsynced` marker is present.

### Key Entities

- **Local Prompt File**: a Markdown (or other text) template on disk used by exactly one pipeline stage. Identified by its file path; carries a content hash derived from its bytes.
- **Stage-to-Prompt Mapping**: the agent's existing wiring (established in feature 006 graph wrapping) that names which prompt file each pipeline stage loads. The discovery mechanism reads this mapping; it is not maintained separately.
- **Langfuse Prompt**: a named, versioned text/chat template stored remotely. One Langfuse Prompt per local file. Each version carries content, a metadata block (the FR-003/FR-004 fields), and zero or more labels.
- **Label**: a movable pointer to one version of one Langfuse Prompt (e.g., `staging`, `production`). At most one version per prompt holds a given label at any time; applying a label moves it.
- **Sync Result**: per-prompt outcome of one `prompts sync` invocation, recording prompt name, action taken (`created`, `unchanged`, `failed`), resulting version number, and any upstream error message.
- **Local-Hash-to-Version Cache**: a process-local lookup that maps `(prompt_name, local_content_hash) → langfuse_version_number` so runtime stage spans can resolve the version without a per-call network round-trip.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An engineer can sync every prompt the agent uses to Langfuse with a single command in under 10 seconds for a project with up to 20 prompts.
- **SC-002**: For 100% of `prompts sync` invocations where no local prompt content has changed since the previous sync, zero new Langfuse versions are created.
- **SC-003**: For 100% of `prompts sync` invocations where exactly one local prompt has changed, exactly one new Langfuse version is created on exactly that prompt and the requested label is moved to that new version.
- **SC-004**: For 100% of `jobagent prompts list` invocations, every local prompt file is represented in the output exactly once with a correct sync-status indicator.
- **SC-005**: When Langfuse credentials are absent, both `prompts sync` and `prompts list` exit with documented behaviour in 100% of runs and do not attempt any network call.
- **SC-006**: When observability is enabled and prompts have been synced, an engineer reading a stage span in Langfuse can navigate to the exact registry prompt + version that produced the call in under 5 seconds (one click on the recorded `prompt_name` + `prompt_version`).
- **SC-007**: A stage span using a locally-edited, unsynced prompt is unambiguously flagged with `prompt_version=unsynced` in 100% of such cases.
- **SC-008**: The privacy invariant from feature 006 holds — across a fixture of 50 stage spans recorded with this feature enabled, zero spans contain raw CV, profile, job, or letter prose, regardless of synced/unsynced state.

## Assumptions

- The runtime prompt-loading layer already exists and already records a content hash per stage (established in feature 006); this feature reuses that hashing convention so local and registry hashes are guaranteed comparable.
- Langfuse Prompt Management's REST API supports: creating named prompts, listing versions of a prompt with their content and metadata, and applying labels to a specific version. These are documented Langfuse v2/v4 capabilities; the feature does not require any private API surface.
- Naming convention: each Langfuse prompt is named `bewerbungs-agent/<prompt_file_stem>` by default (e.g., the local file `prompts/planner.md` becomes the Langfuse prompt `bewerbungs-agent/planner`). The namespacing keeps the agent's prompts cleanly separated from any other project's prompts that share a Langfuse instance.
- Default label is `staging`. Operators escalate to `production` explicitly via `--label production` once a sync has been validated. Promotion is destructive in the sense that the label moves; the underlying version is preserved.
- Hash comparison for "no duplicate version" is against the latest version of each prompt only. Reverting a local file to identical content to an older version still produces a new version (carrying the older content). This keeps sync logic simple and chronological.
- Git commit hash is captured via `git rev-parse HEAD`; if the working tree is not a git repository, the commit-hash metadata field is omitted (not synthesised).
- Template format identifier defaults to `markdown`. If a sidecar metadata file (e.g., `<prompt>.meta.json`) is present in a future iteration, it MAY override individual metadata fields; sidecar support is NOT required in v1.
- Model name and schema version are derived from the agent's existing stage-to-LLM-client wiring (model = `claude-sonnet-4-6` for current stages). When a stage does not call an LLM (e.g., the future validator prompt is informational only), the model field is omitted.
- The local-hash-to-version cache is built lazily: on first runtime resolution of a prompt, the agent fetches the matching version once from Langfuse (if observability is enabled and credentials are present) and caches the result for the rest of the process. A subsequent process resolves again. This avoids needing a persistent local cache file in v1.
- `prompts sync` is operator-initiated and runs to completion (no background scheduling). CI integration is out of scope here; teams can wire `prompts sync --label staging` into their existing CI flow if desired.
- This feature does NOT introduce prompt-content editing inside Langfuse, Langfuse-as-prompt-cache for offline runs, A/B testing of prompt versions, or automatic rollback. All of those are downstream consumers of the registry and out of scope.
- This feature does NOT change runtime generation behaviour, evidence retrieval, validation, or any pipeline stage's output content. Outputs (`letter.md`, `artifacts/*.json`) MUST remain byte-identical to runs before this feature on the same inputs (same invariant as feature 006 FR-013).
