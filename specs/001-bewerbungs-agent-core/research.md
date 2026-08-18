# Research: Bewerbungs-Agent – CLI Job Application System

**Date**: 2026-04-01
**Branch**: 001-bewerbungs-agent-core

---

## Decision: Orchestration Framework

**Decision**: LangGraph for orchestrating the 12-stage document-generation pipeline.

**Rationale**:
- LangGraph is purpose-built for stateful, multi-step agent pipelines and natively supports typed state objects (via `TypedDict` or Pydantic models) passed between nodes, exactly matching the requirement for typed state between stages.
- Conditional edges are a first-class primitive in LangGraph, making the rewrite loop (e.g., re-entering a drafting node if a validation node rejects output) expressible as a single `add_conditional_edges` call rather than hand-rolled control flow.
- Each node in a LangGraph graph is a plain Python callable, making individual stages fully unit-testable in isolation — the node function can be invoked directly with a crafted state dict without running the entire graph.
- The compiled graph produces a deterministic execution order that can be inspected, serialized, and resumed, which supports auditability and future streaming/async upgrades without redesigning the pipeline.
- LangGraph integrates naturally with the Anthropic SDK and LangChain tooling while imposing no mandatory dependency on either, keeping vendor lock-in low.

**Alternatives Considered**:
- **Bare Python pipeline (function chain)**: Simple to start but requires hand-coding state propagation, retry/rewrite loops, branching logic, and observability hooks from scratch. As the pipeline grows to 12 stages, this becomes difficult to maintain and test holistically.
- **Prefect**: Excellent for data-engineering workflows with rich scheduling and observability, but its task/flow model is oriented around async distributed execution. The overhead of Prefect's deployment model is disproportionate for a CLI tool that runs locally and synchronously; typed inter-stage state is also less ergonomic than LangGraph's graph state.
- **Luigi**: Designed for batch data pipelines with file-based dependencies; its DAG model does not support dynamic conditional edges (the rewrite loop) without significant workarounds, and it has no native LLM integration story.

---

## Decision: LLM Selection and API

**Decision**: Claude claude-sonnet-4-6 via the Anthropic Python SDK (`anthropic` package) for all LLM calls.

**Rationale**:
- `claude-sonnet-4-6` offers the best balance of instruction-following fidelity, long-context handling, and output quality for document-generation tasks at production scale, as validated by Anthropic benchmarks current to the knowledge cutoff.
- The Anthropic SDK's **tool-use** (function-calling) feature provides structured output: stages that must produce typed JSON (e.g., `RequirementExtraction`, `EvidenceMap`) define a tool schema and parse the `tool_use` content block, giving guaranteed schema adherence without post-hoc parsing heuristics.
- For the rewrite loop, the SDK's `messages` API supports multi-turn conversation natively: the orchestrator appends the previous draft plus the validation critique to the message history and re-invokes the model, preserving full context without prompt re-engineering.
- Claude's large context window (200 k tokens for Sonnet) accommodates the full set of input documents (master profile, CV variants, previous letters, job description) in a single context, eliminating chunking complexity.
- Using a single model and SDK across all stages simplifies dependency management, error handling, and rate-limit budgeting.

**Alternatives Considered**:
- **GPT-4o via OpenAI SDK**: Strong structured-output support via JSON mode and function calling, but introduces a second vendor dependency and diverges from the project's stated model requirement. OpenAI's JSON mode still requires prompt engineering to guarantee schema adherence, whereas Anthropic tool-use returns a validated block.
- **Gemini 1.5 Pro via Google SDK**: Competitive context window, but the Python SDK is less mature and the structured-output story (response schema) is newer and less battle-tested for complex nested Pydantic models.
- **Local models (Ollama / llama.cpp)**: Eliminate API costs and latency, but current open models do not match claude-sonnet-4-6 on nuanced instruction-following and factual grounding for long-form document generation; also lack reliable tool-use support for structured outputs.

---

## Decision: CLI Framework

**Decision**: Typer for the CLI layer.

**Rationale**:
- Typer derives command signatures, argument types, and help text directly from Python type annotations, meaning the CLI stays in sync with the underlying typed data model with zero boilerplate — critical for a project that already uses Pydantic typed models throughout.
- Subcommands (`generate`, `validate`, `init`, `profile`, `list-variants`) are modelled as separate Typer apps registered on a root app, giving a clean command hierarchy that is scriptable and composable.
- Typer produces deterministic, non-interactive behaviour by default (no prompts unless explicitly coded), satisfying the scriptability requirement; `--no-color` and machine-readable output flags are straightforward to add.
- Built-in `--help` generation, shell completion scripts, and rich error messages reduce documentation burden.
- Typer is a thin wrapper over Click, so the full Click API is accessible when Typer's abstractions are insufficient, providing an escape hatch without a framework switch.

