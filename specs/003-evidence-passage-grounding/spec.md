# Feature Specification: Evidence Passage Grounding

**Feature Branch**: `003-evidence-passage-grounding`  
**Created**: 2026-04-07  
**Status**: Draft  
**Input**: User description: "Improve the application-writing pipeline so that evidence retrieval works on passage level rather than truncated document heads. The system must preserve concrete approved source passages through evidence mapping and content planning, and the letter writer must generate letters from the content plan plus approved anchor passages only. The goal is to reduce generic wording while preserving factual traceability and writer isolation from raw profile documents."

## Clarifications

### Session 2026-04-15

- Q: What is the failure behavior when a passage is empty or invalid? → A: Continue — drop the item from the evidence map and add its claim to `known_gaps`. Do not abort the pipeline.
- Q: Should the system validate that LLM-returned passages are verbatim matches to the source document? → A: No semantic or verbatim claim validation in this iteration. The LLM is trusted to return appropriate excerpts given correct prompting.
- Q: Is golden fixture / output evaluation in scope? → A: No. No golden fixture evaluation for this iteration.
- Q: What is the change scope? → A: Restricted to four areas: passage chunking in `build_evidence_map`, evidence-map enrichment (EvidenceItem.passage population), content-plan anchor passage propagation, and writer prompt input. The existing LangGraph pipeline, validation architecture, and all other stages remain unchanged.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Passage-Level Evidence Extraction (Priority: P1)

When the pipeline builds the evidence map, it extracts specific verbatim passages from source documents (CV, skills, project docs, previous letters) that support each claim — rather than passing truncated document heads. Each EvidenceItem in the evidence map carries the exact quoted passage alongside the claim and its source location.

**Why this priority**: This is the foundational change. Without passage-level extraction, every downstream improvement (plan grounding, writer isolation) cannot work. It directly addresses the root cause of generic wording: the LLM currently invents paraphrases because it receives only the first N characters of each document.

**Independent Test**: Can be tested by running only the `build_evidence_map` stage with a known profile and verifying that each returned EvidenceItem contains a `passage` field with text that verbatim appears in the source document and is not limited to the first 3000 characters.

**Acceptance Scenarios**:

1. **Given** a profile where a relevant achievement appears after the 3000-character mark in a CV, **When** `build_evidence_map` runs, **Then** the resulting EvidenceItem contains a passage that includes text from beyond the 3000-character cutoff.
2. **Given** a profile with multiple CVs and project docs, **When** `build_evidence_map` runs, **Then** every EvidenceItem has a non-empty `passage` field that is a verbatim excerpt from the declared `source_file`.
3. **Given** a document with no content matching the job requirements, **When** `build_evidence_map` runs, **Then** no EvidenceItem is created for that document (no hallucinated passages).

---

### User Story 2 - Passage Propagation Through Content Plan (Priority: P2)

When the content planner produces a structured content plan, it carries the approved anchor passages from the evidence map into the plan — so that each section's evidence references include both the claim text and the verbatim passage that backs it. The plan remains the sole source of truth for the letter writer.

**Why this priority**: Without passage propagation into the plan, the letter writer still has no access to concrete wording and will generate generic text. This is the second link in the traceability chain.

**Independent Test**: Can be tested by running `plan_content` with a pre-built evidence map (containing passages) and asserting that the resulting `ContentPlan` sections carry the verbatim passages from the evidence map, not just claim strings.

**Acceptance Scenarios**:

1. **Given** an evidence map where every EvidenceItem has a non-empty `passage`, **When** `plan_content` runs, **Then** the resulting `ContentPlan` sections include the approved passages associated with each evidence reference.
2. **Given** a content plan produced from passage-grounded evidence, **When** the plan JSON is serialized, **Then** it contains no raw InternalKnowledge fields — only claims and their approved passages.
3. **Given** an evidence map with a known gap (no evidence for a required skill), **When** `plan_content` runs, **Then** the plan explicitly marks that section as having no anchor passage rather than fabricating one.

---

### User Story 3 - Letter Writer Isolation via Anchor Passages (Priority: P3)

The letter writer generates cover letter prose using only the structured content plan (which now includes approved anchor passages) and never receives raw profile documents. It must anchor its sentences to the approved passages, producing factual, traceable output with minimal generic filler.

**Why this priority**: This is the final output quality improvement. It depends on US1 and US2 being complete, but delivers the user-visible value: a letter with concrete, grounded language instead of generic filler phrases.

**Independent Test**: Can be tested by running `write_letter` with a mock content plan containing known anchor passages and verifying that the generated letter text contains vocabulary and phrases drawn from those passages, and that no raw profile document content (beyond what appears in passages) is present in the prompt.

**Acceptance Scenarios**:

1. **Given** a content plan with approved anchor passages, **When** `write_letter` runs, **Then** the generated letter includes phrasing or keywords drawn from the anchor passages rather than invented descriptions.
2. **Given** a content plan, **When** `write_letter` constructs its prompt, **Then** the prompt contains no reference to the full CV text, full personal_skills document, or full project documents — only plan JSON with embedded passages.
3. **Given** a letter generated from anchor passages, **When** the letter is inspected, **Then** every concrete factual claim (tool name, metric, role title) can be traced back to a passage in the content plan.

---

### Edge Cases

