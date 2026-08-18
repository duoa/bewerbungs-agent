# Feature Specification: MLflow Observability and Thinking Config

**Feature Branch**: `004-mlflow-thinking-observability`  
**Created**: 2026-04-15  
**Status**: Draft  
**Input**: User description: "Add lightweight observability and model-control support to the application agent. The system should integrate MLflow in a minimal, low-friction way to track run metadata, stage names, selected models, prompt identifiers, prompt versions or hashes, and basic outputs for debugging and comparison. In addition, the system should support per-stage thinking configuration for Claude API calls, including the ability to enable or disable thinking and configure effort through explicit parameters. The goal is to improve traceability and experimentation without changing the core writing pipeline or validation architecture."

## Clarifications

### Session 2026-04-15

- Q: What is the MLflow tracking scope for this iteration? → A: Lightweight only — run metadata and stage-level LLM configuration. Explicitly out of scope: full evaluation workflows, dashboards, semantic quality scoring.
- Q: What specific fields must be tracked per run/stage? → A: At minimum: run ID, stage name, model name, thinking enabled (boolean), thinking effort (if present), prompt name, prompt hash or version, and basic token or output metadata when available.
- Q: How is thinking configuration structured? → A: Global on/off default with per-stage override capability. No stage-specific config required to be set; omitting a stage override uses the global default.
- Q: Are any LangGraph structural changes allowed? → A: No. The LangGraph graph topology MUST NOT change. Only configuration passing and metadata logging are added around existing stage invocations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Tracking via MLflow (Priority: P1)

When a user runs the application agent, every pipeline execution is automatically logged to a local MLflow tracking server. The run record captures: run metadata (timestamp, run ID, job title if extracted), stage names executed, the model identifier used at each stage, prompt identifiers and version hashes, key configuration parameters, and basic outputs (evidence map size, letter character count, known gaps count). After the run, the user can open the MLflow UI to inspect, compare, and debug runs.

**Why this priority**: Traceability is the primary stated goal. Without run tracking, there is no baseline to compare against when tuning prompts or models. This story delivers immediate value with no pipeline changes.

**Independent Test**: Can be tested by running the agent against a fixture job and verifying that a new MLflow run record exists in the local tracking store, containing the expected parameters and metrics. No letter generation quality is evaluated.

**Acceptance Scenarios**:

1. **Given** the agent is configured with MLflow tracking enabled, **When** a full pipeline run completes, **Then** a new run record exists in the MLflow tracking store with: run ID matching the agent run ID, all stage names logged as tags, the model identifier used, prompt version hashes, evidence map size, and letter character count.
2. **Given** multiple runs have been executed, **When** the user opens the MLflow UI, **Then** runs are listed chronologically and can be filtered by job title or model identifier.
3. **Given** MLflow tracking is disabled or unavailable, **When** the agent runs, **Then** the pipeline completes normally and produces its outputs — no error is raised due to tracking failure.
4. **Given** a run fails partway through the pipeline, **When** tracking is enabled, **Then** the run is logged as failed in MLflow with the stage name where failure occurred.

---

### User Story 2 - Per-Stage Thinking Configuration (Priority: P2)

When a user configures the agent, they can specify per-stage thinking settings for Claude API calls. Each stage that calls the LLM can be independently configured to enable or disable extended thinking, and to set the thinking effort level. These settings flow from configuration into each LLM call without requiring code changes.

**Why this priority**: Thinking configuration is a model-control improvement that directly affects output quality and cost. It is independent of observability and can be implemented and tested without MLflow.

**Independent Test**: Can be tested by configuring thinking enabled for one stage and disabled for another, then verifying that the LLM client receives the correct parameters for each stage call (via mock inspection).

**Acceptance Scenarios**:

1. **Given** a configuration with thinking enabled for `plan_content` and disabled for `write_letter`, **When** the pipeline runs, **Then** the `plan_content` LLM call includes thinking enabled with the configured effort, and the `write_letter` LLM call does not include thinking parameters.
2. **Given** no per-stage thinking configuration is provided, **When** the pipeline runs, **Then** the default behavior (thinking disabled) is used for all stages — pipeline is backward-compatible.
3. **Given** an invalid thinking effort value is specified, **When** the agent starts, **Then** configuration validation fails with a descriptive error before any LLM call is made.

---

### Edge Cases

