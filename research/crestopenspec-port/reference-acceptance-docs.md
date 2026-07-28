# Acceptance Gates

OpenSpec acceptance has two deliberately separate layers:

1. **Deterministic acceptance** is core CLI code. It evaluates CUE, strictly validates OpenSpec material and future merged specs, executes every applicable declared validation, checks assertions and test evidence, supervises declared runtime sessions through teardown, and returns an enforceable exit status.
2. **Adversarial semantic review** is the shared agent workflow used at the end of `/opsx:apply` and by explicit `/opsx:verify`. It traces architecture through production composition and behavior. CLI success never claims that this semantic review passed.

Both layers must pass before an agent reports the execute/apply phase complete. Archive happens later, after user review and approval, without repeating acceptance.

## Running deterministic acceptance

```bash
# One change
openspec acceptance add-dark-mode
openspec acceptance add-dark-mode --json

# Every active change and canonical spec
openspec acceptance --project --json
openspec acceptance --release --json   # alias for --project

# A registered store
openspec acceptance add-dark-mode --store team-plans --json
```

A change name and `--project`/`--release` are mutually exclusive. JSON mode prints exactly one versioned report. Any mandatory failure sets a nonzero exit status. The report always states that semantic conformance was not evaluated by the deterministic command.

Normal reads and archive remain non-executing with respect to repository-declared validations: `list`, `context`, `status`, `instructions`, planning, ordinary progress reads, static `validate`, and `archive` do not run them. Direct `acceptance`, end-of-execute apply, and explicit verify are the command-running workflows.

## When the gate applies

The CLI evaluates the complete top-level `spec/*.cue` package. Executable acceptance is declared when the concrete `project` contains either:

- `completion.projectChecks`, including an explicitly empty array; or
- an attached validation with a `proof` field (`test-suite` or `runtime-session`).

No CUE package, or valid CUE containing neither declaration form, reports deterministic execution as `not_applicable`. CUE evaluation failure and malformed declared contracts fail closed.

## Language-neutral declaration schema

This example shows a project check and an independently binding resource test:

```cue
package architecture

project: {
  completion: projectChecks: ["validation.all"]

  validations: all: {
    id:               "validation.all"
    scope:            "project"
    command:          ["./tools/neutral-check", "--all"]
    workingDirectory: "."
    limits: {
      timeoutMs:  60000
      stdoutBytes: 262144
      stderrBytes: 262144
    }
    assertions: [{type: "exit-code", equals: 0}]
    proof: {
      type:            "test-suite"
      provider:        "structured-json-v1"
      minimumExecuted: 1
      selector: {kind: "suite", value: "all"}
      options: stream: "stdout"
    }
  }

  resources: storage: validations: targeted: {
    id:               "validation.storage"
    scope:            "attached"
    applicability: {mode: "changes", changes: ["add-dark-mode"]}
    command:          ["./tools/neutral-check", "--resource", "storage"]
    workingDirectory: "."
    limits: {
      timeoutMs:  60000
      stdoutBytes: 262144
      stderrBytes: 262144
    }
    assertions: [{type: "exit-code", equals: 0}]
    proof: {
      type:            "test-suite"
      provider:        "structured-json-v1"
      minimumExecuted: 1
      selector: {kind: "resource", value: "storage"}
      options: stream: "stdout"
    }
  }
}
```

Top-level `project.validations` supply project-check declarations. A project check must resolve by ID to exactly one top-level declaration with `scope: "project"`.

The inventory also walks every nested `validations` attachment, including resources, relationships, capabilities, invariants, witnesses, and acceptance assets. An attached test or runtime declaration has `scope: "attached"`; its exact evaluated parent path is its owner and its exact field path is its declaration location. Applicability is explicit:

- `{mode: "always"}` applies in every scope.
- `{mode: "changes", changes: ["change-id"]}` applies to matching change runs and is conservatively included in project/release runs.

Once the contract is governed, missing IDs, duplicate identities, ambiguous owners, orphaned string references, malformed declarations, or missing/malformed attached-test applicability block all execution. Core does not infer roadmap intent from prose.