**Alternatives Considered**:
- **Click**: The underlying library Typer is built on; fully capable, but requires explicit `@click.option` decorators that duplicate type information already captured in Python annotations. The resulting boilerplate is unnecessary given Typer's availability.
- **argparse**: Standard library, zero dependencies, but verbose for nested subcommands and provides no type coercion from annotations. Help formatting is less polished and shell completion requires third-party packages.

---

## Decision: Document Loading Strategy

**Decision**: Use standard Python libraries and lightweight third-party packages matched to each format: `json` for `master_profile.json`, `PyYAML` for YAML starter templates, `python-markdown` (or direct string reading) for Markdown files, and `pypdf` for PDF CV variants.

**Rationale**:
- `json` (stdlib) is the correct and only sane tool for loading `master_profile.json`; no third-party dependency needed.
- `PyYAML` is the de-facto standard for YAML in Python, stable, and already a transitive dependency of many common packages (LangChain, Pydantic settings). It handles the YAML starter template cleanly and returns plain Python dicts ready for Pydantic validation.
- Markdown files (personal_skills.md, previous letters, CV variants) are plain UTF-8 text; they can be loaded with `pathlib.Path.read_text()` and passed as raw strings to the LLM context. Parsing Markdown to AST is unnecessary because the LLM consumes the raw markup.
- `pypdf` (formerly PyPDF2, actively maintained) extracts plain text from PDF CV variants with no system dependencies. For the use case here (extracting text to feed into an LLM prompt) it is sufficient; heavy alternatives like `pdfminer.six` or `camelot` are over-engineered.
- Keeping loaders in a single `loaders.py` module with one function per format makes them independently testable and swappable.

**Alternatives Considered**:
- **`pdfminer.six`**: More accurate PDF text extraction (especially for complex layouts), but slower and heavier. For well-formatted CV PDFs, `pypdf` text extraction quality is adequate, and layout fidelity matters less when the extracted text is used as LLM context rather than rendered output.
- **`docx2txt` / `python-docx`**: Relevant only if Word documents are added as a format later; not needed now.
- **LangChain document loaders**: Provide a unified interface, but introduce a heavyweight dependency for a thin I/O concern. Prefer direct libraries that do not pull in the full LangChain ecosystem for this layer.
- **`mistune` or `markdown-it-py` for Markdown parsing**: Parsing Markdown to HTML or AST is unnecessary since the content is passed as-is to the LLM. Raw string reading is simpler and correct.

---

## Decision: Config Merge Strategy

**Decision**: Load the YAML starter template into a Pydantic `StarterTemplateConfig` model, load per-run JSON overrides into a `RunOverrides` model, then merge by converting both to dicts and using `{**starter_dict, **override_dict}` (shallow) or a recursive deep-merge for nested keys, finally validating the merged dict into a `MergedConfig` Pydantic model. Precedence rule: `run_overrides` values win over `starter_template` values.

**Rationale**:
- Pydantic models as the target type for both source configs means each input is independently validated before merging, surfacing malformed configs at load time with clear error messages rather than at runtime.
- A simple dict merge (`{**base, **overrides}`) implements the precedence rule (`starter_template < run_overrides`) in one line and is immediately readable; a recursive deep-merge function handles nested sections (e.g., tone settings, section enablement flags) without losing un-overridden keys.
- Validating the merged dict through `MergedConfig` as the final step ensures the composed config satisfies all field constraints and required fields, acting as a contract between the config layer and the pipeline.
- Keeping the merge logic as a pure function (`merge_configs(starter, overrides) -> MergedConfig`) makes it trivially unit-testable: supply two dicts, assert the output model.
- This approach avoids runtime YAML/JSON concatenation or string templating, which is error-prone and hard to type-check.

**Alternatives Considered**:
- **Pydantic `model_copy(update=...)` / `model_validate` with `update`**: Works well for flat models but does not natively deep-merge nested models; requires custom `__init__` or validator logic that obscures the merge semantics.
- **`deepmerge` third-party library**: Provides robust recursive merge strategies, but the dependency is heavy for what amounts to a two-level dict merge. A small custom `deep_merge` utility is preferable.
- **Pydantic Settings (`pydantic-settings`) with multiple sources**: Supports layered settings from env vars, `.env` files, and JSON/YAML sources with built-in precedence. Attractive but ties config loading to environment variables, which conflicts with the CLI-centric run-override pattern where overrides are passed as explicit arguments or JSON files, not env vars.

