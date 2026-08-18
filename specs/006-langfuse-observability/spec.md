# Feature Specification: Langfuse Observability for the Application Pipeline

**Feature Branch**: `006-langfuse-observability`
**Created**: 2026-05-13
**Status**: Draft
## Clarifications

### Session 2026-05-13

- Q: In raw-payload mode (`langfuse.log_full_payloads: true`), should PII beyond env-var-style secrets also be redacted? → A: Yes — additionally redact email addresses, phone numbers, IBAN/account numbers, and postal-address patterns before transmission.
- Q: What is the maximum time the CLI may wait for Langfuse to flush queued spans at process exit before exiting anyway? → A: 3 seconds hard limit (loses traces under true backend outage; CLI never hangs more than a beat).
- Q: How should the parallel branches (`write_letter` and `tailor_cv`) appear in the trace tree? → A: As sibling spans directly under the root trace, with overlapping wall-clock start/end timestamps conveying the fan-out; no synthetic parent span.
- Q: How should MLflow and Langfuse be cross-linked? → A: One-way only — when both backends are active, write `langfuse_trace_id` and `langfuse_trace_url` as MLflow tags; do not write anything from MLflow into Langfuse.

**Input**: User description: "Add Langfuse observability to the existing job application agent. The feature must trace one complete CLI application run as one Langfuse trace and create nested observations/spans for each pipeline stage, including requirement extraction, evidence mapping, content planning, letter writing, hiring review, targeted rewrite if used, and validation. Each stage span should record the stage name, prompt file name, prompt hash or version if available, model name if available, input summary, output summary, latency, status, errors, token usage if available, and artifact paths where available. The feature must not change generation behavior, prompt content, final letter content, retrieval behavior, or MLflow logging. Langfuse must be optional and disabled automatically when credentials are missing or when configuration disables it. The implementation must protect secrets and personal data. It must never log API keys, environment variables, or raw secrets. Full raw profile/CV/job logging should be controlled by configuration, with safe summaries as the default. Add tests proving that the app works without Langfuse credentials, that spans are created when Langfuse is enabled, that errors are captured, and that no generation output changes when observability is enabled."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — One CLI Run, One Traceable Story (Priority: P1) 🎯 MVP

An operator runs a job application end-to-end from the command line. When Langfuse credentials are configured, every stage that runs during that single command invocation appears in Langfuse as a nested span tree under one parent trace, identified by the same run ID that already names the output directory. When credentials are missing or observability is disabled in configuration, the run completes normally without any error, warning noise, or change in output — the operator sees no difference besides the absence of tracing.

**Why this priority**: This is the foundational capability. Without a single coherent trace per run, none of the per-stage metadata or debugging value is reachable. The "safe-when-disabled" half of this story is non-negotiable: a developer or contributor without Langfuse access must still be able to run the agent.

**Independent Test**: With Langfuse credentials set, run `jobagent run` against a fixture job and profile; query Langfuse for the trace named after the run ID and confirm at least one nested span per stage exists. Separately, unset the credentials and run again; confirm exit code 0, output artifacts written as normal, no Langfuse network calls attempted, and no errors logged.

**Acceptance Scenarios**:

1. **Given** valid Langfuse credentials are present and tracing is enabled in the template, **When** `jobagent run` completes a full pipeline, **Then** exactly one Langfuse trace exists whose name or identifier matches the run ID, and it contains nested spans for every stage that executed in this run.
2. **Given** no Langfuse credentials are configured in the environment, **When** `jobagent run` is invoked, **Then** the run completes with the same output files, the same exit code, and the same console output it would produce in a build without the Langfuse integration, with no warning about missing credentials beyond an optional single-line debug message.
3. **Given** Langfuse is reachable but a transient network error occurs mid-run, **When** the next stage tries to record a span, **Then** the failure is swallowed, a single non-fatal warning is emitted, and the pipeline continues to produce the final letter and CV.
4. **Given** the conditional rewrite loop fires (validation failed once, rewrite re-runs), **When** the trace is inspected, **Then** the rewrite iteration appears as its own span — not as a silent overwrite of the original stage span.

---

### User Story 2 — Rich Stage Metadata for Debugging (Priority: P2)

When the operator inspects a single stage span in Langfuse, they can see at a glance: which stage ran, which prompt file fed the LLM, the prompt's content hash (so they can tell whether prompt edits changed the output), which model handled the call if an LLM was involved, how long the stage took, whether it succeeded or failed, an error message and stack-trace summary when it failed, token usage when the LLM returned it, a compact summary of what went in and what came out, and the relative path of any artifact the stage wrote (e.g., `outputs/<run_id>/artifacts/evidence_map.json`).

