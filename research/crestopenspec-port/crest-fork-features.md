# CrestOpenSpec: Fork Additions vs Upstream OpenSpec

This document enumerates and documents everything this fork adds on top of
[Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) (merge-base
`19d4171`). It is the reference for porting this work to another spec-driven
development framework.

**Total delta:** ~14,200 insertions / ~2,100 deletions across 203 files.

| # | Feature | Source size | Test size |
|---|---------|-------------|-----------|
| 1 | CUE architecture integration | ~530 TS + 78 Go + build/schema glue | ~315 lines |
| 2 | Adversarial acceptance gates (deterministic layer) | ~2,100 lines | ~1,700 lines |
| 3 | Runtime lifecycle acceptance | ~1,750 lines | ~700 lines |
| 4 | Skill/workflow template rework (shared execution-acceptance contract) | ~150 net new (+ ~1,200 deleted ceremony) | ~370 lines |
| 5 | Docs, specs, and implementation prompts | ~1,800 lines | — |

Feature commits: `71bc752` (adversarial acceptance gates), `2a5554c` (move
acceptance to execute completion), `7ef8060` (runtime lifecycle gates),
`59e67c7` (CUE planning summaries), `43d4205` (CUE bridge + context injection).

---

## 1. CUE Architecture Integration

**What it does.** A project that keeps a CUE-based architecture spec in a
top-level `spec/` directory gets that architecture evaluated and injected into
every agent-facing context surface automatically. There is no new command; it
piggybacks on existing ones:

- `openspec context --json` gains an `architecture` key:
  `{kind: "cue", root, files[], interpretation, project, relationships[]}`.
- `openspec instructions <artifact> --change X --json` (and the `apply` path)
  gain a `context` field containing the rendered architecture block and a
  `contextFiles.cue` array listing the concrete `.cue` sources, so planning
  agents know what to reconcile/edit.
- The built-in `spec-driven` schema gains a required **`summary`** planning
  artifact (flow becomes `proposal → specs → design → tasks → summary`;
  `apply.requires: [tasks, summary]`). The summary instruction forces CUE
  reconciliation before planning is considered complete.

**How it works.**

- `cuebridge/` — a tiny Go binary (`crest-cue-bridge <spec-dir>`) that links
  `cuelang.org/go v0.16.1`, evaluates the CUE package, looks up the `project`
  value, and prints concrete JSON to stdout. Exit 1 on eval failure, 2 on
  usage. The CUE CLI is **not** required at runtime; Go is required at build
  time (`build.js` runs `go build` before `tsc`).
- `src/core/cue-architecture.ts` (452 lines) — TS side:
  `loadCueArchitecture(projectRoot)` checks for `<root>/spec`, globs `*.cue`,
  spawns the bridge (override path via `CREST_CUE_BRIDGE_BIN`), parses JSON,
  and builds a **relationship index** from a canonical resource-ID scheme
  (`context.<C>`, `aggregate.<C>.<N>`, `port.<C>.<N>`, `goal.*`,
  `capability.*`, `validation.*`, …) with ~35 relation verbs (`contains`,
  `implements`, `supports_goal`, `proven_by`, `completion_requires`, …),
  deterministically sorted. Returns `undefined` (not an error) when no CUE
  spec exists.
- `CUE_INTERPRETATION_CONTRACT` — a ~48-line prose contract shipped verbatim
  to agents, describing the intent model (mission, goals, capabilities,
  requirements, evidence, `completion.requiredGoals`,
  `completion.projectChecks`), the architecture model (DDD: contexts,
  aggregates, ports, adapters, layers, contextMap), and the proof model
  (assets, validations, witnesses).