---

## Decision: Testing Strategy for LLM Stages

**Decision**: Mock the Anthropic API client at the boundary using `unittest.mock.patch` (or `pytest-mock`), combined with pre-recorded response fixtures for representative outputs. Stage logic (prompt construction, output parsing, evidence checking) is tested independently of actual LLM calls.

**Rationale**:
- Mocking the `anthropic.Anthropic` client (or its `messages.create` method) at the point of injection isolates the stage function completely: the test exercises prompt assembly, tool-schema construction, response parsing, and Pydantic model validation without network I/O, making tests fast (milliseconds) and deterministic.
- Pre-recorded response fixtures (JSON files capturing real `Message` objects from the SDK) give realistic payloads for the parser under test; they are committed to the repository and serve as regression anchors if the parsing logic changes.
- Splitting each LLM stage into a pure `build_prompt(state) -> messages_list` function and a pure `parse_response(raw_response) -> StageOutput` function allows those halves to be tested without mocking at all — only the thin `call_llm(messages) -> raw_response` wrapper needs a mock.
- This pattern is consistent with the LangGraph node structure: the node function composes `build_prompt`, `call_llm`, and `parse_response`, so each sub-function is independently unit-testable, and the node itself is integration-testable with the client mocked.
- A `--test-mode` flag that returns a canned fixture response can be added as a secondary mechanism for CLI-level smoke tests, but should not replace proper unit mocks in the test suite.

**Alternatives Considered**:
- **Live API calls in CI**: Accurate but slow, flaky (network/rate limits), costly, and non-deterministic. Unsuitable for a unit-test suite.
- **`pytest-recording` / VCR.py cassette approach**: Records HTTP interactions at the transport layer and replays them. More realistic than hand-crafted fixtures but tightly coupled to exact request shapes; any prompt change invalidates cassettes. The build-prompt/parse-response split is a cleaner seam.
- **Dedicated test-mode flag that bypasses LLM entirely**: Useful for CLI smoke tests but skips all parsing logic, giving false confidence. It complements but does not replace mock-based unit tests.
- **Contract testing against a local stub server**: Robust for SDK-level contract verification but adds significant test infrastructure complexity for a solo/small-team project at this stage.

---

## Decision: Output Artifact Format

**Decision**: Intermediate artifacts (`RequirementExtraction`, `EvidenceMap`, `ContentPlan`, `ValidationReport`) are persisted as **JSON** files. Final output artifacts (cover letter, CV) are persisted as **Markdown** files. Both are written to a timestamped run directory under `output/`.

**Rationale**:
- JSON intermediates are directly deserializable back into Pydantic models, enabling re-entry into the pipeline at any stage (e.g., re-running only the drafting step after editing the `EvidenceMap` by hand) without re-running earlier expensive LLM stages.
- Programmatic consumers (CI checks, downstream scripts, future web UI) can parse JSON intermediates without Markdown parsing; field names are explicit and schema-stable via Pydantic's `model_json_schema()`.
- Markdown for final outputs (cover letter, CV) matches the expected delivery format: Markdown renders cleanly in editors, is diff-friendly in version control, and converts straightforwardly to PDF via Pandoc or similar tools in a later pipeline step.
- Keeping intermediates and finals in the same run directory gives a complete audit trail: every run is self-contained and reproducible from its JSON artifacts.
- `ValidationReport` in JSON allows structured access to individual validation findings (e.g., ungrounded claims flagged by field name) rather than burying them in prose.

**Alternatives Considered**:
- **All artifacts as Markdown**: Human-readable, but programmatic parsing of structured fields (e.g., extracting the list of matched requirements from `RequirementExtraction`) requires fragile Markdown parsing. JSON is strictly superior for machine consumption.
- **All artifacts as JSON including finals**: Cover letters and CVs in JSON (with a `body` string field) add unnecessary indirection when the final consumer (a human or Pandoc) expects plain Markdown. JSON wrapping adds no value for final outputs.
- **SQLite or a database for intermediates**: Provides queryability and transactional writes, but is over-engineered for single-run artifacts in a local CLI tool. File-based JSON is simpler, portable, and inspectable with any text editor.
- **Pickle / binary formats**: Non-human-readable, version-sensitive, and a security risk if artifacts are shared. Rejected entirely.