Every applicable declaration is a separate gate. A broad project suite cannot cover an attached target or runtime session by implication. Identical commands currently execute independently, which keeps their assertions and evidence records isolated.

## Process and assertion boundary

`command` is a non-empty argument vector, not a shell string. Core starts it with shell interpolation disabled and records the exact arguments. `workingDirectory` must exist and resolve, through aliases and symlinks, inside the canonical project root.

Every declaration supplies positive limits. Core caps them at 30 minutes and 16 MiB per output stream, captures stdout and stderr independently, and terminates on timeout or overflow. Reports preserve bounded output, duration, exit code, signal, timeout, overflow, and spawn errors, but never serialize environment keys or values.

Built-in generic assertions are `exit-code`, `stdout-contains`, `stdout-not-contains`, `stderr-contains`, and `stderr-not-contains`. Every declared assertion is evaluated even after process failure. Unsupported, malformed, throwing, or false assertions fail closed.

## Runtime-session proof

Use `runtime-session` only for a claim about an external lifecycle or production composition. Proof roles remain explicit: `target-reachability`, `static-validation`, `in-process-behavior`, `external-process-lifecycle`, and `production-composition-runtime`. An ordinary validation may declare `proofRole: "target-reachability"` or `proofRole: "static-validation"`; the normalized role is reported. A test-suite proof may optionally declare `in-process-behavior` (and otherwise normalizes to it); it is rejected if presented as external lifecycle. A runtime-session proof must declare one of the two runtime roles. A validation claiming either runtime role without a runtime-session proof also fails. A dry run, `--help`, target listing, fake, or construction test cannot be relabeled as runtime evidence.

```cue
project: resources: liveDemo: validations: lifecycle: {
  id:                 "validation.live-demo"
  scope:              "attached"
  applicability:      {mode: "changes", changes: ["add-live-demo"]}
  command:            ["./tools/live-demo", "--autonomous"]
  workingDirectory:   "."
  limits: {
    timeoutMs:  190000
    stdoutBytes: 262144
    stderrBytes: 262144
  }
  assertions: [{type: "exit-code", equals: 0}]
  proof: {
    type:        "runtime-session"
    provider:    "process-lifecycle-v1"
    role:        "external-process-lifecycle"
    entryPoint:  "./tools/live-demo --autonomous"
    boundary:    "external-process"
    environment: "physical"
    lifecycle:   "bounded"

    successCondition: "state and summary records occur once in order"
    terminationOwner: "process"
    resources: [
      {id: "application", type: "process", disposition: "release", owner: "live-demo"},
      {id: "window", type: "native-window", disposition: "release", owner: "live-demo"},
      {id: "stream", type: "device-stream", disposition: "release", owner: "live-demo"},
    ]

    stdioMode: "pty"
    timeouts: {
      startupTimeoutMs:          30000
      progressSilenceMs:         30000
      completionTimeoutMs:      180000
      completionToExitGraceMs:    5000
      teardownGraceMs:             5000
      hardTimeoutMs:             185000
    }
    progress: [
      {id: "checkpoint", stream: "stdout", contains: "CHECKPOINT", minimumCount: 1},
    ]
    completion: [
      {id: "state", stream: "stdout", contains: "FINAL_STATE", exactCount: 1},
      {id: "summary", stream: "stdout", contains: "FINAL_SUMMARY", exactCount: 1},
    ]
    requireExitCode:      0
    requireNoDescendants: true
    requiredCapabilities: ["desktop-session", "physical-output-device"]
    interactions: []
  }
}
```

The declaration names the production entry point, boundary, environment fidelity, lifecycle, authoritative success condition, termination owner, and every resource disposition. Marker strings are ordinary declared data; core contains no application-specific names.

For `bounded`, terminal success starts the short completion-to-exit grace. It does not finish acceptance. The required sequence is start, declared progress, exact completion markers in order, normal parent exit with the required code, and no owned process or descendant remaining. Stable failures distinguish startup, progress silence, completion, completion-to-exit, hard-limit, marker, exit, interaction, teardown, and cleanup stages. In particular, a process that emits every final record and stays alive fails as `success_reported_but_process_resident` and is cleaned up.