**Integration points:** `src/core/artifact-graph/instruction-loader.ts`,
`src/commands/workflow/instructions.ts`, `src/commands/context.ts`, and the
acceptance service (the loader IS acceptance gate #1).

**Portability note:** the acceptance system consumes only a plain
`{project: JsonObject}` — the CUE evaluation is behind one injectable
`cueLoader` dependency, so a different declaration format can be substituted
at a single seam.

**Known gap:** the compiled bridge binary ships in the npm tarball, making the
published artifact platform-specific (no per-platform build matrix).

---

## 2. Adversarial Acceptance Gates (deterministic layer)

**What it does.** A new top-level command:

```
openspec acceptance [change-name] [--project|--release] [--json] [--store <id>]
```

It runs a deterministic, language-agnostic acceptance pipeline and exits 0 iff
everything passes. It is the machine-checkable half of a two-layer acceptance
story (the other half is the agent-run adversarial semantic review, feature 4).
Both must pass before an agent may report execute/apply complete.

**The gates, in order (fail-closed at every step):**

1. **Architecture gate** — evaluate the CUE architecture in memory. Eval
   failure → fail. No CUE spec → `not_applicable` (passes, gate disarmed).
2. **Inventory resolution** — resolve every declared validation from the
   evaluated `project` value. Applicability trigger: `completion.projectChecks`
   is present (even `[]`) OR any validation carries a `proof` field. Missing,
   duplicate, ambiguous, or malformed declarations fail closed **before
   anything is executed**.
3. **Strict OpenSpec validation** — stricter than `openspec validate --strict`:
   for a change it also builds the *post-archive merged specs in memory* and
   validates the future spec content before any write.
4. **Validation execution** — run each resolved check sequentially.

**Declaration model (in the CUE `project` value):**

- Project-scope checks: `project.validations` entries with `scope: "project"`,
  referenced by ID from `completion.projectChecks` (exactly-one resolution).
- Attached checks: nested `validations` under resources, relationships,
  capabilities, invariants, witnesses; require `scope: "attached"` and explicit
  `applicability` (`{mode: "always"}` or `{mode: "changes", changes: [...]}`).
- Every declaration: `id`, `command` (argv array, **never** a shell string),
  `workingDirectory` (must canonicalize inside project root), `limits`
  (`timeoutMs` capped at 30 min, stream capture capped at 16 MiB), optional
  `assertions[]`, `proofRole`, `proof`.

**Assertions:** `exit-code`, `stdout-contains`, `stdout-not-contains`,
`stderr-contains`, `stderr-not-contains` — every declared assertion is
evaluated even after process failure; anything malformed fails closed.

**Test evidence:** a `{type: "test-suite"}` proof requires structured evidence
via a provider (built-in: `structured-json-v1`, one JSON doc on
stdout/stderr). The core — not the provider — enforces `executed >=
minimumExecuted >= 1`, zero failures, count consistency, and deep-equal
selector match. A green process with `executed: 0` **fails acceptance**
(`test_evidence_minimum_not_met`).

**Report:** one versioned JSON document (`version: "2.0"`) with per-gate
status, per-check process records (argv, cwd, limits, duration, termination
kind, bounded output), and a permanent
`semanticReview: {status: "not_evaluated"}` marker stating that deterministic
acceptance does not establish semantic conformance. Environment variables are
never serialized. ~70 stable diagnostic codes form the portable contract.

**Explicit-execution boundary:** `list`, `context`, `status`, `instructions`,
planning, static `validate`, and `archive` **never** run declared commands.
Only `openspec acceptance`, end-of-execute apply, and explicit verify do.
Nothing is persisted between runs (no DB/cache/daemon/ledger).

**Extension seams (all DI-injectable):** `cueLoader`, `commandRunner`,
`assertionRegistry`, `testEvidenceRegistry`, `runtimeSessionRegistry`,
`strictValidation`. Adding a test runner or runtime mechanism requires no
orchestration changes.

**Key modules:** `src/core/acceptance/{types,validation-inventory,service,
process-runner,assertions,test-evidence,openspec-validation,render}.ts`,
`src/commands/acceptance.ts`.

---

## 3. Runtime Lifecycle Acceptance

**What it does.** Closes the gap where tests, dry runs, and success markers
all agree while the real user-facing process never terminates (or leaks
children, or a concurrent input races the production reducer). Adds a
first-class `runtime-session` proof type that launches the project's actual
entry point, supervises the full process tree, and verifies lifecycle
semantics — not just output strings.

**Declaration (`proof: {type: "runtime-session", provider:
"process-lifecycle-v1", ...}`):** `entryPoint`, `boundary`
(`external-process` | `production-composition` | `native-ui` | …),
`environment`, `lifecycle` (`bounded` | `interactive-persistent` |
`service-persistent` | `background-owned`), `stdioMode` (`pipe` | `pty`), six
separate timeout budgets (`startup`, `progressSilence`, `completion`,
`completionToExitGrace`, `teardownGrace`, `hard`), ordered `progress[]` and
`completion[]` markers, `requireExitCode`, `requireNoDescendants`,
`requiredCapabilities[]`, `interactions[]`, and mandatory `teardown` for
persistent lifecycles.

**Semantics:**

- **bounded:** `start → declared progress → exact completion markers in
  declared order → grace window → normal exit with required code → no owned
  process or descendant remains`. Emitting the success marker does **not**
  finish the proof — the signature diagnostic is
  `success_reported_but_process_resident`.
- **persistent:** completion markers mean readiness; a declared teardown
  (`owned-process-signal-v1`) must cleanly stop the session; readiness and
  teardown are reported separately.
- **Process ownership** (`process-tree.ts`): enumerates via `ps`/CIM, signals
  the process *group* it spawned, TERM→KILL escalation with every action
  recorded. Never selects processes by executable name — an unrelated
  same-named process provably survives cleanup.
- **PTY fidelity:** `stdioMode: "pty"` wraps the entry point in
  `/usr/bin/script` (POSIX only); if PTY is unavailable the check fails as a
  proof gap — never silently downgraded to pipe.
- **Host capabilities:** default host provides only
  `process`, `stdio:pipe`, `platform:<os>`. Any other required capability
  (desktop session, audio device, …) → `BLOCKING_REQUIRED_PROOF_GAP`. No
  implicit waiver.
- **Controlled interactions** (`process-json-v1`): a project-owned driver is
  invoked inside a declared `[opensAfter, closesBefore)` marker window with a
  bounded JSON request; evidence must match session/action IDs, prove the seam
  was reached, and pass every named assertion. Guards against races like "a
  keypress during a pending autonomous checkpoint goes through the production
  reducer."

**Key modules:** `src/core/acceptance/{runtime-session,runtime-providers,
process-tree,runtime-process-launcher}.ts`; spec at
`openspec/specs/runtime-lifecycle-acceptance/spec.md` (7 requirements, 21
scenarios); ~20 named fixture scenarios in
`test/fixtures/acceptance/create-project.mjs`.

---

## 4. Skill/Workflow Template Rework

**What it does.** Restructures *when* acceptance happens in the agent
workflow and gives apply + verify one shared, verbatim contract:

- **`EXECUTION_ACCEPTANCE_CONTRACT`** (~95 lines of markdown in
  `src/core/templates/workflows/acceptance-review.ts`), interpolated verbatim
  into both the apply and verify skill/command templates. Five phases:
  1. Establish authority/applicability with an obligation ledger
     (`CURRENT_SLICE` / `EVERGREEN_INVARIANT` / `DEFERRED_SCOPE` /
     `UNAUTHORIZED_EARLY_SCOPE`).
  2. Evidence-complete findings (`BLOCKING_CURRENT_VIOLATION`,
     `BLOCKING_EVERGREEN_VIOLATION`, `BLOCKING_REQUIRED_PROOF_GAP`,
     `DEFERRED_NOT_APPLICABLE`, `INFORMATIONAL_FUTURE_RISK`; 7 mandatory
     fields per blocker).
  3. Architecture-conformance matrix + **9 drift guards**
     (composition-root-and-dependency-direction, negotiation-before-
     preparation, asynchronous-runtime-failure, end-to-end-failure-
     observability, validation-declaration-integrity, runtime-boundary-
     completeness, terminal-success-coherence, critical-interleaving-
     completeness, declaration-honesty).
  4. Run deterministic acceptance (`openspec acceptance <change> --json`).
  5. Decide and report.
- **Apply** runs the full contract at end-of-execute (including when it starts
  in `all_done` state). Verify is a standalone invocation of the same
  contract. **Archive and bulk-archive were stripped** of ~830 lines of
  verification ceremony: they consume reviewed completion state + user
  approval and explicitly must not rerun acceptance or start runtime sessions.
- **Planning guidance** (`planning-guidance.ts`): CUE reconciliation guidance
  and dense-summary guidance injected into propose/continue/ff/update/onboard
  templates; explore reads `openspec context --json` architecture data.
- **Parity enforcement:** tests assert the contract appears verbatim in
  apply+verify (and NOT in archive), all 9 guard IDs are present, and a
  language-neutral fixture matrix
  (`test/fixtures/adversarial-review/architecture-drift-cases.json`,
  `dialect: neutral-trace-v1`) provides blocking/conforming trace pairs per
  guard.

---

## 5. Docs, Specs, and Prompts

- `docs/acceptance.md` (293 lines) — the full user-facing guide to both
  layers, with worked CUE examples (including the canonical "green process,
  zero tests executed, acceptance fails" example).
- OpenSpec specs (dogfooded): `runtime-lifecycle-acceptance` (synced),
  `opsx-verify-skill` / `opsx-archive-skill` deltas, plus the **still-active,
  unsynced** `add-adversarial-acceptance-gates` change (11-requirement
  `acceptance-gates` spec, 53/53 tasks complete — needs archiving).
- `openspec/changes/archive/generic/ADVERSARIAL_ACCEPTANCE_GATES_PROMPT.md`
  (370 lines) and `RUNTIME_LIFECYCLE_EXECUTION_GATES_PROMPT.md` (304 lines) —
  self-contained, framework-agnostic implementation briefs. These are the
  primary porting artifacts: they specify the systems without OpenSpec
  specifics. Caveat: the first prompt's archive-enforcement section was
  superseded by `2a5554c` (acceptance moved from archive-time to
  end-of-execute).

## Incidental changes (not features)

- Codex tool paths migrated `.codex` → `.agents` (with legacy detection), in
  `src/core/config.ts` / `src/core/migration.ts` (commit `43d4205`).
- `tmp/refactoring-review.md` — committed scratch notes; candidate for
  removal.
- `openspec/changes/track-spec-progress/` — unimplemented proposal for a
  read-only `openspec progress` command; origin of the "ordinary reads never
  execute" trust boundary.
