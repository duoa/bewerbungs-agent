"""LangGraph workflow: pipeline graph definition and conditional edges.

Stage nodes are registered as no-op stubs at this point.
They are replaced with real implementations as each user story is completed.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from bewerbungs_agent.models.state import WorkflowState
from bewerbungs_agent.utils.observability import _wrap_stage
from bewerbungs_agent.utils.prompt_registry import STAGE_PROMPT_MAP

# ---------------------------------------------------------------------------
# Stage node stubs (replaced per user story)
# ---------------------------------------------------------------------------


def _noop(state: WorkflowState) -> dict[str, Any]:
    """Placeholder node — returns no state updates."""
    return {}


# ---------------------------------------------------------------------------
# Conditional edge: should_rewrite
# ---------------------------------------------------------------------------


def should_rewrite(state: WorkflowState) -> str:
    """Decide whether to re-validate after a rewrite.

    Returns "rewrite" if any validation failed and rewrites remain;
    otherwise "end".
    """
    letter_ok = state.letter_validation.passed if state.letter_validation else True
    cv_ok = state.cv_validation.passed if state.cv_validation else True

    if (not letter_ok or not cv_ok) and state.rewrite_count < state.max_rewrites:
        return "rewrite"
    return "end"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """Assemble and compile the full pipeline graph.

    Stage implementations are imported lazily so that only the stages required
    for the current user stories need to be implemented.
    """
    # Import real stage functions where available; fall back to _noop.
    def _import_stage(module: str, fn: str) -> Any:
        try:
            import importlib
            mod = importlib.import_module(f"bewerbungs_agent.stages.{module}")
            return getattr(mod, fn)
        except (ImportError, AttributeError):
            return _noop

    load_job_fn = _import_stage("load_job", "load_job")
    extract_req_fn = _import_stage("extract_requirements", "extract_requirements")
    load_profile_fn = _import_stage("load_profile", "load_profile")
    select_cv_fn = _import_stage("select_cv_variant", "select_cv_variant")
    build_evidence_fn = _import_stage("build_evidence_map", "build_evidence_map")
    role_position_fn = _import_stage("role_position", "role_position")
    narrative_strategy_fn = _import_stage("narrative_strategy", "narrative_strategy")
    plan_content_fn = _import_stage("plan_content", "plan_content")
    write_letter_fn = _import_stage("write_letter", "write_letter")
    story_polish_fn = _import_stage("story_polish", "story_polish")
    hiring_review_fn = _import_stage("hiring_review", "hiring_review")
    targeted_rewrite_fn = _import_stage("targeted_rewrite", "targeted_rewrite")
    tailor_cv_fn = _import_stage("tailor_cv", "tailor_cv")
    validate_fn = _import_stage("validate", "validate_outputs")
    rewrite_fn = _import_stage("rewrite", "rewrite_if_needed")

    graph: StateGraph[WorkflowState] = StateGraph(WorkflowState)

    # Register all nodes, each wrapped with one observability stage span.
    # prompt_name is passed for LLM stages so the wrapper can record the
    # current prompt-file content hash and the model name.
    # Register every node, each wrapped with one observability stage span.
    # `prompt_name` is sourced from the single STAGE_PROMPT_MAP constant
    # (utils/prompt_registry.py) so the registry and the graph wiring never
    # drift apart.
    stage_fns: dict[str, Any] = {
        "load_job":             load_job_fn,
        "extract_requirements": extract_req_fn,
        "load_profile":         load_profile_fn,
        "select_cv_variant":    select_cv_fn,
        "build_evidence_map":   build_evidence_fn,
        "role_position":        role_position_fn,
        "narrative_strategy":   narrative_strategy_fn,
        "plan_content":         plan_content_fn,
        "write_letter":         write_letter_fn,
        "story_polish":         story_polish_fn,
        "hiring_review":        hiring_review_fn,
        "targeted_rewrite":     targeted_rewrite_fn,
        "tailor_cv":            tailor_cv_fn,
        "validate_outputs":     validate_fn,
        "rewrite_if_needed":    rewrite_fn,
    }
    for stage_name, stage_fn in stage_fns.items():
        graph.add_node(
            stage_name,
            _wrap_stage(stage_fn, stage_name, prompt_name=STAGE_PROMPT_MAP.get(stage_name)),
        )

    # Sequential edges up to plan_content
    graph.set_entry_point("load_job")
    graph.add_edge("load_job", "extract_requirements")
    graph.add_edge("extract_requirements", "load_profile")
    graph.add_edge("load_profile", "select_cv_variant")
    graph.add_edge("select_cv_variant", "build_evidence_map")
    # Feature 013: insert role_position and narrative_strategy between
    # build_evidence_map and plan_content.
    graph.add_edge("build_evidence_map", "role_position")
    graph.add_edge("role_position", "narrative_strategy")
    graph.add_edge("narrative_strategy", "plan_content")

    # Parallel fan-out after plan_content (equal-depth branches required by LangGraph):
    #   branch 1: write_letter → story_polish → hiring_review  (2 hops, feature 013)
    #   branch 2: tailor_cv                  → hiring_review   (1 hop)
    # Fan-in at hiring_review; then sequential: targeted_rewrite → validate_outputs
    graph.add_edge("plan_content", "write_letter")
    graph.add_edge("plan_content", "tailor_cv")

    # Feature 013: insert story_polish between write_letter and hiring_review
    graph.add_edge("write_letter", "story_polish")
    graph.add_edge("story_polish", "hiring_review")
    graph.add_edge("tailor_cv", "hiring_review")

    # Sequential review → rewrite → validate chain
    graph.add_edge("hiring_review", "targeted_rewrite")
    graph.add_edge("targeted_rewrite", "validate_outputs")

    # Conditional rewrite loop
    graph.add_conditional_edges(
        "validate_outputs",
        should_rewrite,
        {"rewrite": "rewrite_if_needed", "end": END},
    )
    graph.add_edge("rewrite_if_needed", "validate_outputs")

    return graph.compile()


# Module-level compiled graph instance (lazy).
_compiled_graph: Any = None


def get_graph() -> Any:
    """Return the compiled graph, building it on first call."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
