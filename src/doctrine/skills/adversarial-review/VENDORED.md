# Vendored Skill — Provenance

`adversarial-review` is vendored into the Spec Kitty doctrine layer from an
external skill repository. It is **not** a Spec Kitty operating skill (it does
not teach anyone how to use Spec Kitty); it is a code-quality review pipeline
that Spec Kitty doctrine *invokes* at defined point-cuts.

| Field | Value |
|---|---|
| Upstream | `https://github.com/crestenstclair/skills.git` |
| Upstream path | `adversarial-review/` |
| Vendored at commit | `c30082ac6aeda4df956d29030d6285dd14ef8cb8` |
| Vendored on | 2026-08-05 |
| Layout | Preserved byte-for-byte (`SKILL.md`, `agents/`, `references/`) |

## Why the layout is preserved

`SKILL.md` cross-links its role files as `agents/<role>.md` and its catalogs as
`references/<catalog>.md`. Renaming the directories or the skill itself breaks
those links in 16 places and severs the upstream provenance trail. The skill
therefore keeps its upstream name rather than adopting the `spk-<family>-*`
convention documented in [`../README.md`](../README.md).

## Who invokes it

| Caller | Point-cut |
|---|---|
| [`spec-kitty-mission-review`](../spec-kitty-mission-review/SKILL.md) | Step 8.75 — post-merge adversarial code-smell pass over the mission diff |

## Updating

Re-copy from upstream wholesale; do not hand-patch individual files here. Local
edits are drift and will be lost on the next sync:

```bash
cp -R <upstream>/adversarial-review/. src/doctrine/skills/adversarial-review/
```

Then update the commit hash above and re-run
`pytest tests/architectural/test_no_legacy_terminology.py tests/specify_cli/skills/ -q`.

## Deployment note

The `agents/` subdirectory is installed by `SkillRegistry` alongside
`references/`, `scripts/`, and `assets/` (see
`src/specify_cli/skills/registry.py`). Without that collection the seven hunter
and skeptic role files would be present in the repository but absent from every
deployed agent surface, and the pipeline would silently degrade to a
single-reviewer pass.
