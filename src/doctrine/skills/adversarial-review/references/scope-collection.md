# Scope Collection — Building the Review Set

The pipeline is diff-agnostic: every mode below reduces to the same **review set** — a list of files, each optionally narrowed to changed line ranges. Hunters receive the set plus permission to read surrounding code for context.

## Resolution order

When the user did not name a mode explicitly, resolve in this order and say which mode was picked:

1. User pasted a diff or gave a patch file → **Pasted diff**
2. User gave explicit paths → **Files / directory**
3. Not a git repo → **Files / directory** (ask which paths if unclear)
4. PR exists for the current branch → **Pull request**
5. On a branch that is not the default → **Branch diff**
6. Staged changes exist → **Staged**
7. Working tree dirty → **Working tree**
8. Nothing pending → ask: last commit(s), or a path?

## Modes

### Pull request

```bash
pr_number=$(gh pr list --head "$(git branch --show-current)" --json number --jq '.[0].number')
gh pr view "$pr_number" --json title,body,baseRefName   # intent context
gh pr diff "$pr_number"                                  # the diff
```

### Branch diff

```bash
base=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
base=${base:-main}
git diff --name-only "${base}...HEAD"
git diff "${base}...HEAD"
```

Use three-dot (`...`) so only this branch's changes appear, not drift on the base.

### Staged

```bash
git diff --cached --name-only
git diff --cached
```

### Working tree

```bash
git diff HEAD --name-only
git diff HEAD
git ls-files --others --exclude-standard    # untracked files — include whole-file
```

### Commit range

```bash
git diff --name-only <A>..<B>
git diff <A>..<B>
# "last 3 commits": git diff HEAD~3..HEAD
```

### Pasted diff / patch file

Parse the unified diff headers (`+++ b/<path>`, `@@ -a,b +c,d @@`) into files + line ranges. If the files exist locally, hunters read them for context; if not, review the hunk content alone and say so in the report — cross-file smells (Shotgun Surgery, Duplicate Code) will have reduced coverage.

### Files / directory

No git required.

```bash
find <dir> -type f \( -name '*.cs' -o -name '*.ts' ... \) | head -50
```

Whole files are in scope. Skip generated code, vendored dependencies, and lockfiles.

## Edge cases

- **Diff mode, changed lines only:** hunters flag smells *introduced or worsened* by the change; pre-existing problems in touched files go to a "Pre-existing (FYI)" note at most, never counted as findings.
- **Huge sets (>30 files):** review in full only the files with substantive changes; list mechanically-changed files (renames, generated, format-only) as skipped in the report. Never silently truncate.
- **Binary / lock / generated files:** excluded, listed as excluded.
- **Merge commits in a range:** use `git diff` of the range endpoints, not per-commit diffs, to avoid double-counting.
