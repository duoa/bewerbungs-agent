# Quickstart: Evidence Passage Grounding

**Feature**: 003-evidence-passage-grounding  
**Date**: 2026-04-15

This file describes how to verify the feature works end-to-end after implementation.

---

## What changes (user-visible)

After this feature, the `content_plan.json` debug output (if enabled) and the final letter will reflect concrete phrasing drawn from the actual profile documents rather than generic reformulations.

No CLI flags change. No new commands. No configuration changes.

---

## Verifying passage extraction (US1)

Run only the `build_evidence_map` stage via a unit test or integration fixture:

```python
from bewerbungs_agent.stages.build_evidence_map import parse_response

# Simulate LLM response with a populated passage
response = {
    "items": [
        {
            "claim": "Led migration of monolith to microservices",
            "source_type": "cv_variant",
            "source_file": "cvs/cv_software.md",
            "passage": "Led the migration of a 200 KLOC Django monolith to a microservices architecture on Kubernetes, reducing deployment frequency from monthly to daily.",
            "relevance_note": "Directly evidences large-scale backend architecture experience."
        }
    ],
    "known_gaps": [],
    "assumptions": []
}

evidence_map = parse_response(response)
assert evidence_map.items[0].passage != ""
assert "migration" in evidence_map.items[0].passage
```

**Expected**: `evidence_map.items` is non-empty and each item has a non-empty `passage`.

---

## Verifying empty-passage gap handling (FR-006)

```python
response_with_empty_passage = {
    "items": [
        {
            "claim": "Experience with Kubernetes",
            "source_type": "cv_variant",
            "source_file": "cvs/cv_software.md",
            "passage": "",  # LLM found no supporting text
            "relevance_note": ""
        }
    ],
    "known_gaps": [],
    "assumptions": []
}

evidence_map = parse_response(response_with_empty_passage)
assert evidence_map.items == []
assert "Experience with Kubernetes" in evidence_map.known_gaps
```

**Expected**: Item is dropped; claim appears in `known_gaps`.

---

## Verifying anchor passage propagation (US2)

```python
from bewerbungs_agent.stages.plan_content import parse_response as parse_plan

# Simulate planner response with anchor_passages populated
plan_response = {
    "template_id": "default_de_neutral",
    "selected_cv_variant": "cv_software",
    "mode": "standard",
    "sections": [
        {
            "title": "relevant_experience",
            "key_claims": ["Led microservices migration"],
            "evidence_refs": ["Led migration of monolith to microservices"],
            "anchor_passages": [
                "Led the migration of a 200 KLOC Django monolith to a microservices architecture on Kubernetes, reducing deployment frequency from monthly to daily."
            ],
            "soft_skills": []
        }
    ],
    "selected_soft_skills": [],
    "evidence_map": {"items": [], "known_gaps": [], "assumptions": []},
    "open_questions": [],
    "assumptions": []
}

plan = parse_plan(plan_response, soft_skill_max=3)
assert plan.sections[0].anchor_passages != []
assert "Kubernetes" in plan.sections[0].anchor_passages[0]
```

---

## Verifying writer isolation (US3)

Inspect the prompt built by `write_letter.build_prompt` — assert it contains no raw CV or skills text beyond what appears in the ContentPlan JSON:

```python
from bewerbungs_agent.stages.write_letter import build_prompt

messages = build_prompt(state_with_plan)
prompt_text = messages[0]["content"]

# The raw CV text should not appear directly — only via the plan JSON
assert "raw_cv_full_text_sentinel" not in prompt_text
assert "anchor_passages" in prompt_text  # plan JSON includes the field
```

---

## Full pipeline smoke test

```bash
uv run python -m bewerbungs_agent.cli run \
  --profile-dir data/examples \
  --job-file data/examples/jobs/sample_job.md \
  --output-dir /tmp/test_output
```

**Expected**:
- No `FileNotFoundError` or `ValidationError`
- `letter_draft.txt` generated in `/tmp/test_output/`
- Each `EvidenceItem` in the pipeline log has a non-empty `passage`
- The letter does not contain phrases like "extensive experience in" without a concrete backing claim