- When the tracking store directory is unwritable or the tracking call raises an exception: the exception is caught silently, a warning is emitted to stderr, and the pipeline continues normally.
- When a prompt file changes between runs: the hash is recomputed from the file content at run time — the change is automatically reflected in the new run record.
- When thinking is configured for a stage that does not make LLM calls (e.g., `load_profile`): the config is ignored silently for that stage — no error is raised.
- When thinking effort is omitted from a stage's thinking config while thinking is enabled: a default effort level is used (defined in the global thinking config or a system default).
- When tracking is disabled globally: no tracking code executes, no `mlruns/` directory is created or written, and the pipeline runs identically to the pre-feature baseline.
- When a stage is listed in per-stage thinking overrides but has no global thinking config: the per-stage config takes effect; stages not listed use thinking disabled.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST log each pipeline run to a configurable tracking store (local file-based by default). Logging MUST be non-blocking: tracking failures MUST NOT abort the pipeline or raise errors visible to the user.
- **FR-002**: Each run record MUST include: run ID (matching the agent's run ID), stage name, model name, thinking enabled (boolean), thinking effort (when thinking is enabled), prompt name, prompt version hash (SHA-256 of prompt file content at run time), and basic output metadata (token counts or character counts when available from the API response). Additional run-level metadata (job title if extracted, pipeline mode, language, template ID, total run duration) MUST also be recorded.
- **FR-003**: The system MUST log per-stage metadata as a separate record or tag for each LLM-calling stage in the pipeline. Non-LLM stages are not logged at the stage level.
- **FR-004**: The system MUST log the following output metrics per run: evidence item count, known gaps count, letter character count, number of validation passes, and rewrite count.
- **FR-005**: MLflow tracking MUST be opt-in and configurable via a single flag (e.g., `--track` / `tracking: true` in config). When disabled, no MLflow code is executed.
- **FR-006**: The configuration schema MUST support a global thinking default (enabled: boolean, effort: named level) and a per-stage override map (stage name → thinking enabled: boolean, effort: optional named level). When a stage is absent from the override map, the global default applies. When global thinking config is absent, thinking is disabled for all stages.
- **FR-007**: The LLM client MUST pass the configured thinking parameters to each API call for stages where thinking is enabled. Stages without explicit thinking configuration MUST use the default (thinking disabled).
- **FR-008**: Thinking configuration MUST be validated at startup: invalid effort levels or unsupported combinations MUST raise a descriptive error before any LLM call is made.
- **FR-009**: The system MUST remain backward-compatible: existing configuration files without tracking or thinking settings MUST work without modification.

### Key Entities

- **RunRecord**: A single MLflow experiment run. Attributes: run ID (linked to agent run ID), experiment name (fixed per project), start/end timestamp, status (running/completed/failed), parameters, metrics, and tags.
- **PromptVersionHash**: A SHA-256 hash of a prompt file's content at the time of the run. Used to detect prompt changes across runs without storing prompt text in the tracking store.
- **StageThinkingConfig**: Per-stage configuration for extended thinking. Attributes: stage name, thinking enabled (boolean), effort level (enum or numeric). Default: thinking disabled.
- **TrackingConfig**: Top-level tracking configuration. Attributes: enabled (boolean), tracking URI (default: local `mlruns/` directory), experiment name (default: "bewerbungs-agent").

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After any pipeline run with tracking enabled, a run record is retrievable from the tracking store within 2 seconds of run completion, containing all required parameters and metrics (FR-002, FR-003, FR-004).
- **SC-002**: A tracking failure (e.g., disk full, permissions error) does not prevent the pipeline from completing and producing its letter output — zero pipeline aborts due to tracking errors.
- **SC-003**: When thinking is enabled for a stage, that stage's model invocation includes the configured thinking parameters; when disabled, no thinking parameters are sent — verified by unit tests covering 100% of affected stage calls.
- **SC-004**: All existing pipeline runs (without tracking or thinking configuration) produce identical outputs with zero configuration errors after this feature is added — full backward compatibility.
- **SC-005**: A developer comparing two runs in the tracking UI can identify which prompt version was used at each stage, what model was called, and the key output metrics — without reading source code.

## Assumptions

- MLflow is used in local file-based mode by default (`mlruns/` directory in the working directory). No remote MLflow server setup is required for v1.
- Tracking is completely optional — the pipeline must function identically when tracking is off.
- Per-stage thinking configuration is applied only to stages that make LLM calls; non-LLM stages ignore thinking config silently.
- The thinking effort level uses a named scale (e.g., "low", "medium", "high") mapped to the underlying API parameter, rather than raw API values, to decouple configuration from API specifics.
- Prompt version hashes are computed from the file content at run time; no separate versioning system for prompts is introduced.
- The MLflow experiment name defaults to `"bewerbungs-agent"` and is not configurable per-run (only per installation via config).
- This feature does not introduce a new pipeline stage and does not change the LangGraph graph topology. Tracking calls are instrumentation added around existing stage invocations; thinking config is passed through the existing configuration object.
- Evaluation workflows, dashboards, and semantic quality scoring are explicitly out of scope for this iteration.
- The `tailor_cv` stage is included in tracking scope (it makes LLM calls and its outputs are worth logging).