**Why this priority**: The trace tree from US1 makes runs discoverable; this story makes individual spans actionable. Without metadata, a span is a name and a duration — useful for performance but not for debugging prompt regressions, model swaps, or quality drops.

**Independent Test**: Mock the Langfuse client and run a single stage (e.g., `plan_content`) end-to-end with the mock injected; assert the recorded span carries every required attribute with non-null values for the fields the stage can produce.

**Acceptance Scenarios**:

1. **Given** an LLM stage (e.g., `plan_content`) executes successfully, **When** its span is inspected, **Then** the span records the stage name, the prompt file name, the prompt content hash, the model name, the input summary, the output summary, the latency in milliseconds, a status of "success," the token usage if the model returned it, and the artifact path if the stage wrote one.
2. **Given** a stage raises an unhandled exception, **When** the span is inspected, **Then** the span status is "error," the exception type and message are recorded, and the surrounding trace is not orphaned (the parent trace is closed cleanly).
3. **Given** a non-LLM stage (e.g., `load_job`, `validate_outputs`) executes, **When** its span is inspected, **Then** model, prompt name, prompt hash, and token usage fields are absent or explicitly null without causing the span to be rejected — the remaining fields (stage name, latency, status, artifact paths) are still present.
4. **Given** prompt content for one stage has changed between two runs, **When** the two corresponding spans are compared, **Then** the prompt hash field differs, making the change visible without inspecting the prompt files.

---

### User Story 3 — Privacy-Safe Defaults, Opt-In Raw Payloads (Priority: P3)

By default, no full profile document, CV text, job description, evidence passage, or generated letter body is sent to Langfuse — only safe summaries (counts, sizes, lengths, top-level field names, hashes) are recorded. The operator can opt in to richer payload logging by setting a configuration flag, but no Langfuse field at any setting may ever contain an API key, environment-variable value, or other credential.

**Why this priority**: The privacy default is what makes Langfuse usable on real job applications without leaking the operator's CV, target employer details, or third-party PII to a hosted SaaS. P3 because the system delivers debugging value (US1+US2) even without raw-payload mode; the configurable escalation is a power-user feature.

**Independent Test**: Run the pipeline with default config and a fixture profile containing distinctive strings (a unique email address, a known project name, a fake API key in an env var); inspect every recorded span payload and assert none of the distinctive strings or the API key value appears anywhere. Then re-run with `langfuse.log_full_payloads: true`; confirm CV text and job text now appear in span inputs but the API key still does not.

**Acceptance Scenarios**:

1. **Given** default Langfuse configuration, **When** any stage records a span, **Then** the span's input and output fields contain no full profile document, CV body, evidence passage text, or generated letter prose — only summary fields (counts, lengths, IDs, hashes, requirement labels).
2. **Given** the operator sets `langfuse.log_full_payloads: true` in the template, **When** stages record spans, **Then** raw inputs and outputs are included, but environment variables and any value of an environment variable whose name ends in `_API_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD` are still redacted.
3. **Given** an exception message contains a credential-looking value, **When** the error is recorded on a span, **Then** the credential is redacted before transmission.
4. **Given** observability is enabled and a full pipeline runs, **When** the operator compares the generated `letter.md` and all `artifacts/*.json` files to a reference run with observability disabled, **Then** every output file is byte-for-byte identical.

---

### Edge Cases

