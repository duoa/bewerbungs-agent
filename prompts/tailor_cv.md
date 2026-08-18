# CV Tailoring Instructions

Your task: adapt the provided CV variant to better match the target job requirements.
You may ONLY work with what is already in the CV — you must not add skills, roles,
employers, tools, dates, or achievements that are not present in the base CV text.

## Permitted changes

- **emphasise**: Move an existing section, bullet, or result higher / give it more
  visual prominence. No new facts added.
- **reorder**: Change the sequence of sections, roles, or bullets to lead with the
  most relevant content for this role.
- **include**: Reinstate a section or bullet that exists in the base CV but was
  previously de-emphasised or placed at the end (only if present in the base text).
- **exclude**: Remove a section or bullet that is clearly irrelevant to this role
  (reduces noise; does not add anything).

## Forbidden changes

- Do NOT write any new skill, tool, technology, metric, project name, employer
  name, or date that does not appear verbatim in the base CV text.
- Do NOT rephrase a bullet to imply a stronger result than stated (e.g. do not
  change "contributed to migration" to "led migration" unless the base CV says "led").
- Do NOT merge two separate bullets to create a combined claim not in the original.

## Output format

Return:
- `tailored_text`: the complete Markdown CV after all changes are applied
- `changes`: one entry per modification with `section`, `action`, `rationale`,
  and optionally `evidence_ref` (claim from the evidence map that justifies it)
- `base_variant_id`: the variant_id of the input CV

If no changes are needed (CV already matches the role well), return the original
text unchanged with an empty `changes` list.
