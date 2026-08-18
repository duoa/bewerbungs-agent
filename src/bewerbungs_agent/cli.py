"""Bewerbungs-Agent CLI — Typer application.

Entry point: `jobagent` (configured in pyproject.toml scripts).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

from dotenv import load_dotenv

# Load .env before anything else so ANTHROPIC_API_KEY is available.
load_dotenv()

import typer  # noqa: E402  (must come after load_dotenv)

app = typer.Typer(
    name="jobagent",
    help="CLI job-application agent — evidence-grounded cover letters and CVs.",
    add_completion=False,
)

# ---------------------------------------------------------------------------
# Global options (shared across commands)
# ---------------------------------------------------------------------------

_PROFILE_DIR_OPTION = Annotated[
    Path,
    typer.Option(
        "--profile-dir",
        help="Root directory of user profile data.",
        envvar="BEWERBUNGS_PROFILE_DIR",
    ),
]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    job: Annotated[Path, typer.Option("--job", help="Path to the job description file.")],
    template: Annotated[str, typer.Option("--template", help="Starter template name.")],
    company: Annotated[Optional[Path], typer.Option("--company", help="Company info file.")] = None,
    storyboard: Annotated[Optional[Path], typer.Option("--storyboard", help="Storyboard/AIDA file.")] = None,
    override: Annotated[
        Optional[list[str]],
        typer.Option("--override", help='JSON override string, e.g. \'{"language":"EN"}\'.'),
    ] = None,
    cv_variant: Annotated[Optional[str], typer.Option("--cv-variant", help="Force a specific CV variant ID.")] = None,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", help="Output directory.")] = None,
    profile_dir: _PROFILE_DIR_OPTION = Path("data"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Run structured stages only, skip generation.")] = False,
) -> None:
    """Execute a full application run: cover letter + tailored CV."""
    import json
    import uuid

    from bewerbungs_agent.config.models import RunInput
    from bewerbungs_agent.io.loader import load_starter_template
    from bewerbungs_agent.utils.merge import merge_config

    # Resolve overrides
    merged_overrides: dict[str, Any] = {}
    for ov in override or []:
        merged_overrides.update(json.loads(ov))

    run_id = str(uuid.uuid4())[:8]
    resolved_output = output_dir or Path("outputs") / run_id

    run_input = RunInput(
        starter_template_id=template,
        job_file=job,
        company_file=company,
        storyboard_file=storyboard,
        overrides=merged_overrides,
        cv_variant_override=cv_variant,
        output_dir=resolved_output,
    )

    template_path = profile_dir / "templates" / f"{template}.yaml"
    try:
        starter = load_starter_template(template_path)
    except FileNotFoundError:
        typer.echo(f"[error] Template not found: {template_path}", err=True)
        raise typer.Exit(3)
    except ValueError as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(3)

    try:
        config = merge_config(starter, run_input, profile_dir=str(profile_dir))
    except Exception as exc:
        typer.echo(f"[error] Config merge failed: {exc}", err=True)
        raise typer.Exit(3)

    if dry_run:
        typer.echo(f"[dry-run] Config loaded for template '{template}'. No LLM calls made.")
        typer.echo(f"[dry-run] Mode: {config.mode.value}, Language: {config.language}")
        return

    # Full pipeline execution
    from bewerbungs_agent.graph.workflow import get_graph
    from bewerbungs_agent.io.writer import write_artifacts, write_final_outputs
    from bewerbungs_agent.models.state import WorkflowState

    typer.echo(f"[run] Starting run {run_id} with template '{template}'...")

    initial_state = WorkflowState(config=config, run_id=run_id)

    # Initialise tracker when tracking is enabled (non-blocking)
    tracker = None
    if config.tracking.enabled:
        from bewerbungs_agent.utils.tracker import PipelineTracker

        tracker = PipelineTracker(config.tracking, run_id=run_id)
        tracker.start_run()
        initial_state = initial_state.model_copy(update={"tracker": tracker})

    # Initialise Langfuse observability (NoOp when disabled or creds missing)
    from bewerbungs_agent.utils.observability import build_observability

    observability = build_observability(config.observability)
    observability.start_trace(
        run_id=run_id,
        tags={
            "template_id": config.template_id,
            "language": config.language,
            "mode": config.mode.value,
        },
    )

    # Cross-link Langfuse trace into the MLflow run (one-way; FR-021)
    if tracker is not None:
        try:
            tracker.log_langfuse_link(observability.trace_id(), observability.trace_url())
        except Exception:  # noqa: BLE001
            pass

    initial_state = initial_state.model_copy(update={"observability": observability})

    graph = get_graph()

    # Stream gives per-node progress; accumulate into final_state
    final_state: WorkflowState | None = None
    _run_succeeded = False
    try:
        for event in graph.stream(initial_state, stream_mode="updates"):
            for node_name, updates in event.items():
                typer.echo(f"  [{node_name}] done")
                if final_state is None:
                    final_state = initial_state.model_copy(update=updates)
                else:
                    final_state = final_state.model_copy(update=updates)
        _run_succeeded = True
    finally:
        # Always end the MLflow run — catches Ctrl+C (KeyboardInterrupt) and
        # any other BaseException so runs never get stuck in RUNNING state.
        if tracker and not _run_succeeded:
            tracker.end_run(status="FAILED")
        # Bounded flush to Langfuse (FR-020: 3 s hard limit) + close.
        try:
            observability.flush(timeout_seconds=3.0)
        finally:
            observability.close()

    if final_state is None:
        typer.echo("[error] Pipeline produced no output.", err=True)
        if tracker:
            tracker.end_run(status="FAILED")
        raise typer.Exit(1)

    if tracker:
        tracker.log_outputs(
            evidence_count=len(final_state.evidence_map.items) if final_state.evidence_map else 0,
            gaps_count=len(final_state.evidence_map.known_gaps) if final_state.evidence_map else 0,
            letter_char_count=final_state.letter_draft.char_count if final_state.letter_draft else 0,
            validation_passes=1 if (final_state.letter_validation and final_state.letter_validation.passed) else 0,
            rewrite_count=final_state.rewrite_count,
        )
        tracker.end_run()

    resolved_output.mkdir(parents=True, exist_ok=True)
    write_artifacts(final_state, resolved_output)
    write_final_outputs(final_state, resolved_output)

    typer.echo(f"[run] Done. Outputs written to: {resolved_output}")
    trace_url = observability.trace_url()
    if trace_url:
        typer.echo(f"  langfuse trace: {trace_url}")
    if final_state.letter_draft:
        typer.echo(f"  letter.md  ({final_state.letter_draft.char_count} chars)")
    if final_state.letter_review:
        n_sections = len(final_state.letter_review.sections)
        n_rewritten = len(final_state.letter_review.sections_to_rewrite)
        typer.echo(f"  letter_review  ({n_sections} sections reviewed, {n_rewritten} rewritten)")
    if final_state.cv_tailoring_plan and final_state.cv_tailoring_plan.tailored_text:
        typer.echo("  cv_tailored.md")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    draft: Annotated[Path, typer.Option("--draft", help="Path to draft cover letter.")],
    job: Annotated[Path, typer.Option("--job", help="Path to job description file.")],
    template: Annotated[str, typer.Option("--template", help="Starter template name.")] = "default_de_neutral",
    profile_dir: _PROFILE_DIR_OPTION = Path("data"),
) -> None:
    """Validate an existing draft cover letter against its source job description."""
    from bewerbungs_agent.config.models import RunInput
    from bewerbungs_agent.io.loader import load_markdown, load_starter_template
    from bewerbungs_agent.models.state import LetterDraft, WorkflowState
    from bewerbungs_agent.stages.validate import validate_outputs
    from bewerbungs_agent.utils.merge import merge_config

    if not draft.exists():
        typer.echo(f"[error] Draft file not found: {draft}", err=True)
        raise typer.Exit(2)
    if not job.exists():
        typer.echo(f"[error] Job file not found: {job}", err=True)
        raise typer.Exit(2)

    template_path = profile_dir / "templates" / f"{template}.yaml"
    try:
        starter = load_starter_template(template_path)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(3)

    run_input = RunInput(starter_template_id=template, job_file=job)
    config = merge_config(starter, run_input, profile_dir=str(profile_dir))

    letter_text = load_markdown(draft)
    letter_draft = LetterDraft(
        text=letter_text,
        char_count=len(letter_text),
        mode=config.mode,
        content_plan_hash="",  # no hash available for standalone validate
    )

    state = WorkflowState(config=config, letter_draft=letter_draft)
    result = validate_outputs(state)
    report = result.get("letter_validation")

    if not report:
        typer.echo("[validate] No validation report produced.", err=True)
        raise typer.Exit(1)

    # Print per-rule results
    typer.echo(f"\n[validate] Results for: {draft.name}")
    for vr in report.results:
        icon = "✓" if vr.status.value == "pass" else ("⚠" if vr.status.value == "warning" else "✗")
        line = f"  {icon} {vr.rule}"
        if vr.detail:
            line += f": {vr.detail}"
        typer.echo(line)

    typer.echo("")
    if report.passed:
        typer.echo("[validate] All rules passed.")
        raise typer.Exit(0)
    else:
        typer.echo(f"[validate] {len(report.violations)} rule(s) failed: {report.violations}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# list-templates
# ---------------------------------------------------------------------------


@app.command(name="list-templates")
def list_templates(
    profile_dir: _PROFILE_DIR_OPTION = Path("data"),
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """List all available starter templates in the profile directory."""
    import json as json_mod

    from bewerbungs_agent.io.loader import load_starter_template

    templates_dir = profile_dir / "templates"
    if not templates_dir.exists():
        typer.echo(f"[error] Templates directory not found: {templates_dir}", err=True)
        raise typer.Exit(2)

    yaml_files = sorted(templates_dir.glob("*.yaml"))
    if not yaml_files:
        typer.echo("No templates found.")
        return

    loaded = []
    for path in yaml_files:
        try:
            loaded.append(load_starter_template(path))
        except Exception as exc:
            typer.echo(f"[warn] Could not load {path.name}: {exc}", err=True)

    if as_json:
        typer.echo(json_mod.dumps([t.model_dump() for t in loaded], indent=2))
        return

    # Human-readable table
    header = f"{'ID':<30} {'Language':<10} {'Mode':<10} {'Length':<8} {'Tone'}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for t in loaded:
        typer.echo(
            f"{t.template_id:<30} {t.language:<10} {t.mode.value:<10} "
            f"{t.length.value:<8} {t.tone}"
        )


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


@app.command()
def eval(
    dataset: Annotated[Path, typer.Option("--dataset", help="Path to eval dataset YAML.")],
    output: Annotated[Optional[Path], typer.Option("--output", help="Eval results directory.")] = None,
) -> None:
    """Run the evaluation suite against a fixture dataset."""
    typer.echo("[eval] Eval stage not yet implemented.")
    raise typer.Exit(0)


# ---------------------------------------------------------------------------
# prompts sub-app: sync + list (feature 007 — Langfuse Prompt Registry)
# ---------------------------------------------------------------------------

prompts_app = typer.Typer(
    name="prompts",
    help="Manage Langfuse prompt registry (sync + list).",
    no_args_is_help=True,
)
app.add_typer(prompts_app, name="prompts")


def _prompts_dir_from_env() -> Path | None:
    """Honour the BEWERBUNGS_PROMPTS_DIR env var; else fall back to registry default."""
    import os
    override = os.environ.get("BEWERBUNGS_PROMPTS_DIR")
    return Path(override) if override else None


def _build_langfuse_client_or_none() -> Any | None:
    """Build a Langfuse SDK client when credentials are present; else None."""
    from bewerbungs_agent.config.models import LangfuseConfig, ObservabilityConfig
    from bewerbungs_agent.utils.observability import build_observability

    obs = build_observability(
        ObservabilityConfig(langfuse=LangfuseConfig(enabled=True))
    )
    return obs.underlying_client()


@prompts_app.command("sync")
def prompts_sync(
    label: Annotated[str, typer.Option("--label", help="Label to apply (default: staging).")] = "staging",
) -> None:
    """Sync every local prompt file to Langfuse Prompt Management.

    Exit codes:
      0 — all prompts synced (any mix of created / unchanged / relabeled).
      1 — Langfuse credentials missing in env.
      2 — at least one prompt's sync failed.
      3 — local prompt discovery failed.
    """
    from bewerbungs_agent.utils.prompt_registry import (
        SyncAction,
        discover_prompts,
        sync_prompts,
    )

    try:
        records = discover_prompts(prompts_dir=_prompts_dir_from_env())
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"[prompts] Local discovery failed: {exc}", err=True)
        raise typer.Exit(3)

    if not records:
        typer.echo("[prompts] No prompt files discovered.", err=True)
        raise typer.Exit(3)

    typer.echo(f"[prompts] Discovered {len(records)} local prompt files.")

    client = _build_langfuse_client_or_none()
    if client is None:
        typer.echo(
            "[prompts] Langfuse disabled (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY "
            "credentials missing); nothing uploaded.",
            err=True,
        )
        raise typer.Exit(1)

    results = sync_prompts(records, label=label, client=client)

    counts = {a: 0 for a in SyncAction}
    for r in results:
        counts[r.action] += 1
        if r.action == SyncAction.failed:
            typer.echo(f"[prompts] FAILED   {r.name}: {r.error_message}", err=True)
        else:
            label_part = f"label={r.label_applied}" if r.label_applied else ""
            typer.echo(
                f"[prompts] {r.action.value.upper():9} {r.name:42} "
                f"version {r.version_after_sync}   {label_part}".rstrip()
            )

    typer.echo(
        f"[prompts] Summary: {counts[SyncAction.created]} created, "
        f"{counts[SyncAction.unchanged]} unchanged, "
        f"{counts[SyncAction.relabeled]} relabeled, "
        f"{counts[SyncAction.failed]} failed."
    )

    if counts[SyncAction.failed] > 0:
        raise typer.Exit(2)


@prompts_app.command("list")
def prompts_list(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON instead of table.")] = False,
) -> None:
    """List every local prompt with its sync status against Langfuse.

    Works locally-only when credentials are missing. Exit code 0 in both cases.
    """
    import json as json_mod

    from bewerbungs_agent.utils.prompt_registry import discover_prompts, list_prompts

    try:
        records = discover_prompts(prompts_dir=_prompts_dir_from_env())
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"[prompts] Local discovery failed: {exc}", err=True)
        raise typer.Exit(3)

    client = _build_langfuse_client_or_none()
    entries = list_prompts(records, client=client)

    if as_json:
        typer.echo(json_mod.dumps([e.model_dump(mode="json") for e in entries], indent=2))
        return

    # Aligned table layout
    header = f"{'FILE':30} {'HASH':10} {'LANGFUSE NAME':38} {'VERSION':7} {'LABELS':20} STATUS"
    typer.echo(header)
    typer.echo("-" * len(header))
    for e in entries:
        version_str = str(e.latest_version) if e.latest_version is not None else "—"
        labels_str = ",".join(e.labels) if e.labels else "—"
        local_hash_str = (e.local_hash or "")[:8] or "—"
        typer.echo(
            f"{e.file:30} {local_hash_str:10} {e.langfuse_name:38} "
            f"{version_str:7} {labels_str:20} {e.status.value}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