- **Langfuse SDK is not installed**: the run behaves as if credentials were missing — no import error, no crash, just silent fallback.
- **Credentials are present but invalid (auth fails)**: the first span attempt fails; one warning is emitted; subsequent spans are no-ops for the rest of the run.
- **Run is killed mid-pipeline (Ctrl+C)**: the active trace is flushed and closed so it does not linger as a half-open trace in Langfuse; partial spans are acceptable.
- **A stage retries internally (e.g., transient LLM error)**: each attempt produces its own observable record so retries are not invisible.
- **MLflow tracking is also enabled**: both observability backends record the same run independently; neither system is affected by the other being on or off.
- **Run produces zero LLM calls (everything is a no-op because of an early config error)**: the trace still appears in Langfuse, contains the early-failure span, and carries a clear "error" status at the trace level.
- **An artifact file referenced in a span cannot be written (permission error)**: the span still records what it intended to write; the absence of the file is reflected in the status.
- **Concurrent runs share a tracking experiment**: each run gets a distinct trace; spans from one run never appear nested under another.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST emit exactly one Langfuse trace per complete CLI invocation of `jobagent run`, identified by the same run ID used for the output directory.
- **FR-002**: The system MUST emit one nested observation (span) per pipeline stage that executes during the run, covering at minimum: requirement extraction, evidence mapping, content planning, letter writing, hiring review, targeted rewrite (when active), validation, and the post-validation rewrite loop (when active).
- **FR-003**: Each stage span MUST record the stage name as a structured field, not only as the span name.
- **FR-004**: Each stage span MUST record the prompt file name and the prompt content hash whenever the stage loads a prompt file.
- **FR-005**: Each stage span MUST record the model name whenever the stage invokes an LLM.
- **FR-006**: Each stage span MUST record token usage (input tokens, output tokens, total tokens) whenever the underlying LLM call returns them.
- **FR-007**: Each stage span MUST record stage start time, end time, and duration; duration MUST be measured around the stage's work, not around span creation.
- **FR-008**: Each stage span MUST record a terminal status of either "success" or "error"; "error" spans MUST carry the exception type, the exception message, and a truncated stack trace.
- **FR-009**: Each stage span MUST record a summary of the stage's input and a summary of the stage's output; summary content is governed by FR-018.
- **FR-010**: Each stage span MUST record the relative path of any artifact file the stage writes, when the stage writes one.
- **FR-011**: The system MUST disable Langfuse export automatically when Langfuse credentials are not available in the environment, with no exception raised and no error logged beyond an optional single debug-level message.
- **FR-012**: The system MUST disable Langfuse export when configuration explicitly sets the Langfuse-enabled flag to false, even if credentials are present.
- **FR-013**: The system MUST NOT change generation behavior, prompt content, prompt loading order, final letter content, the evidence retrieval pipeline, or any artifact file content when observability is enabled vs. disabled — outputs MUST be byte-identical across the two modes for the same inputs and the same model seed/temperature.
- **FR-014**: The system MUST NOT alter, replace, or disable the existing MLflow tracking integration; both observability systems run side by side without interference.
- **FR-015**: A failure inside the Langfuse client (network error, auth failure, malformed payload, transient timeout) MUST NOT abort the pipeline run or change its exit code; a non-fatal warning is acceptable, an exception is not.
- **FR-016**: Conditional and looping stages (e.g., a second pass of rewrite after a failed validation) MUST appear as distinct spans, not as silent overwrites of an earlier span.
- **FR-016a**: Parallel pipeline branches (`write_letter` and `tailor_cv`) MUST appear as sibling spans directly under the root trace. The system MUST NOT insert a synthetic "parallel branches" parent span; wall-clock start/end timestamps on the sibling spans MUST be the sole signal of fan-out overlap.
- **FR-017**: The system MUST NEVER record API keys, environment variables, contents of environment variables whose names end in `_API_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD`, or other recognisable credential strings in any Langfuse field, regardless of payload-logging mode.
- **FR-018**: The system MUST default to "summary mode" for all input and output payloads on spans — sending only counts, sizes, lengths, identifiers, hashes, requirement labels, and other non-revealing metadata. Raw profile documents, CV text, job text, evidence passages, content plans, and generated letter prose MUST NOT be sent in this default mode.
- **FR-019**: The system MUST expose a single configuration flag (e.g., `langfuse.log_full_payloads`) that, when set to true, switches input and output payloads to include raw content. Credential redaction (FR-017) MUST still apply in this mode.
- **FR-019a**: In raw-payload mode, the system MUST additionally redact common personally-identifying patterns before transmission: email addresses, phone numbers (international and national formats), IBAN/bank-account numbers, and postal-address blocks. Redaction MUST apply to all span input, output, error, and metadata fields, regardless of which stage produced them.
- **FR-020**: The system MUST flush and close the parent trace on normal termination, on uncaught exception, and on keyboard interrupt, so that no trace remains in an open state after the CLI process exits. The flush MUST be bounded to 3 seconds wall-clock; if Langfuse has not acknowledged the queued events within that window, the CLI MUST exit anyway, accepting trace loss as the failure mode (consistent with FR-015 non-fatal posture).
- **FR-021**: When MLflow tracking is also active for the run, the system MUST record the Langfuse trace ID and trace URL as MLflow tags (`langfuse_trace_id`, `langfuse_trace_url`) so an operator viewing the MLflow run can pivot to the Langfuse trace. The link is one-way only — the system MUST NOT write any MLflow identifier back onto the Langfuse trace, to keep the two backends fully independent (FR-014). Failure to set the MLflow tag (e.g., MLflow run already closed) MUST be swallowed and MUST NOT abort the pipeline.
- **FR-022**: The system MUST provide an automated test that runs the full pipeline with no Langfuse credentials configured and asserts the run succeeds without raising or logging an error.
- **FR-023**: The system MUST provide an automated test that runs the full pipeline with a mocked or in-memory Langfuse client and asserts that one trace and the expected nested spans are recorded.
- **FR-024**: The system MUST provide an automated test that injects a deliberate exception in one stage and asserts the corresponding span is recorded with status "error" and that the exception is captured.
- **FR-025**: The system MUST provide an automated test that runs the full pipeline twice with identical inputs — once with Langfuse disabled, once enabled — and asserts the output `letter.md` and every `artifacts/*.json` file are byte-identical between the two runs.

