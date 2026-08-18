# Data Model: Bewerbungs-Agent – CLI Job Application System

**Branch**: `001-bewerbungs-agent-core` | **Date**: 2026-04-01
**Source**: spec.md §Key Entities + research.md

All models are Pydantic v2. Every pipeline stage accepts one typed model and
returns one typed model. No untyped dicts cross stage boundaries.

---

## Configuration Models (`src/bewerbungs_agent/config/models.py`)

### `StarterTemplate`

Persistent baseline configuration loaded from a YAML file in `data/templates/`.

```python
class LengthMode(str, Enum):
    short  = "short"    # 1200–1800 chars
    normal = "normal"   # 2000–3000 chars
    long   = "long"     # 3200–4000 chars

class WritingMode(str, Enum):
    standard = "standard"
    aida     = "aida"

class CVSelectionMode(str, Enum):
    automatic = "automatic"
    manual    = "manual"

class StarterTemplate(BaseModel):
    template_id:        str
    language:           str                 # "DE" | "EN"
    length:             LengthMode
    tone:               str                 # e.g. "neutral-professionell", "direkt"
    mode:               WritingMode
    cv_selection:       CVSelectionMode
    cv_tailoring:       bool
    soft_skill_max:     int = Field(ge=0, le=5)
    output_sections:    list[str]           # which artifacts to persist
    validation_rules:   dict[str, Any] = {}  # override-able thresholds
```

### `RunInput`

Per-run inputs. Only jobspecific or override values; baseline comes from the
selected starter template.

```python
class RunInput(BaseModel):
    starter_template_id:  str
    job_file:             Path
    company_file:         Path | None = None
    storyboard_file:      Path | None = None
    overrides:            dict[str, Any] = {}
    prioritized_projects: list[str] = []
    must_not_mention:     list[str] = []
    why_company:          list[str] = []
    cv_variant_override:  str | None = None
    output_dir:           Path = Path("outputs")
```

### `MergedConfig`

Resolved configuration after applying `RunInput.overrides` on top of
`StarterTemplate`. All pipeline stages read from this model only.

```python
class MergedConfig(BaseModel):
    template_id:          str
    language:             str
    length:               LengthMode
    tone:                 str
    mode:                 WritingMode
    cv_selection:         CVSelectionMode
    cv_tailoring:         bool
    soft_skill_max:       int
    output_sections:      list[str]
    validation_rules:     dict[str, Any]
    # run-specific
    job_file:             Path
    company_file:         Path | None
    storyboard_file:      Path | None
    prioritized_projects: list[str]
    must_not_mention:     list[str]
    why_company:          list[str]
    cv_variant_override:  str | None
    output_dir:           Path
```

**Merge precedence**: `starter_template` defaults < `run_overrides`.

---

## Pipeline State Models (`src/bewerbungs_agent/models/state.py`)

### `JobContext`

Normalised content of the job description and optional company information.

```python
class JobContext(BaseModel):
    raw_job_text:        str
    job_title:           str | None = None
    company_name:        str | None = None
    raw_company_text:    str | None = None
    raw_storyboard_text: str | None = None
```

### `RequirementExtraction`

Structured output of the `extract_requirements` stage.

```python
class Requirement(BaseModel):
    label:       str    # e.g. "core", "technical", "collaboration", "domain", "optional"
    text:        str
    priority:    int    # 1 = highest

class RequirementExtraction(BaseModel):
    core_requirement:          str
    technical_requirements:    list[str]          # max 2
    collaboration_requirement: str | None = None
    domain_requirement:        str | None = None
    optional_requirement:      str | None = None
    tone_signals:              list[str] = []
    must_include:              list[str] = []
    must_avoid:                list[str] = []
    all_requirements:          list[Requirement] = []  # ordered by priority
```

### `CVVariantMetadata`

Metadata for one CV variant, loaded from `data/cvs/metadata/*.json`.

```python
class CVVariantMetadata(BaseModel):
    variant_id:     str         # e.g. "cv_ml_engineer"
    file_path:      Path
    role_families:  list[str]   # e.g. ["ml", "data-science"]
    skills:         list[str]
    tools:          list[str]
    summary:        str
```

### `InternalKnowledge`

All approved internal documents loaded for a run.

```python
class InternalKnowledge(BaseModel):
    master_profile:    dict[str, Any]        # parsed master_profile.json
    cv_variants:       list[CVVariantMetadata]
    personal_skills:   str                   # raw Markdown text
    project_docs:      dict[str, str]        # filename → raw text
    previous_letters:  dict[str, str]        # filename → raw text
```

### `SelectedCV`

Result of the `select_cv_variant` stage.

```python
class SelectedCV(BaseModel):
    variant_id:    str
    metadata:      CVVariantMetadata
    full_text:     str        # raw text of the CV file
    selection_reason: str     # brief rationale
```

### `EvidenceItem`

A single claim → source mapping.

```python
class EvidenceItem(BaseModel):
    claim:        str         # the factual statement
    source_type:  str         # "master_profile" | "cv_variant" | "personal_skills" | "project_doc" | "previous_letter"
    source_file:  str         # relative path within data/
    passage:      str         # verbatim excerpt supporting the claim
```

