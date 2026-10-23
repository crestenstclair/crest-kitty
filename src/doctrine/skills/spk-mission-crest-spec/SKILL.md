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
4. Load `writing-clean-code` and keep it loaded (see **Design Discipline**
   below). The `contexts` block is a DDD declaration; SOLID is the test for
   whether it will hold.
5. For structural missions, edit the crest-spec sources FIRST: intent (goals,
   capabilities, requirements), architecture (contexts, value objects,
   aggregates, ports, adapters), the generation layer (assetKinds, assets),
   and proof (validations, witnesses, evidence, invariants).
6. Validate until the model closes: `spec-kitty crest-spec doctor` — the
   loader's referential integrity is the tool; lean on it.
7. Commit the crest-spec edits ahead of any planning artifact, then hand off
   to `spk-mission-plan`.

## Design Discipline

Invoke `Skill(writing-clean-code)` before declaring structure. DDD and SOLID
are not two vocabularies here — they are the same decisions named twice, and
the crest-spec is where they are made:

- **SRP** — a context, aggregate, or `domainService` you cannot describe
  without "and" is two resources sharing one ID.
- **OCP** — a capability that grows by adding an `adapter` or `asset` is open
  for extension; one that grows by editing a resource's branch list is a switch
  statement with an ID.
- **LSP / ISP** — every adapter behind a `port` swaps in without its caller
  knowing; a port whose consumers each use a different third of it is three
  ports.
- **DIP / DI** — this is what `layerRules` encode. Domain declares ports;
  adapters depend inward. A `domainService` naming a concrete adapter has
  `new`-ed its dependency at the model level.

Read the reference matching the decision at hand (`references/solid.md`,
`references/design-patterns.md`, `references/dependency-injection.md`); do not
load all four to add one value object.

**Why here.** Work packages derive from `assets[]`, code derives from work
packages, proof derives from `validations` — so an SRP violation or an inverted
`layerRule` is copied faithfully into every downstream artifact by design.
Post-merge `adversarial-review` catches the smell in the code; it cannot catch
it in the bedrock that generated the code.

**Counterweight.** SOLID never licenses declaring resources the mission's
`requirements` do not need. A `port` with one adapter and no second in prospect
is speculative generality, and the crest-spec makes it load-bearing for every
mission that follows. The Rule of Three applies to declarations too.

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
