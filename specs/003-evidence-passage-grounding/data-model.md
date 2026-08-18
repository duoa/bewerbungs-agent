# Data Model: Evidence Passage Grounding

**Feature**: 003-evidence-passage-grounding  
**Date**: 2026-04-15

This document describes only the model changes introduced by this feature. All unchanged models are omitted.

---

## Changed: EvidenceItem

**File**: `src/bewerbungs_agent/models/state.py`

### Before

```python
class EvidenceItem(BaseModel):
    claim: str
    source_type: str  # "master_profile" | "cv_variant" | "personal_skills" | ...
    source_file: str  # relative path within data/
    passage: str      # verbatim excerpt (was underused — often empty)
```

### After

```python
class EvidenceItem(BaseModel):
    claim: str
    source_type: str          # "master_profile" | "cv_variant" | "personal_skills" | ...
    source_file: str          # relative path within data/
    passage: str              # verbatim excerpt — REQUIRED non-empty after build_evidence_map
    relevance_note: str = ""  # NEW: one-sentence explanation of why this passage supports the claim
```

### Constraints

- `passage` MUST be non-empty after `build_evidence_map` runs. Items with empty passages are dropped and their `claim` is added to `EvidenceMap.known_gaps`.
- `relevance_note` is optional (safe default `""`). The LLM populates it; it is never validated for content.
- All existing fields remain identical; `relevance_note` has a safe default, so no migration is needed.

### Validation rule

In `build_evidence_map.parse_response`:
```
if not item.passage.strip():
    known_gaps.append(item.claim)
    # do not add item to items list
```

---

## Changed: SectionPlan

**File**: `src/bewerbungs_agent/models/state.py`

### Before

```python
class SectionPlan(BaseModel):
    title: str
    key_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)  # claim texts
    soft_skills: list[str] = Field(default_factory=list)
```

### After

```python
class SectionPlan(BaseModel):
    title: str
    key_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)      # claim texts (unchanged)
    anchor_passages: list[str] = Field(default_factory=list)    # NEW: verbatim passages for this section
    soft_skills: list[str] = Field(default_factory=list)
```

### Constraints

- `anchor_passages` is optional (safe default `[]`). It is populated by `plan_content` by copying verbatim passages from the evidence map items referenced in `evidence_refs`.
- The letter writer uses `anchor_passages` as the primary grounding text when generating prose for this section.
- Empty `anchor_passages` is allowed (section may have no evidence, e.g., opening/closing boilerplate).

---

## Unchanged entities (listed for reference)

| Entity | Change |
|--------|--------|
| `EvidenceMap` | No change — `items`, `known_gaps`, `assumptions` fields unchanged |
| `ContentPlan` | No change — embeds `EvidenceMap` (which now has passages) and `sections` (which now have `anchor_passages`) automatically |
| `SoftSkill` | No change — still embeds `EvidenceItem`, which now has `relevance_note` |
| `LetterDraft` | No change |
| `WorkflowState` | No change — `evidence_map` and `content_plan` fields unchanged |

---

## Data flow summary

```
build_evidence_map
  → EvidenceItem {claim, source_type, source_file, passage, relevance_note}
  → EvidenceMap {items: [EvidenceItem...], known_gaps: [...]}
        ↓
plan_content
  → SectionPlan {title, key_claims, evidence_refs, anchor_passages}  ← passages copied here
  → ContentPlan {sections: [...], evidence_map: EvidenceMap, ...}
        ↓
write_letter
  → receives ContentPlan JSON (includes EvidenceMap with passages + SectionPlan.anchor_passages)
  → generates LetterDraft anchored to anchor_passages
  → NO raw InternalKnowledge fields in prompt
```