`interactive-persistent`, `service-persistent`, and `background-owned` use their completion markers as readiness. They must declare controller teardown:

```cue
teardown: {
  provider: "owned-process-signal-v1"
  request: signal: "SIGTERM"
}
```

The service must handle that request and exit with the declared code inside `teardownGraceMs`. Readiness is reported separately from teardown and never masquerades as bounded completion.

The process provider starts the target without shell interpolation. It creates a uniquely owned group where the platform permits, observes descendants while the session runs, records parent/group/descendant identities, sends bounded TERM/KILL stages only to that owned tree, and verifies it is gone. Executable names, globs, and unrelated PIDs are never cleanup selectors.

`stdioMode: "pipe"` uses independent bounded stdout/stderr pipes. `stdioMode: "pty"` is explicit and never silently downgraded; terminal output is observed on stdout. The built-in platform adapter uses the host PTY facility when available. An applicable PTY proof on a host without that adapter returns `BLOCKING_REQUIRED_PROOF_GAP`.

## Controlled runtime interactions

Core does not know how to press a native key, invoke a device callback, or speak a project protocol. Each material action names an interaction provider and two declared milestones:

```cue
interactions: [{
  id:           "mapped-input"
  provider:     "process-json-v1"
  opensAfter:   "checkpoint-dispatched"
  closesBefore: "generation-observed"
  request: {
    command: ["./tools/drive-live-input", "--json"]
    timeoutMs: 5000
    payload: {action: "mapped-input"}
  }
  requiredAssertions: ["isolation-preserved", "autonomous-completion"]
}]
```

`process-json-v1` starts the project-owned driver argument vector directly in the runtime's canonical working directory and sends one bounded JSON request on stdin. The driver returns one JSON document containing the same `sessionId` and `actionId`, `attempted`, `reachedSeam`, a session-relative `deliveredAtMs`, named assertion results, and JSON-safe details. Core verifies that delivery falls in `[opening, closing)`, the evidence belongs to this session, the seam was reached, and every required assertion appears exactly once and passes. Unsupported providers, another session's evidence, pre-start/post-completion delivery, missing seam delivery, and negative-only incomplete assertions fail closed.

## Host capability fidelity

`requiredCapabilities` is explicit. Core provides only capabilities it can actually exercise (for example process/pipe and an available PTY adapter); it never guesses a desktop, device, native service, or protocol capability from the operating system or command name. If an applicable physical/native or interaction proof requires an unavailable capability, the result is `BLOCKING_REQUIRED_PROOF_GAP`, not pass or skip. OpenSpec currently provides no implicit waiver. Any future waiver must be user-approved, scoped, and reported as a waiver rather than executed evidence.

## Trustworthy test evidence

A validation is treated as a test suite only when it declares `proof.type: "test-suite"` and explicitly names a provider. Non-test checks do not need test counts.

The built-in `structured-json-v1` provider reads one complete JSON document from the explicitly selected stdout or stderr stream:

```json
{
  "selector": { "kind": "resource", "value": "storage" },
  "discovered": 3,
  "executed": 2,
  "passed": 2,
  "failed": 0,
  "skipped": 1,
  "source": { "report": "project-owned adapter output" }
}
```

Core, not the provider, enforces nonnegative integer counts, count consistency, no failed tests, and `executed >= minimumExecuted >= 1`. Discovered, filtered, skipped, ignored, compiled, or merely enumerated tests do not count as executed.

The evidence selector must deep-equal the declaration's opaque selector. A count from a broad or related invocation cannot satisfy a targeted declaration. This successful process therefore still fails acceptance:

```json
{
  "id": "validation.storage",
  "declaration": {
    "kind": "attached_test",
    "owner": "project.resources.storage",
    "location": "project.resources.storage.validations.targeted"
  },
  "processPassed": true,
  "testEvidence": {
    "provider": "structured-json-v1",
    "minimumExecuted": 1,
    "selector": { "kind": "resource", "value": "storage" },
    "status": "failed",
    "evidence": {
      "provider": "structured-json-v1",
      "selector": { "kind": "resource", "value": "storage" },
      "executed": 0,
      "passed": 0,
      "failed": 0,
      "source": { "kind": "process-stream", "stream": "stdout" }
    },
    "diagnostics": [{
      "severity": "error",
      "code": "test_evidence_minimum_not_met",
      "message": "Executed 0 test(s); at least 1 must execute."
    }]
  },
  "passed": false
}
```

