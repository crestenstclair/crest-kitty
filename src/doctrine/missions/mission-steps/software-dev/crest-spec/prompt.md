---
description: Author the crest-spec — the bedrock this mission derives from
---
# /spec-kitty.crest-spec - Author the Crest-Spec

**The crest-spec is the bedrock.** It is the single source of implementation
intent: resources declare what exists, `assets` declare the files that realize
them and the prompts that produce them, `proof` declares what must be true and
how it is measured. Planning, work packages, code, and acceptance all derive
FROM the crest-spec — it is never reconciled TO other documents after the
fact. This phase runs after `/spec-kitty.specify` and before
`/spec-kitty.plan`, and it is where the crest-spec changes happen. If the
crest-spec does not declare it, it does not get built.

## 📍 WORKING DIRECTORY: Stay in the repository root checkout

**IMPORTANT**: Crest-spec authoring works in the repository root checkout. NO
worktrees created. The crest-spec sources live at `.kittify/crest-spec/`
(configurable via `crest_spec.root` in `.kittify/config.yaml`).

## Mission Handle Rule

`/spec-kitty.crest-spec` operates on an existing mission, so use
`--mission <handle>` when the CLI needs a mission selector (`mission_id`,
`mid8`, or `mission_slug`; ambiguity is a structured error, no silent
fallback).

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Applicability

- **No crest-spec in this project** (`spec-kitty crest-spec context` reports
  not applicable): this phase is a no-op. Report that and suggest
  `/spec-kitty.plan`. Do not invent a crest-spec unless the operator asks for
  one.
- **Crest-spec present**: this phase is mandatory. Every mission declares its
  relationship to the crest-spec (`crest_spec_impact`, below), and structural
  missions author their crest-spec changes HERE — the plan gate
  (`CREST_SPEC_UNDERIVED`) refuses to advance a structural mission whose
  crest-spec is untouched.

## Execution Steps

### 1. Ground in the current model

```bash
spec-kitty crest-spec context
```

Read the interpretation contract and the resolved project value. If the
command fails with diagnostics, STOP and repair first (`spec-kitty crest-spec
doctor`) — an invalid crest-spec fails every derivation gate closed.

### 2. Declare the mission's impact

Decide which of the three this mission is, and record it in
`kitty-specs/<mission>/meta.json` as a top-level field:

```json
{ "crest_spec_impact": "structural" }
```

- `structural` — the mission adds, changes, or retires system structure
  (resources, assets, proof). The crest-spec is edited in this phase.
- `predeclared` — the crest-spec already declares this mission's work (a
  prior mission authored it). No edits needed; work packages still trace to
  declared assets.
- `none` — no structural change (doc fix, flaky-test repair, config tweak).
  The remaining steps are skipped; report and suggest `/spec-kitty.plan`.

Do not guess. If the spec's scope is ambiguous, ask the operator — this
declaration arms or disarms the implement and accept gates.

### 3. Author the crest-spec (structural missions)

Edit the source files under `.kittify/crest-spec/` FIRST, before any planning
artifact exists:

- **Intent**: `goals`, `capabilities` (+ `acceptance` scenarios),
  `requirements`, `actors`, `nonGoals`.
- **Architecture**: bounded `contexts` — `valueObjects`, `aggregates`,
  `ports`, `repositories`, `domainServices`, `applicationServices` — plus
  `adapters`, `contextMap`, `layers`, `layerRules`.
- **Generation layer**: `assetKinds` (with `filePattern`) and `assets` — every
  file this mission will produce must trace to an asset (`kind`, `targets`,
  `prompts`, `profile`, attached `validations`). The implement gate refuses a
  work package whose `owned_files` no asset covers (`crest_spec_underived`).
- **Proof**: `validations`, `witnesses`, `evidence`, `invariants` — every
  behavioral resource this mission adds needs declared proof; acceptance
  blocks `crest_spec_unproven` otherwise. Proof is declared where behavior is
  declared, not improvised at review.

Authoring rules:

- The loader closes the model under you: undeclared or ambiguous references
  fail immediately. Lean on that — author, validate, repair, repeat. It is
  faster and safer than discovering gaps at acceptance.
- `DESIGN.md` and visual references remain the product authority for *what
  the product should be*; the crest-spec is the executable declaration of
  *what the system is*. When they disagree, resolve it deliberately with the
  operator NOW — never silently edit the crest-spec to permit code that was
  already planned, and never narrow `nonGoals` merely to make a mission
  admissible.
- Keep declarations terse and relational. The crest-spec is not a prose
  design document.

### 4. Validate until the model closes

```bash
spec-kitty crest-spec doctor
```

Repair every diagnostic. The phase is not complete while the doctor reports
the crest-spec invalid.

### 5. Commit the crest-spec changes

Commit the `.kittify/crest-spec/` edits (plus the `meta.json` impact
declaration) before planning, following the repository's commit discipline.
The plan gate evaluates the mission diff — uncommitted working-tree edits
count, but the authored crest-spec belongs in history ahead of `plan.md`.

### 6. STOP and report

Report: the declared `crest_spec_impact`, the canonical resource IDs added /
changed / retired, the assets that will produce this mission's files, and the
validations/witnesses covering the new behavior. Then STOP.

**Next suggested command**: `/spec-kitty.plan` (derives from what you just
authored; its plan.md records the `## Crest-Spec Derivation` section).

## Forbidden in this phase and every later one

- ❌ `data-model.md` and `contracts/` planning artifacts — they fork
  `valueObjects`, `aggregates`, and `ports` and are rejected at acceptance
  (`crest_spec_duplicate_artifacts`) when a crest-spec exists.
- ❌ Hand-written work-package prompts that restate asset `targets` /
  `prompts` — work packages are derived from `assets[]`; a gap in an asset is
  fixed in the crest-spec, not papered over in a WP prompt.
- ❌ Editing the crest-spec from inside plan/tasks/implement to legalize work
  already decided — that inversion is the failure mode this phase exists to
  prevent.
