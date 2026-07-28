# crest-synth architecture spec — terse authoring format (prototype 2)

Second-iteration prototype, derived losslessly from `../spec-yaml/` (which is
itself a lossless conversion of `../spec/*.cue`). Round-trip back to the
canonical form is deep-equal. Converter:
`../scripts/convert_spec_to_terse.py`.

This format treats the whole tree as **one namespace considered together** —
file boundaries are organization, not scoping. The loader globs every file,
merges, then resolves.

## Authoring conventions

1. **Single-level maps, no `id:` boilerplate.** A resource is declared as
   `Name: {body}` under its section; the canonical ID
   (`valueObject.Control.GraphicalShellProjection`) is derived from
   section + context header + name. Max depth to any resource: two levels.
2. **Suffix references.** Any reference may be the shortest dot-suffix of a
   canonical ID that resolves uniquely: `AppState`, `Kernel.PatchId`,
   `validation.soundfont_preset_selection`. 3,176 of 3,196 references in this
   spec resolve as bare names.
3. **Field-typed resolution.** Fields with a known target kind (`goals:`,
   `capabilities:`, `requirements:`, `actors:`, `projectChecks:`, evidence
   `validations:`) resolve within that kind only — so `soundfont_preset_selection`
   in a `capabilities:` list is unambiguous even though a goal and a
   validation share the name. Untyped fields (`resources:`, `uses:`,
   `implements:`, `targets:`, `attachedTo:`) resolve against all IDs.
4. **`contributesTo` is a map** of capability-ref → contribution sentence.
5. **`defaults:` block** (in `proof/validations.yaml`) supplies
   `workingDirectory`/`limits` for every project validation unless overridden —
   this replaces the single CUE pattern-constraint the old spec used.
6. **Union types are lists.** A list value in `state:` or `from:` means a
   union of variants (one variant per line, clean per-variant diffs); a string
   value is any other type expression (`u32`, `Vec<String>`,
   `Option<AudioCommand>`). Variants with payloads stay strings inside the
   list (`Effect(EffectSlotId, ParameterId)`). The pipe syntax in the CUE
   source was never parsed by anything — it was prose mirroring Rust.

## Loader obligations (fail-closed, replacing CUE unification)

- Duplicate map keys → error (YAML silently drops them; the loader must use a
  duplicate-detecting parser).
- Ambiguous suffix reference → error listing candidates (forces qualification,
  like a Python import collision).
- Unresolved reference in a typed field → error. (The canonical converter
  already caught a real case: assets `implements` validations while adapters
  `implements` ports — a polymorphism the CUE never checked.)
- Everything else (shape checking, limits bounds, applicability) — pydantic
  models, same diagnostic vocabulary as the acceptance inventory.

## Measurements against this spec (413 resources, 112 validations)

- References shortened: 3,176 (20 kept fully qualified).
- Bytes: 593 KB → 548 KB overall; reference-heavy files improve most
  (witnesses −15%). Prose (descriptions, invariants, contributions) dominates
  the remainder — that is spec content, not format overhead.
- The original CUE used **no** templating features (zero comprehensions,
  `let`, or definitions) except one `[string]:` defaults pattern — covered by
  the `defaults:` block above.
