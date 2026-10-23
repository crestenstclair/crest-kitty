# Crest-Spec Action — Governance Guidelines

These guidelines govern the crest-spec authoring phase in the software-dev
mission. They are injected at runtime via the charter context bootstrap.

---

## Derivation Direction (binding)

- The crest-spec is the single source of implementation intent. Plan, tasks,
  code, validations, and evidence derive FROM it; nothing is reconciled TO it
  after the fact.
- A mission that adds, changes, or retires system structure edits the
  crest-spec BEFORE any planning artifact exists. The diff shows crest-spec
  changes preceding `plan.md`.
- Never edit the crest-spec to permit code that was already planned; never
  narrow `nonGoals` merely to make a mission admissible. Conflicts with the
  product authority (`DESIGN.md`, visual references) are resolved deliberately
  with the operator during this phase.

## Impact Declaration

- Every mission in a crest-spec project declares `crest_spec_impact` in
  `meta.json`: `structural`, `predeclared`, or `none`. The declaration is
  explicit — gates never assume a default.
- `none` is for missions that genuinely change no structure (doc fixes,
  flaky-test repairs). It disarms the asset-coverage and proof gates for this
  mission; using it to dodge authoring is a review rejection.

## Structural Design Discipline

- The `writing-clean-code` skill is loaded during this phase and governs the
  `contexts` block. DDD resources and SOLID are the same decisions named
  twice: SRP bounds a context, OCP decides whether a capability grows by
  addition or by edit, LSP/ISP shape `ports`, and DIP is what `layerRules`
  encode.
- A `domainService` or `applicationService` that names a concrete adapter has
  inverted its dependency at the model level; it receives a `port`.
- Structural defects declared here are not local — work packages, code, and
  proof all derive from the declaration, so the crest-spec propagates them by
  design. Post-merge `adversarial-review` finds the smell in the code but
  cannot reach the bedrock that generated it.
- SOLID does not license unrequested structure. An abstraction with one
  implementation and no second in prospect is speculative generality that the
  crest-spec makes permanent; the Rule of Three applies to declarations.

## Model Quality

- Lean on the loader's referential integrity: author, run
  `spec-kitty crest-spec doctor`, repair, repeat until the model closes.
- Declare proof (validations, witnesses, acceptance scenarios) alongside every
  behavioral resource added — acceptance blocks `crest_spec_unproven`.
- Declare an asset (and assetKind `filePattern`) for every file the mission
  will produce — the implement gate blocks `crest_spec_underived`.
- Keep declarations terse and relational; the crest-spec is a model, not a
  prose design document.