- What happens when a source document is very short (under 200 characters) and the entire document is essentially one passage?
- How does the system handle a passage that is a duplicate across multiple source documents (same text appears in CV and a previous letter)?
- When the LLM returns a passage that does not verbatim match the source document: accepted as-is in v1 (no semantic or verbatim validation is performed; the LLM prompt is relied upon to produce appropriate excerpts).
- How does the system behave when no passage can be extracted for a high-priority claim (e.g., the job requires cloud experience but the profile has none)?
- What happens if an anchor passage is extremely long (e.g., a 2000-character project description paragraph)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `build_evidence_map` stage MUST extract a specific verbatim passage from the source document for each EvidenceItem it produces, not a truncated document head.
- **FR-002**: Each `EvidenceItem` MUST carry: `claim` (short factual statement), `source_type`, `source_file`, and `passage` (verbatim excerpt from source_file that substantiates the claim).
- **FR-003**: The `write_letter` stage MUST NOT receive full raw documents or truncated document heads as grounding context. Its prompt MUST be constructed solely from the serialised `ContentPlan` (which embeds approved anchor passages). Raw `InternalKnowledge` fields MUST NOT appear in the letter-writer prompt.
- **FR-004**: The `plan_content` stage MUST propagate approved anchor passages from the `EvidenceMap` into the `ContentPlan` structure, so that each section's evidence references include both the claim and the associated passage.
- **FR-005**: The `write_letter` stage MUST construct its prompt from the `ContentPlan` JSON only (which includes anchor passages), with no additional access to raw `InternalKnowledge` fields.
- **FR-006**: The system MUST validate that each passage in an EvidenceItem is non-empty; items with empty passages MUST be dropped from the evidence map and their claims added to `known_gaps`. The pipeline MUST continue (not abort) when gaps exist. No semantic or verbatim validation of passage content is performed.
- **FR-007**: The `content_plan_hash` integrity mechanism MUST remain intact: the hash MUST cover the evidence map including passages, so that any post-plan passage substitution is detectable.
- **FR-008**: The system MUST remain backward-compatible with profiles that do not have project docs or previous letters — passage extraction MUST work with CV and personal_skills alone.

### Key Entities

- **EvidenceItem**: A single grounded claim. Key attributes: `claim` (short factual statement), `source_type` (cv/skills/project/letter), `source_file` (filename), `passage` (verbatim excerpt substantiating the claim). The `passage` field transitions from "currently underused" to "required and validated".
- **EvidenceMap**: The collection of EvidenceItems produced by `build_evidence_map`. After this feature, each item in `EvidenceMap.items` MUST have a non-empty passage.
- **ContentPlan**: The structured plan produced by `plan_content`. After this feature, each section's evidence references carry the approved anchor passages so the letter writer can anchor prose to them.
- **AnchorPassage**: The verbatim excerpt from a source document that substantiates a claim. Flows from EvidenceItem through ContentPlan to the letter-writer prompt.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every EvidenceItem in a generated evidence map has a non-empty `passage` field; zero items with empty passages in passing pipeline runs.
- **SC-002**: The letter-writer prompt contains no raw CV text, no raw personal_skills text, and no raw project document text beyond what is embedded in anchor passages inside the ContentPlan JSON.
- **SC-003**: A cover letter generated from a profile where a key achievement appears beyond the first 3000 characters of the CV correctly references that achievement (verified by keyword presence in output).
- **SC-004**: All existing unit and integration tests (excluding any golden output fixtures, which are out of scope) continue to pass after the change; no regression in pipeline correctness.
- **SC-005**: The `content_plan_hash` validation in `source_compliance` continues to detect tampering when a passage is altered between plan creation and letter writing.

## Assumptions

- No new models or classes are needed. Two new optional fields with safe defaults are added to existing models: `relevance_note: str = ""` on `EvidenceItem` and `anchor_passages: list[str] = []` on `SectionPlan`. The existing `EvidenceItem.passage` field carries verbatim excerpts; it transitions from underused to required-non-empty.
- The LLM (claude-sonnet-4-6 via tool-use) is capable of extracting specific verbatim passages from documents provided in context, given appropriate instructions in the `build_evidence_map` prompt.
- Documents in the profile are small enough to fit in a single LLM context call alongside the job requirements (typical CV: 2–6 KB, skills: 1–2 KB, project docs: 1–3 KB each); no chunking strategy is needed for v1.
- Passage extraction happens at the `build_evidence_map` stage; no separate "retrieval" or vector-search step is introduced.
- The `write_letter` stage already operates in isolation from raw `InternalKnowledge` (confirmed by code review); the change is to enrich the ContentPlan it receives with passages, not to restructure the isolation boundary.
- Backward compatibility: profiles with no project docs or previous letters are fully supported; passage extraction works with CV + skills alone.
- The `tailor_cv` parallel branch is out of scope for this feature — it is not affected by passage grounding.
- Change scope is intentionally minimal: only four areas are modified — `build_evidence_map` (passage chunking + enrichment), `plan_content` (anchor passage propagation into ContentPlan), and `write_letter` (writer prompt updated to use passages from plan). All other stages, the LangGraph graph structure, and the validation architecture remain unchanged.
- No golden fixture or output quality evaluation is included in this iteration.
- No semantic or verbatim validation of LLM-returned passages is performed; correct passage extraction is enforced by prompt design, not post-hoc checking.
