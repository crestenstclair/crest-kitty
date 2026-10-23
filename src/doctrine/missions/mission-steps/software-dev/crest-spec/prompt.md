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

### 3. Load the design discipline BEFORE declaring structure

Invoke the `writing-clean-code` skill and keep it loaded for the rest of this
phase:

```
Skill(writing-clean-code)
```

The crest-spec's `contexts` block is a DDD declaration, and SOLID is the test
for whether that declaration will hold. These are not two vocabularies — they
are the same decisions named twice, and the crest-spec is where they are made:

| Principle | What it constrains in the crest-spec |
|---|---|
| **SRP** | A bounded context, an aggregate, or a `domainService` you cannot describe without "and" is two resources wearing one ID. Split it here, before any WP owns files under it. |
| **OCP** | A capability that grows by adding an `adapter` or an `asset` is open for extension. One that grows by editing an existing resource's branch list is a switch statement with an ID — it will be edited by every future mission. |
| **LSP** | Every `adapter` behind a `port` must be swappable without its `applicationService` knowing which one it got. An adapter that needs the caller to special-case it means the port boundary is drawn in the wrong place. |
| **ISP** | Ports stay narrow. A `port` whose consumers each use a different third of its operations is three ports; declaring it as one forces every adapter to implement methods nobody calls. |
| **DIP** | This is what `layerRules` encode. Domain declares ports; adapters implement them and depend inward. A `layerRule` permitting the domain to reference an adapter has inverted the dependency and no amount of downstream code review recovers it. |
| **DI** | A `domainService` that names a concrete adapter in its declaration has `new`-ed its dependency at the model level. It receives a `port`. |
| **Patterns** | Read `references/design-patterns.md` before inventing a resource shape. Choose the pattern that solves a problem present in this mission's `requirements` — a `port` with exactly one adapter and no second one in prospect is speculative generality, and the crest-spec makes it permanent. |

Read the reference that matches the decision in front of you
(`references/solid.md` for boundaries, `references/design-patterns.md` for
composition-vs-inheritance, `references/dependency-injection.md` for wiring);
do not load all four to add one value object.

**Why here and not at review.** A structural mistake in the crest-spec is not
local. Work packages derive from `assets[]`, code derives from work packages,
and proof derives from `validations` — so a context that violates SRP or a
`layerRule` that inverts DIP is copied faithfully into every downstream
artifact by design. Post-merge review (`adversarial-review`) catches the smell
in the code; it cannot catch it in the bedrock that generated the code. The
cheapest fix is a resource ID that does not exist yet.

**What this does not license.** Applying SOLID never justifies declaring
resources this mission's `requirements` do not need. Structure that exists
"for future flexibility" is speculative generality, and the crest-spec makes
it load-bearing for every mission that follows. The Rule of Three applies to
declarations as much as to code.

### 4. Author the crest-spec (structural missions)

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

Before moving on, run the `writing-clean-code` self-check against what you
declared, not against code you have not written:

1. Can every new context, aggregate, and service be described without "and"?
2. Does any `domainService` or `applicationService` name a concrete adapter
   instead of a `port`?
3. Would the next obvious variant of this capability require editing an
   existing resource rather than adding an `adapter` or `asset`?
4. Is there a resource whose name lies about what it holds, or a `port` no
   consumer uses in full?
5. Does every declared abstraction solve a problem in this mission's
   `requirements` — or did one get added for a second implementation that does
   not exist yet?

### 5. Validate until the model closes

```bash
spec-kitty crest-spec doctor
```

Repair every diagnostic. The phase is not complete while the doctor reports
the crest-spec invalid.

### 6. Commit the crest-spec changes

Commit the `.kittify/crest-spec/` edits (plus the `meta.json` impact
declaration) before planning, following the repository's commit discipline.
The plan gate evaluates the mission diff — uncommitted working-tree edits
count, but the authored crest-spec belongs in history ahead of `plan.md`.

### 7. STOP and report

Report: the declared `crest_spec_impact`, the canonical resource IDs added /
changed / retired, the assets that will produce this mission's files, the
validations/witnesses covering the new behavior, and any structural decision
where SOLID and the shortest declaration disagreed — name which one won and
why. Then STOP.

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