### Key Entities

- **Trace**: a single CLI invocation's observability container. One per `jobagent run`. Carries the run ID, overall status, total duration, and trace-level tags such as template ID and selected CV variant.
- **Stage Span**: one nested observation under a Trace, corresponding to one execution of one pipeline stage. Carries stage name, prompt metadata, model metadata, input/output summary or payload, latency, status, error info, token usage, and artifact path references.
- **Payload Summary**: a structured non-revealing description of a stage's input or output, derived from the typed Pydantic state. Examples: requirement count, evidence item count, character count of letter draft, hash of content plan, list of artifact paths. Used by default; replaced by raw payloads only when `langfuse.log_full_payloads` is true.
- **Credential Redactor**: the safety filter that removes API keys, environment-variable values, and other recognisable secrets from any string before it leaves the process for Langfuse, regardless of which payload mode is active. In raw-payload mode it additionally strips common PII patterns (email addresses, phone numbers, IBAN/account numbers, postal-address blocks).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With Langfuse enabled, an operator can locate the trace for any past `jobagent run` in under 30 seconds using only the run ID.
- **SC-002**: For 100% of pipeline runs with observability enabled, every stage that executed during the run is represented by at least one span in the resulting trace.
- **SC-003**: For 100% of pipeline runs with Langfuse credentials missing, the run exits with the same exit code and produces the same output files it would in a build without the Langfuse feature.
- **SC-004**: Generated `letter.md` and every `artifacts/*.json` file are byte-identical between a Langfuse-enabled run and a Langfuse-disabled run on the same inputs in 100% of test executions.
- **SC-005**: Zero spans across a corpus of 50 test runs contain any API key, environment-variable value, or other recognisable credential string in any field.
- **SC-005a**: With raw-payload mode enabled, zero spans across the same 50-run corpus contain a recognisable email address, phone number, IBAN, or postal-address block from the operator profile in any field.
- **SC-006**: In default payload mode, zero spans across the same 50-run corpus contain full profile documents, full CV text, full job description text, full evidence passages, or full letter prose.
- **SC-007**: A simulated Langfuse network failure during any single stage causes zero pipeline aborts across 20 fault-injection test runs.
- **SC-008**: A simulated stage exception is captured on its span as status "error" with type and message present in 100% of fault-injection runs.

## Assumptions

- Langfuse is consumed via its official Python SDK; the SDK and any network access to the configured Langfuse host are operator-provided dependencies, not part of this feature.
- The CLI runs as a single process per invocation; there is no need to coordinate spans across multiple processes for one logical run.
- The existing `WorkflowState`, run ID, prompt-hashing utility, and per-stage prompt-loading convention (established by features 004 and 005) are reused as the source of truth for span metadata; no parallel metadata system is introduced.
- "Prompt version" is satisfied by the existing content-hash convention (16-character SHA-256 prefix already used for MLflow tags); no separate version registry is required.
- "Input summary" and "output summary" for LLM stages are derived from the typed Pydantic state objects (counts, lengths, IDs) and do not require parsing the underlying Markdown or JSON.
- The Langfuse trace identifier and the local run ID are linked one-to-one; the run ID is used as the trace name or external ID so the trace is discoverable from local artifacts and vice versa.
- Configuration follows the same pattern as the existing MLflow integration — a `langfuse` block in the starter template YAML with sub-fields for enabling and for full-payload mode — so operators learn one configuration shape, not two.
- Default payload mode is "summary"; the operator explicitly opts in to raw payloads. This default is conservative because real applications include real PII (operator's CV, target employer, third-party names).
- "Credential redaction" covers values of environment variables whose names match common secret suffixes (`_API_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`); novel custom secret naming conventions are out of scope.
- The post-validation rewrite loop (`rewrite_if_needed`) is considered a "stage" for the purposes of this feature and produces one span per iteration; the iteration count is recorded on each span.
- This feature does NOT introduce LLM-assisted log analysis, alerting, dashboards, or cost reporting; those are downstream consumers of the trace data and out of scope here.
- This feature is observability-only. It does NOT modify prompts, prompt-loading logic, stage prompts, evidence retrieval, validation rules, or any generation behaviour. Any prompt-quality improvement work belongs in a separate feature.
