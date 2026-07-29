# Spec Kitty Mission Workflow

Use this workflow for local autonomous missions that start from a normal
repository checkout and finish with a pull request to the mission's target
branch.

## Phase 1: Specify

Create the mission spec from the intake prompt:

```bash
/spec-kitty.specify @start-here.md
```

Confirm the mission slug, target branch, and requirement scope before planning.
When the project declares a crest-spec, the spec references its canonical
capabilities and requirements — it never restates them.

## Phase 2: Crest-Spec

Author the crest-spec — the bedrock declaration the rest of the mission
derives from:

```bash
/spec-kitty.crest-spec
```

Declare `crest_spec_impact` in `meta.json` (`structural` | `predeclared` |
`none`). Structural missions edit `.kittify/crest-spec/` here — resources,
assets, and proof — and validate with `spec-kitty crest-spec doctor` until the
model closes. Projects without a crest-spec skip this phase. The plan gate
(`CREST_SPEC_UNDERIVED`) refuses to advance a structural mission whose
crest-spec is untouched.

## Phase 3: Plan

Generate the plan from the approved spec and the authored crest-spec:

```bash
/spec-kitty.plan @start-here.md
```

Keep branch intent explicit. If the mission should land somewhere other than
`main`, resolve that before tasks are generated. When a crest-spec exists,
`plan.md` records the `## Crest-Spec Derivation` section, and `data-model.md`
/ `contracts/` are forbidden — the plan points at canonical resources.

## Phase 4: Tasks

Generate and finalize tasks:

```bash
/spec-kitty.tasks @start-here.md
spec-kitty agent mission finalize-tasks --mission <mission-slug>
```

Review lane assignments and owned files before implementation begins. When a
crest-spec exists, work packages derive from its `assets[]`, and every
`owned_files` entry must trace to a declared asset's file pattern — the
implement gate refuses undeclared work (`crest_spec_underived`).

## Phase 5: Implement and Review

Run the implement-review loop until every WP is approved:

```bash
/spec-kitty-implement-review
```

Each implementer edits only the execution workspace printed by
`spec-kitty agent action implement`.

## Phase 6: Accept

Run acceptance after the final WP is approved:

```bash
/spec-kitty.accept
```

Acceptance checks mission readiness. When the project declares a
crest-spec (`.kittify/crest-spec`), accept also runs deterministic
acceptance — every declared project check and applicable attached validation —
and records the versioned report to `<mission>/deterministic-acceptance.json`,
and it enforces the derivation direction: `plan.md` must carry the
`## Crest-Spec Derivation` section, behavior added without declared proof
blocks (`crest_spec_unproven`), and duplicate planning artifacts block
(`crest_spec_duplicate_artifacts`).
Both layers must pass: the deterministic gates and the adversarial semantic
review embedded in the accept prompt. Accept is the only step that executes
declared validations; archive later consumes the recorded verdict (guard AM-6)
and never re-runs it. Merge still performs its own pre-flight validation.

## Phase 7: Merge Preview

Preview the merge before mutating the target branch:

```bash
spec-kitty merge --mission <mission-slug> --dry-run
```

Resolve dirty worktrees, missing worktrees, and dependency ordering issues
before continuing.

## Phase 8: Merge or Open a Focused PR

If the target branch is synchronized with its tracking branch, merge normally:

```bash
spec-kitty merge --mission <mission-slug> --push
```

If `spec-kitty merge` stops with this diagnostic, use the focused-PR path
instead of trying to make local `main` publishable:

```text
Error: Target branch is not synchronized with its tracking branch.
  diagnostic_code: TARGET_BRANCH_NOT_SYNCHRONIZED
  branch_or_work_package: main
  violated_invariant: local_target_branch_must_match_tracking_branch
```

Autonomous local runs often leave `main` ahead of or diverged from
`origin/main` because planning, status, review, and orchestration commits are
created during the run. Do not reset, rebase, force-push, or push local `main`
as remediation for this diagnostic.

When the mission branch already contains the approved lane merge, open the PR
directly from the mission branch:

```bash
git push -u origin kitty/mission-<mission-slug>
gh pr create --base main --head kitty/mission-<mission-slug> --fill
```

If you want a dedicated PR branch, create it from the mission branch and open
the PR from there:

```bash
git switch -c kitty/pr/<mission-slug>-to-main kitty/mission-<mission-slug>
git push -u origin kitty/pr/<mission-slug>-to-main
gh pr create --base main --head kitty/pr/<mission-slug>-to-main --fill
```

Prefer a squash merge for autonomous runs that accumulated many orchestration
commits:

```bash
gh pr merge --squash --delete-branch
```

## Phase 9: Mission Review

After the PR lands, run mission review from a checkout containing the landed
changes:

```bash
spec-kitty agent mission review --mission <mission-slug>
```

Use the review to confirm spec-to-code fidelity and requirement coverage.

## Phase 10: Retrospective

Verify or create the retrospective, then inspect synthesis proposals:

```bash
spec-kitty retrospect create --mission <mission-slug>
spec-kitty agent retrospect synthesize --mission <mission-slug>
```

Apply only the proposals you intend to preserve:

```bash
spec-kitty agent retrospect synthesize --mission <mission-slug> --apply <proposal-id>
```
