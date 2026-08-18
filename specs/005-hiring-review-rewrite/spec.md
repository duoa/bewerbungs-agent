# Feature Specification: Hiring-Manager Review and Targeted Rewrite Stage

**Feature Branch**: `005-hiring-review-rewrite`  
**Created**: 2026-04-15  
**Status**: Draft  
**Input**: User description: "Add a structured hiring-review-and-rewrite stage to the application pipeline. After the cover letter is generated, the system should evaluate it from the perspective of a hiring manager for the target role and identify section-level strengths, weaknesses, severity, and priority fixes for clarity, specificity, credibility, role relevance, and differentiation. Based on that review, the system should rewrite only the affected parts of the letter, not the entire document. The reviewer-rewriter must not invent facts, must not add unsupported claims, and must preserve the evidence-grounded architecture by working only from the generated letter, role requirements, and structured review output. The goal is to improve weak or generic sections through targeted rewriting without changing strong sections unnecessarily."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automated Section-Level Review of Cover Letter (Priority: P1)

After the cover letter draft is generated, the pipeline automatically evaluates it through the lens of a hiring manager for the target role. The review produces a structured, section-level report that identifies each section's strengths and weaknesses across five dimensions: clarity, specificity, credibility, role relevance, and differentiation. Each weakness receives a severity rating (low/medium/high) and a priority fix description.

**Why this priority**: This is the foundational capability — without the structured review output, targeted rewriting cannot be performed. The review itself delivers standalone value by making improvement areas explicit and machine-readable.

**Independent Test**: Can be tested by running the review stage on an existing draft letter and a job description file and asserting that a structured report is produced with section names, per-dimension assessments, and at minimum one strength and one weakness entry.

**Acceptance Scenarios**:

1. **Given** a generated cover letter draft and extracted role requirements, **When** the review stage runs, **Then** it produces a structured report with per-section entries each containing: section name, list of strengths, list of weaknesses with severity (low/medium/high) and priority fix description, and an overall assessment.
2. **Given** a cover letter where all sections are strong, **When** the review stage runs, **Then** the report identifies no high-severity weaknesses and the downstream rewrite stage makes no modifications.
3. **Given** a cover letter that addresses a skill irrelevant to the role, **When** the review stage runs, **Then** the role-relevance dimension flags that section as weak with severity ≥ medium.

---

### User Story 2 - Targeted Rewrite of Weak Sections Only (Priority: P2)

Using the structured review output, the system rewrites only the sections identified as having weaknesses above a minimum severity threshold. Sections rated as strong are preserved verbatim. The rewrite draws exclusively from the generated letter, role requirements, and the review output — no new facts, tools, employers, or achievements may be introduced.

**Why this priority**: The rewrite delivers the tangible quality improvement. P2 because it depends on US1 completing first and adds complexity that can be deferred if the review output alone is sufficient for some use cases.

**Independent Test**: Can be tested by injecting a pre-built review report with known weak sections into the rewrite stage, then asserting that: (a) flagged sections are modified, (b) non-flagged sections are unchanged, and (c) no content appears in the output that was absent from both the original letter and the role requirements.

**Acceptance Scenarios**:

1. **Given** a review report with two sections flagged as high-severity weak and two sections as strong, **When** the rewrite stage runs, **Then** only the two weak sections appear modified in the output; the two strong sections are byte-for-byte identical to the input letter.
2. **Given** any review report, **When** the rewrite stage runs, **Then** the rewritten letter contains no claim, skill, employer name, project, or quantitative result that did not exist in the source letter or extracted role requirements.
3. **Given** a section flagged as low-severity weak, **When** the rewrite stage runs with a medium minimum-severity threshold configured, **Then** that section is left unchanged.

---

### User Story 3 - Configurable Review Dimensions and Rewrite Threshold (Priority: P3)

The review stage's active evaluation dimensions and the minimum weakness severity that triggers a rewrite can be configured via the starter template or run-level overrides. Operators can restrict evaluation to a subset of dimensions (e.g., clarity + credibility only) and raise the threshold to reduce over-editing.

**Why this priority**: P3 because the system works correctly with sensible defaults (all five dimensions, medium threshold). Configurability adds operational flexibility but is not required for the core value proposition.

**Independent Test**: Can be tested by setting `review_dimensions: [clarity, credibility]` and `rewrite_threshold: high` in a template override, running a full pipeline, and asserting that the review report only contains clarity and credibility dimension entries and that medium-severity sections are not rewritten.

**Acceptance Scenarios**:

