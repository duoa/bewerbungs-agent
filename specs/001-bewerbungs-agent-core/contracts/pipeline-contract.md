# Pipeline Stage Contracts: Bewerbungs-Agent

**Branch**: `001-bewerbungs-agent-core` | **Date**: 2026-04-01
**Implementation**: `src/bewerbungs_agent/stages/`

Each stage is a LangGraph node. The node function signature is:

```python
def stage_name(state: WorkflowState) -> dict[str, Any]:
    ...
    return {"field_name": updated_value}
```

The return value is a partial `WorkflowState` update (LangGraph merges it).
Every stage MUST:
- Read only from `state.config` and fields populated by prior stages.
- Return only the fields it is responsible for populating.
- Raise `ValueError` with a descriptive message on any rule violation.
- Never write directly to disk (the `io.writer` module handles persistence).

---

## Stage 1: `load_job`

**Module**: `stages/load_job.py`
**LLM call**: No

```
Input fields used:
  state.config.job_file
  state.config.company_file     (optional)
  state.config.storyboard_file  (optional)

Output fields set:
  state.job_context             → JobContext

Raises:
  FileNotFoundError   if job_file does not exist
  ValueError          if job_file is empty
```

---

## Stage 2: `merge_config`

**Module**: `stages/merge_config.py`
**LLM call**: No

Loaded implicitly at CLI entry before the graph runs. Produces `MergedConfig`
from `StarterTemplate` + `RunInput.overrides`. Not a LangGraph node — runs
before graph construction so the graph receives a complete `MergedConfig`.

---

## Stage 3: `extract_requirements`

**Module**: `stages/extract_requirements.py`
**LLM call**: Yes (structured output via tool-use)

```
Input fields used:
  state.config          (language, tone_signals hint)
  state.job_context     (raw_job_text, raw_company_text)

Output fields set:
  state.requirements    → RequirementExtraction

Constraint:
  technical_requirements: len ≤ 2
  all_requirements total: len ≤ 6

Raises:
  ValueError   if core_requirement is empty after extraction
```

---

## Stage 4: `load_profile`

**Module**: `stages/load_profile.py`
**LLM call**: No

```
Input fields used:
  state.config.job_file     (profile-dir is resolved from CLI --profile-dir)

Output fields set:
  state.knowledge           → InternalKnowledge

Raises:
  FileNotFoundError   if master_profile.json is missing
  FileNotFoundError   if no CV variant files are found
  FileNotFoundError   if personal_skills.md is missing
```

---

## Stage 5: `select_cv_variant`

**Module**: `stages/select_cv_variant.py`
**LLM call**: Yes (lightweight — selects from list, no prose)

```
Input fields used:
  state.config.cv_variant_override  (if set, skip LLM selection)
  state.requirements
  state.knowledge.cv_variants

Output fields set:
  state.selected_cv   → SelectedCV

Raises:
  ValueError   if no CV variant is available
  ValueError   if override variant_id is not found in knowledge.cv_variants
```

---

## Stage 6: `build_evidence_map`

**Module**: `stages/build_evidence_map.py`
**LLM call**: Yes (structured output — maps claims to source passages)

```
Input fields used:
  state.requirements
  state.knowledge
  state.selected_cv
  state.config.prioritized_projects
  state.config.must_not_mention

Output fields set:
  state.evidence_map    → EvidenceMap

Constraint:
  Every EvidenceItem.source_file MUST resolve within the approved source
  directories (master_profile, cv_variants, personal_skills, projects, letters).

Raises:
  ValueError   if any EvidenceItem.source_file is outside approved directories
```

---

## Stage 7: `plan_content`

**Module**: `stages/plan_content.py`
**LLM call**: Yes (structured output — produces ContentPlan, no prose)

```
Input fields used:
  state.config          (mode, soft_skill_max, language, tone)
  state.requirements
  state.evidence_map
  state.knowledge.personal_skills
  state.config.why_company

Output fields set:
  state.content_plan    → ContentPlan

Constraint:
  len(content_plan.selected_soft_skills) ≤ config.soft_skill_max
  All claim texts in ContentPlan MUST exist in evidence_map.items[].claim
  No prose — key_claims are bullet-point style, not sentences

Raises:
  ValueError   if a claim in content_plan is not found in evidence_map
```

---

## Stage 8: `write_letter`

**Module**: `stages/write_letter.py`
**LLM call**: Yes (generative — prose output)

```
Input fields used:
  state.config          (language, tone, length, mode)
  state.content_plan

Output fields set:
  state.letter_draft    → LetterDraft

Constraint:
  Prose MUST only express facts listed in state.content_plan.
  The model prompt MUST pass only the content_plan (not raw knowledge docs)
  to prevent out-of-plan invention.

Raises:
  ValueError   if letter_draft.char_count == 0
```

---

## Stage 9: `tailor_cv`

**Module**: `stages/tailor_cv.py`
**LLM call**: Yes (structured plan + generative for tailored text)

```
Input fields used:
  state.config
  state.requirements
  state.selected_cv
  state.evidence_map

Output fields set:
  state.cv_tailoring_plan   → CVTailoringPlan

Constraint:
  CVTailoringChange actions MUST be "emphasise", "reorder", "include", or "exclude".
  No new facts may be introduced; all changes must reference evidence_map items.
```

---

## Stage 10: `validate_outputs`

**Module**: `stages/validate.py`
**LLM call**: Optional (for tone/mode compliance checks; source checks are deterministic)

```
Input fields used:
  state.letter_draft
  state.cv_tailoring_plan
  state.content_plan
  state.evidence_map
  state.config

Output fields set:
  state.letter_validation   → ValidationReport
  state.cv_validation       → ValidationReport

Rules checked (deterministic):
  source_compliance:   all claims in output traceable to evidence_map
  length:              char_count within config.length bounds
  redundancy:          same fact ≤ 1 occurrence; same tech ≤ 2 occurrences
  soft_skill_count:    count ≤ config.soft_skill_max
  must_not_mention:    no item from config.must_not_mention appears in output

Rules checked (LLM-assisted, optional):
  tone:                output matches config.tone description
  mode_rules:          AIDA structure respected if mode == aida
```

---

## Stage 11: `rewrite_if_needed`

**Module**: `stages/rewrite.py`
**LLM call**: Yes (targeted — only failing sections)

```
Input fields used:
  state.letter_validation
  state.cv_validation
  state.letter_draft
  state.cv_tailoring_plan
  state.content_plan
  state.rewrite_count
  state.max_rewrites

Output fields set:
  state.letter_draft         (updated, if letter had violations)
  state.cv_tailoring_plan    (updated, if cv had violations)
  state.rewrite_count        (incremented)

Conditional edge:
  if rewrite_count < max_rewrites AND (letter_validation.passed == False OR
     cv_validation.passed == False):
      → re-run validate_outputs
  else:
      → end (report remaining violations)

Constraint:
  Only failing sections are regenerated. Full-document regeneration is not
  permitted as a validation bypass.
  Rewrite MUST use the same content_plan (no re-planning).

Raises:
  ValueError   if a rewrite introduces a new fact not in content_plan
```

---

## Graph Edge Summary

```
load_job
    → extract_requirements
    → load_profile
    → select_cv_variant
    → build_evidence_map
    → plan_content
    → [write_letter, tailor_cv]   (parallel)
    → validate_outputs
    → rewrite_if_needed           (conditional back-edge to validate_outputs)
    → END
```
