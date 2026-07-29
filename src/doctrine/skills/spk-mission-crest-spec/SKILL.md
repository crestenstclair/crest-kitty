---
name: spk-mission-crest-spec
description: "Operate the Spec Kitty crest-spec phase: author the bedrock DDD declaration (resources, assets, proof) a mission's plan, tasks, and code derive from."
---

# spk-mission-crest-spec

Use this skill when a mission has a spec and the project carries a crest-spec
(the machine-readable DDD declaration at `.kittify/crest-spec/`). The
crest-spec is the single source of implementation intent: planning, work
packages, code generation, and proof derive FROM it — it is never reconciled
TO other documents after the fact.

## Flow

1. Invoke `/spec-kitty.crest-spec` against the active mission (after
   `/spec-kitty.specify`, before `/spec-kitty.plan`).
2. Ground in the current model: `spec-kitty crest-spec context`.
3. Declare the mission's `crest_spec_impact` in `meta.json`
   (`structural` | `predeclared` | `none`) — explicit, never a silent default.
4. For structural missions, edit the crest-spec sources FIRST: intent (goals,
   capabilities, requirements), architecture (contexts, value objects,
   aggregates, ports, adapters), the generation layer (assetKinds, assets),
   and proof (validations, witnesses, evidence, invariants).
5. Validate until the model closes: `spec-kitty crest-spec doctor` — the
   loader's referential integrity is the tool; lean on it.
6. Commit the crest-spec edits ahead of any planning artifact, then hand off
   to `spk-mission-plan`.

## Guardrails

- If the crest-spec does not declare it, it does not get built: the plan gate
  (`CREST_SPEC_UNDERIVED`), the implement gate (`crest_spec_underived`), and
  the accept gates (`crest_spec_unproven`, `crest_spec_duplicate_artifacts`)
  enforce this executably.
- Never edit the crest-spec to permit code that was already planned, and
  never narrow `nonGoals` merely to make a mission admissible — conflicts
  with the product authority (`DESIGN.md`) are decided deliberately with the
  operator, in this phase.
- Do not produce `data-model.md` or `contracts/`; do not restate crest-spec
  declarations in prose. Work packages derive from `assets[]` — an
  underspecified asset is fixed in the crest-spec, not in a WP prompt.
