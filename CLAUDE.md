# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This repository (`bewerbungs-agent`) is currently empty and being initialized. Update this file as the project takes shape.

## Active Technologies
- Python 3.12+ + LangGraph 0.2+, Pydantic v2, Typer, Anthropic SDK (001-bewerbungs-agent-core)
- Local files only — JSON, YAML, Markdown, PDF; no database (001-bewerbungs-agent-core)
- Python 3.11 + LangGraph 0.2+, Pydantic v2, Typer, Anthropic SDK (001-bewerbungs-agent-core)
- Python 3.11 + LangGraph 0.2+, Pydantic v2, Anthropic SDK (claude-sonnet-4-6 via tool-use) (003-evidence-passage-grounding)
- Python 3.12+ + mlflow ≥ 2.12, anthropic SDK ≥ 0.25, pydantic v2, langgraph 0.2+ (004-mlflow-thinking-observability)
- Local file-based MLflow tracking store (`mlruns/` directory, default) (004-mlflow-thinking-observability)
- Python 3.12+ + anthropic SDK ≥ 0.25, pydantic v2, langgraph 0.2+, mlflow ≥ 2.12 (optional, for tracking) (005-hiring-review-rewrite)
- Local files only (prompts/ directory for new prompt files) (005-hiring-review-rewrite)
- Python 3.11 (matches `pyproject.toml`, mypy strict) + `langfuse>=2.0` (new); existing `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `mlflow>=3.11.1`, `typer>=0.12` (006-langfuse-observability)
- File artifacts under `outputs/<run_id>/` unchanged; Langfuse traces are stored in the operator-provided Langfuse instance (cloud or self-hosted via `LANGFUSE_BASE_URL`). No new local storage. (006-langfuse-observability)
- Python 3.11 (matches `pyproject.toml`, mypy strict) + `langfuse>=2.0` (already in pyproject from feature 006; uses the new prompt-management surface: `create_prompt`, `get_prompt`, `update_prompt`), `pydantic>=2.0`, `typer>=0.12`. No new dependencies required. (007-langfuse-prompt-registry)
- Local prompt files under `prompts/` (existing source of truth); Langfuse Prompt Management for version tracking (operator-provided remote). No new local persistence. (007-langfuse-prompt-registry)
- Python 3.11 (matches `pyproject.toml`, mypy strict) + existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new dependencies. (008-role-positioned-prompting)
- prompt files under `prompts/` (canonical) + local file artefacts. No new persistence. No change to MLflow / Langfuse persistence. (008-role-positioned-prompting)
- existing only — prompt files, file artefacts, MLflow store, Langfuse remote. (009-review-full-job-context)
- Python 3.11 (matches `pyproject.toml`, mypy strict) + existing only — `langgraph>=0.2`, `pydantic>=2.0`, `anthropic>=0.25`, `langfuse>=2.0`, `mlflow>=3.11.1`, `typer>=0.12`. No new runtime dependencies. (013-narrative-strategy-polish)
- Prompt files under `prompts/` (canonical). New file artefacts under `outputs/<run_id>/artifacts/`: `narrative_strategy.json`, `story_polish_output.json`. No new persistence systems. No change to MLflow / Langfuse persistence. (013-narrative-strategy-polish)

## Recent Changes
- 001-bewerbungs-agent-core: Added Python 3.12+ + LangGraph 0.2+, Pydantic v2, Typer, Anthropic SDK