1. **Given** a template configured with `review_dimensions: [clarity, role_relevance]`, **When** the pipeline runs, **Then** the review report contains only clarity and role-relevance assessments per section.
2. **Given** `rewrite_threshold: high` configured, **When** the review finds medium-severity weaknesses, **Then** those sections are not rewritten.

---

### Edge Cases

- What happens when the generated letter has no section structure (single prose block)? The reviewer treats the entire letter as one section rather than failing.
- What happens when all sections are flagged as weak? The system rewrites all sections but must not fabricate content.
- What happens when the review LLM call fails? The pipeline logs the error, skips both review and rewrite stages, returns the original letter unchanged, and does not abort the run.
- What happens when the rewrite produces a letter longer than the configured length limit? The existing validation stage catches this; review and rewrite stages are not responsible for enforcing length.
- What happens when a section contains both strengths and a weakness? Both are recorded; the weakness severity determines whether rewriting is triggered.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST evaluate the generated cover letter from the perspective of a hiring manager for the target role after the write-letter stage completes.
- **FR-002**: System MUST produce a structured, section-level review report containing, for each identified section: section name, strengths list, weaknesses list (each with severity and priority fix description), and an overall section assessment.
- **FR-003**: System MUST evaluate each section across five dimensions: clarity, specificity, credibility, role relevance, and differentiation.
- **FR-004**: System MUST assign a severity level (low, medium, or high) to each identified weakness.
- **FR-005**: System MUST rewrite only sections whose weaknesses meet or exceed the configured minimum severity threshold; sections below the threshold or with no weaknesses MUST be preserved verbatim.
- **FR-006**: System MUST NOT introduce any fact, skill, tool, employer, date, responsibility, achievement, or quantitative result that is not present in the source letter or the extracted role requirements.
- **FR-007**: System MUST work exclusively from the generated letter, extracted role requirements, and the structured review output during the rewrite — no external knowledge retrieval or profile re-reading.
- **FR-008**: System MUST handle a missing section structure gracefully by treating the entire letter as a single section.
- **FR-009**: If the review or rewrite LLM call fails, the pipeline MUST log the failure, skip those stages, and return the original generated letter unchanged without aborting the run.
- **FR-010**: System MUST expose configuration for active review dimensions (subset of the five) and minimum rewrite severity threshold via the starter template and run-level override mechanism.
- **FR-011**: The review and rewrite stages MUST be inserted into the existing pipeline after the write-letter stage and before the existing validation stage.

### Key Entities

- **SectionReview**: A per-section assessment — section name, list of strengths (strings), list of weaknesses (each: text, severity enum, priority fix string), overall section assessment.
- **LetterReviewReport**: Full structured output of the review stage — list of SectionReview entries plus an overall letter assessment string.
- **RewritePlan**: Derived from LetterReviewReport — identifies which sections need rewriting and the targeted fixes to apply; serves as the input contract for the rewrite stage.
- **ReviewConfig**: Configuration entity — active dimensions (list of enum values from: clarity, specificity, credibility, role_relevance, differentiation) and minimum severity threshold (low/medium/high).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The review stage produces a structured report with section-level entries for 100% of runs where a cover letter was generated.
- **SC-002**: For letters with at least one weak section above threshold, the rewrite stage modifies those sections and leaves all other sections unchanged in 100% of cases.
- **SC-003**: Zero instances of fabricated content (skills, employers, results not present in the source letter or role requirements) are detectable by automated content-origin checks in the test suite.
- **SC-004**: When the review or rewrite LLM call fails, the pipeline completes successfully with the original letter and logs a warning — pipeline abort rate from review/rewrite failures is 0%.
- **SC-005**: The combined review + rewrite stage adds exactly two additional LLM round-trips to the pipeline (one for review, one for rewrite of weak sections), not more.

## Assumptions

- The generated letter produced by the write-letter stage has recognizable section structure (headings or clear paragraph breaks) in the majority of cases; single-block handling is best-effort.
- The evidence-grounded constraint (FR-006, FR-007) is enforced via prompt design and validated by automated tests — it is not enforced by a separate fact-checking LLM call.
- The review and rewrite stages use the same Claude model and thinking configuration mechanism introduced in Feature 004 (MLflow/thinking observability), including per-stage thinking overrides and MLflow logging.
- Default configuration: all five dimensions active, minimum rewrite severity = medium.
- The LetterReviewReport is stored in WorkflowState and available for downstream inspection and MLflow tracking.
- The existing validation rules (char count, forbidden phrases, etc.) still apply to the rewritten letter, handled by the unchanged validate stage downstream.
- The rewrite stage assembles the final letter by replacing weak sections with rewritten versions and keeping strong sections verbatim — output is a complete letter, not a diff or patch.
