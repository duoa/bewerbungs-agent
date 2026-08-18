# Quickstart: MLflow Observability and Thinking Config

**Feature**: 004-mlflow-thinking-observability  
**Date**: 2026-04-15

## Scenario 1: Run with MLflow Tracking Enabled (US1)

**Goal**: Verify that a pipeline run produces a retrievable MLflow run record with all required metadata.

**Prerequisites**: `mlflow` installed (`uv add mlflow`), ANTHROPIC_API_KEY set (or use mock).

### Configuration (starter template YAML addition)

```yaml
tracking:
  enabled: true
  tracking_uri: mlruns
  experiment_name: bewerbungs-agent
```

### Verification

After a run:

```bash
# List experiments
mlflow experiments list

# Query runs via Python
python - <<'EOF'
import mlflow
client = mlflow.MlflowClient(tracking_uri="mlruns")
experiment = client.get_experiment_by_name("bewerbungs-agent")
runs = client.search_runs(experiment.experiment_id)
run = runs[0]
print("run_id:", run.info.run_id)
print("params:", run.data.params)
print("metrics:", run.data.metrics)
print("tags:", run.data.tags)
EOF
```

**Expected params include**:
- `run_id` matches the agent run ID
- `model` = "claude-sonnet-4-6"
- `template_id` = "default_de_neutral"
- `thinking_enabled_global` = "False"

**Expected metrics include**:
- `evidence_count` > 0
- `letter_char_count` > 0

**Expected tags include**:
- `stage.extract_requirements.prompt_hash` = 16-char hex string
- `stage.plan_content.thinking_enabled` = "false"

### Open MLflow UI

```bash
mlflow ui --backend-store-uri mlruns
# Open http://localhost:5000
```

---

## Scenario 2: Tracking Disabled — No mlruns Directory Created (US1, FR-005)

**Goal**: Verify that when tracking is not configured, no MLflow code executes and no `mlruns/` directory is created.

**Configuration**: No `tracking` key in the starter template (or `tracking.enabled: false`).

**Verification**:

```bash
# Run the pipeline
uv run bewerbungs-agent run --job data/examples/jobs/sample_software_engineer.md

# Assert: no mlruns directory created
[ -d mlruns ] && echo "FAIL: mlruns exists" || echo "PASS: mlruns not created"
```

---

## Scenario 3: Tracking Failure is Non-Blocking (US1, FR-001, SC-002)

**Goal**: Verify that a permissions error on the tracking store does not abort the pipeline.

**Verification (unit test)**:

```python
from unittest.mock import patch, MagicMock
from bewerbungs_agent.utils.tracker import PipelineTracker
from bewerbungs_agent.config.models import TrackingConfig

config = TrackingConfig(enabled=True)
tracker = PipelineTracker(config, run_id="test-run")

with patch.object(tracker, "_mlflow") as mock_mlflow:
    mock_mlflow.start_run.side_effect = PermissionError("disk full")
    # Must NOT raise:
    tracker.start_run(job_title="Senior Engineer")
# Pipeline continues normally
```

---

## Scenario 4: Per-Stage Thinking Configuration (US2)

**Goal**: Verify that `plan_content` receives thinking enabled and `write_letter` receives thinking disabled when configured.

### Configuration

```yaml
thinking:
  enabled: false      # global default: thinking off
  effort: medium

stage_thinking:
  plan_content:
    enabled: true
    effort: high
```

### Verification (unit test)

```python
from unittest.mock import MagicMock, patch
from bewerbungs_agent.config.models import (
    MergedConfig, ThinkingConfig, ThinkingEffort, LengthMode, WritingMode, CVSelectionMode
)

config = MergedConfig(
    template_id="default_de_neutral",
    language="DE",
    length=LengthMode.normal,
    tone="neutral-professionell",
    mode=WritingMode.standard,
    cv_selection=CVSelectionMode.automatic,
    cv_tailoring=True,
    soft_skill_max=3,
    output_sections=["letter"],
    validation_rules={},
    job_file=Path("data/examples/jobs/sample_software_engineer.md"),
    output_dir=Path("outputs"),
    thinking=ThinkingConfig(enabled=False),
    stage_thinking={
        "plan_content": ThinkingConfig(enabled=True, effort=ThinkingEffort.high)
    },
)

# Simulate stage config lookup:
plan_thinking = config.stage_thinking.get("plan_content", config.thinking)
assert plan_thinking.enabled is True
assert plan_thinking.effort == ThinkingEffort.high

write_thinking = config.stage_thinking.get("write_letter", config.thinking)
assert write_thinking.enabled is False
```

### Verify API call receives thinking params

```python
mock_client = MagicMock()

# In a test that invokes plan_content with the above config:
# Assert: client.call was called with thinking param
call_kwargs = mock_client.call.call_args
assert call_kwargs.kwargs.get("thinking") is not None
thinking_arg = call_kwargs.kwargs["thinking"]
assert thinking_arg.enabled is True
assert thinking_arg.effort == ThinkingEffort.high
```

---

## Scenario 5: Invalid Thinking Effort Fails at Startup (US2, FR-008)

**Goal**: Verify that an invalid effort level raises a descriptive error before any LLM call.

```python
from pydantic import ValidationError
import pytest

with pytest.raises(ValidationError) as exc_info:
    ThinkingConfig(enabled=True, effort="extreme")  # invalid value

assert "effort" in str(exc_info.value)
```

---

## Scenario 6: Backward Compatibility — No Config Changes Required (SC-004)

**Goal**: Existing config files without tracking or thinking settings work unchanged.

```python
# MergedConfig with no thinking/tracking fields — uses defaults
config = MergedConfig(
    template_id="default_de_neutral",
    language="DE",
    length=LengthMode.normal,
    tone="neutral-professionell",
    mode=WritingMode.standard,
    cv_selection=CVSelectionMode.automatic,
    cv_tailoring=True,
    soft_skill_max=3,
    output_sections=["letter"],
    validation_rules={},
    job_file=Path("data/examples/jobs/sample_software_engineer.md"),
    output_dir=Path("outputs"),
    # No tracking= or thinking= or stage_thinking= fields
)

assert config.tracking.enabled is False
assert config.thinking.enabled is False
assert config.stage_thinking == {}
```

The full integration test `test_produces_letter_and_artifacts` covers this scenario end-to-end with no tracking config.
