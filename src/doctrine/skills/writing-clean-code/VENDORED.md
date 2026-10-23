# Vendored Skill — Provenance

`writing-clean-code` is vendored into the Spec Kitty doctrine layer from an
external skill repository. It is **not** a Spec Kitty operating skill; it is the
structural-design discipline (SOLID, dependency injection, naming, pattern
selection) that Spec Kitty doctrine *invokes* when a phase makes architecture
decisions.

| Field | Value |
|---|---|
| Upstream | `https://github.com/crestenstclair/skills.git` |
| Upstream path | `writing-clean-code/` |
| Vendored at commit | `c30082ac6aeda4df956d29030d6285dd14ef8cb8` |
| Vendored on | 2026-08-05 |
| Layout | Preserved byte-for-byte (`SKILL.md`, `references/`) |

## Why the layout is preserved

`SKILL.md` cross-links its four references as `references/<topic>.md`, and
[`../adversarial-review/`](../adversarial-review/VENDORED.md) shares the same
SOLID vocabulary. Renaming either skill splits that vocabulary in two and severs
the upstream provenance trail. The skill therefore keeps its upstream name
rather than adopting the `spk-<family>-*` convention documented in
[`../README.md`](../README.md).

## Who invokes it

| Caller | Point-cut |
|---|---|
| [`spk-mission-crest-spec`](../spk-mission-crest-spec/SKILL.md) | Crest-spec authoring — bounded contexts, aggregates, ports, adapters, and `assets[]` are shaped against SOLID and the pattern-selection rules |
| `src/doctrine/missions/mission-steps/software-dev/crest-spec/` | The `/spec-kitty.crest-spec` step prompt and guidelines |

The crest-spec is the bedrock DDD declaration that plan, tasks, and code derive
from. Structural mistakes made there are not local: they propagate into every
downstream work package, so the design discipline belongs at authoring time, not
at review time.

## Updating

Re-copy from upstream wholesale; do not hand-patch individual files here. Local
edits are drift and will be lost on the next sync:

```bash
cp -R <upstream>/writing-clean-code/. src/doctrine/skills/writing-clean-code/
```

Then update the commit hash above and re-run
`pytest tests/architectural/test_no_legacy_terminology.py tests/specify_cli/skills/ -q`.