Runner-specific parsing belongs in a provider. Adding another test runner requires implementing and registering a `TestEvidenceProvider`; adding another runtime mechanism requires a `RuntimeSessionProvider`; and adding another interaction mechanism requires a `RuntimeInteractionProvider` or the project-owned JSON driver. None changes acceptance orchestration, execute/archive workflow logic, CUE resolution, or archive. No provider is inferred from command names, filenames, frameworks, host OS, or output prose.

## End-of-execute enforcement

When `/opsx:apply` completes its final implementation task, it rebuilds the obligation/architecture ledgers from final evaluated CUE and the final diff, runs final strict validation, performs the semantic review, and runs `openspec acceptance <change-name> --json`. Acceptance validates future merged specs and executes every applicable runtime session. The same happens when apply starts in `all_done` state, so a completed task list or earlier validation pass cannot skip final proof.

If either layer blocks, execute/apply remains incomplete and repairs stay in the active implementation loop. If implementation pauses with tasks remaining, final acceptance does not run. Explicit `/opsx:verify` can rerun the same contract later when the user deliberately requests another review.

`/opsx:archive`, bulk archive, and core `openspec archive` do not rerun acceptance. They summarize completion and spec effects, obtain user approval, and perform the ordinary validation/spec/archive operation. Archive flags retain their documented meanings; archive approval is not represented as new functional evidence.

## Adversarial semantic review

The agent reads evaluated CUE before artifacts and implementation. It classifies each obligation exactly once as `CURRENT_SLICE`, `EVERGREEN_INVARIANT`, `DEFERRED_SCOPE`, or `UNAUTHORIZED_EARLY_SCOPE`. Missing deferred functionality is never a blocker; it is reported as `DEFERRED_NOT_APPLICABLE` or omitted.

Blocking finding classes are `BLOCKING_CURRENT_VIOLATION`, `BLOCKING_EVERGREEN_VIOLATION`, and `BLOCKING_REQUIRED_PROOF_GAP`. Every blocker needs an authority citation, applicability rationale, production evidence, falsifiable contradiction or precise proof gap, the exact controlled proof command and production-seam witness, observed result, severity, and repair direction. If execution cannot complete, the attempted command and remaining proof gap stay explicit and blocking. Keyword suspicion, name matching, a success string, missing future work, or lack of investigation is not proof.

The review builds an architecture-conformance matrix and, where evaluated architecture supplies the premise, traces eight guard families:

- **Composition root and dependency direction:** declared owner, production construction and supply, consuming service, bypasses, layer direction, and a production substitution/mismatch witness.
- **Negotiation before preparation:** discover or negotiate, validate, completely prepare, start, and check later values; cover a supported non-default value and capacity boundaries without silent truncation, padding, or fallback.
- **Asynchronous runtime failure:** startup and post-start error entry points through callbacks, futures, events, workers, and tasks to the declared observation or recovery boundary; use a controlled failure after startup.
- **End-to-end failure observability:** trace typed failure through every production caller and independently prove both forbidden-mutation absence and the required error, status, state, or counter observation.
- **Runtime-boundary completeness:** match every applicable external runtime claim to its exact production entry point, lifecycle, termination/resource ownership, executable witness, and environment fidelity.
- **Terminal-success coherence:** treat markers/readiness as intermediate until declared teardown, parent exit, and owned-resource cleanup are proved.
- **Critical-interleaving completeness:** identify concrete independent producers and inject each material competing action between named milestones through the production seam with session-bound positive assertions.
- **Declaration honesty:** keep reachability, static, in-process, external lifecycle, production composition, synthetic/physical environment, and controlled interaction roles distinct.

Core acceptance contains no AST, framework, method-name, runner-name, or ecosystem heuristic for these semantic questions. A project can make additional analysis deterministic by declaring an executable validation or installing an explicit provider; unsupported inference never becomes a pass.