### `EvidenceMap`

Complete mapping of selected claims to approved sources.

```python
class EvidenceMap(BaseModel):
    items:        list[EvidenceItem]
    known_gaps:   list[str]   # requirements for which no evidence was found
    assumptions:  list[str]   # explicit assumptions made when evidence was partial
```

### `SoftSkill`

A selected soft skill with evidence.

```python
class SoftSkill(BaseModel):
    name:          str        # from personal_skills.md
    behaviour:     str        # observable behaviour or outcome (not a bare adjective)
    evidence_item: EvidenceItem
```

### `SectionPlan`

One planned section of the cover letter.

```python
class SectionPlan(BaseModel):
    title:          str       # e.g. "role_fit", "relevant_experience", "working_style", "motivation", "closing"
    key_claims:     list[str]
    evidence_refs:  list[str] # claim texts from EvidenceMap
    soft_skills:    list[str] = []
```

### `ContentPlan`

Structured plan produced before any prose is generated.

```python
class ContentPlan(BaseModel):
    template_id:          str
    selected_cv_variant:  str
    mode:                 WritingMode
    sections:             list[SectionPlan]
    selected_soft_skills: list[SoftSkill]
    evidence_map:         EvidenceMap
    open_questions:       list[str]   # unresolved ambiguities
    assumptions:          list[str]
```

### `LetterDraft`

The generated cover letter prose.

```python
class LetterDraft(BaseModel):
    text:              str       # full Markdown cover letter text
    char_count:        int
    mode:              WritingMode
    content_plan_hash: str       # SHA-256 of the ContentPlan used
```

### `CVTailoringPlan`

Instructions for adapting the selected CV variant.

```python
class CVTailoringChange(BaseModel):
    section:      str   # which CV section to modify
    action:       str   # "emphasise" | "reorder" | "include" | "exclude"
    rationale:    str
    evidence_ref: str | None = None

class CVTailoringPlan(BaseModel):
    base_variant_id: str
    changes:         list[CVTailoringChange]
    tailored_text:   str       # full Markdown tailored CV text
```

### `ValidationResult`

Result for a single validation rule.

```python
class RuleStatus(str, Enum):
    pass_   = "pass"
    fail    = "fail"
    warning = "warning"

class ValidationResult(BaseModel):
    rule:         str
    status:       RuleStatus
    detail:       str | None = None    # offending excerpt or message on failure
```

### `ValidationReport`

Aggregate validation report across all rules.

```python
class ValidationReport(BaseModel):
    target:      str           # "letter" | "cv"
    results:     list[ValidationResult]
    passed:      bool          # True only if all results are pass or warning
    violations:  list[str]     # rule names that failed
```

### `WorkflowState`

The typed container accumulated and threaded through all LangGraph nodes.
Every field is `None` until the corresponding stage populates it.

```python
class WorkflowState(BaseModel):
    config:               MergedConfig
    job_context:          JobContext | None = None
    requirements:         RequirementExtraction | None = None
    knowledge:            InternalKnowledge | None = None
    selected_cv:          SelectedCV | None = None
    evidence_map:         EvidenceMap | None = None
    content_plan:         ContentPlan | None = None
    letter_draft:         LetterDraft | None = None
    cv_tailoring_plan:    CVTailoringPlan | None = None
    letter_validation:    ValidationReport | None = None
    cv_validation:        ValidationReport | None = None
    rewrite_count:        int = 0
    max_rewrites:         int = 2
    run_id:               str     # UUID generated at run start
```

---

## Model Relationships

```
RunInput + StarterTemplate ──merge──▶ MergedConfig
                                           │
                              ┌────────────▼────────────────┐
                              │        WorkflowState        │
                              │  ┌──────────────────────┐  │
                              │  │  JobContext           │  │
                              │  │  RequirementExtraction│  │
                              │  │  InternalKnowledge    │  │
                              │  │  SelectedCV           │  │
                              │  │  EvidenceMap ◀────────┼──┼── EvidenceItem[]
                              │  │  ContentPlan ◀────────┼──┼── SectionPlan[], SoftSkill[]
                              │  │  LetterDraft          │  │
                              │  │  CVTailoringPlan      │  │
                              │  │  ValidationReport×2   │  │
                              │  └──────────────────────┘  │
                              └─────────────────────────────┘
```

---

## Persistence

Each model is serialised to JSON in `output_dir/<run_id>/artifacts/`:

| Model | File |
|---|---|
| RequirementExtraction | `requirements.json` |
| EvidenceMap | `evidence_map.json` |
| ContentPlan | `content_plan.json` |
| LetterDraft | `letter.md` (text only) |
| CVTailoringPlan | `cv_tailoring_plan.json`, `cv_tailored.md` (text) |
| ValidationReport (letter) | `validation_letter.json` |
| ValidationReport (cv) | `validation_cv.json` |
| known gaps | extracted from `evidence_map.json` |
