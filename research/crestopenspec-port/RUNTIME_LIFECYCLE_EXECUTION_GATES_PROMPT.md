# Prompt: Production Runtime Lifecycle and Interaction Gates

Work from the committed `codex/adversarial-acceptance-gates` ref in `~/workspace/CrestOpenSpec`. Create a clean sibling worktree and a new branch such as:

- worktree: `~/workspace/crestopenspec-runtime-lifecycle-acceptance`
- branch: `codex/runtime-lifecycle-acceptance-gates`
- OpenSpec change: `add-runtime-lifecycle-acceptance-gates`

Do not modify `~/workspace/crest-synth`; it is incident evidence only. Do not use legacy crest-spec tooling.

## Objective

Extend CrestOpenSpec's end-of-execute acceptance so an agent cannot report `/opsx:apply` complete merely because in-process tests, dry-run commands, success markers, and the declared specifications agree with one another. When the current slice makes an external runtime, lifecycle, physical-environment, or concurrent-interaction claim, acceptance must require a proof at the matching production boundary.

The new gates must catch both of these classes of escaped defect before execute/apply is reported complete:

1. a process emits its successful completion records but remains alive indefinitely with its window, device, children, or other owned resources still resident; and
2. an input, callback, worker, or other concurrent producer can interleave at a critical point and invalidate or corrupt an otherwise passing autonomous workflow.

Preserve the existing separation between deterministic acceptance and adversarial semantic review. Core code must remain language-, build-system-, UI-toolkit-, and test-runner-agnostic. Project-specific interaction driving belongs behind explicit declarations and provider interfaces.

## Incident this change must prevent

Use the following Crest Synth failure as the regression narrative and as a read-only dogfood case after self-contained fixtures pass:

- `make demo-live` was a user-facing, physical production-path witness.
- It emitted all four successful final records after about 89 seconds, but the `make` process, application process, native window, and audio stream remained resident. A monitored run was still alive and silent after 319 seconds and required user action to end.
- A mapped key pressed while an autonomous checkpoint was pending dispatched through the production semantic-input and reducer path. The accepted edit advanced the application generation and replaced a latest-wins parameter snapshot before audio observed the awaited generation, so the demo failed.
- The deterministic window witness did not inject an action in that dispatch-to-observation interval. Worse, its then-current assertion deliberately required multiple post-completion ticks and no automatic close.
- The declared target validation was `make -n demo-live`, which proved only that the Make target expanded. The deterministic acceptance report executed the fake-window/live-runner tests but did not execute and supervise the real `make demo-live` process.
- The old OpenSpec, CUE, test, and implementation were therefore mutually consistent around the same wrong lifecycle assumption. Passing those mutually reinforcing artifacts was not evidence that the user-facing command completed.

This is not merely a downstream bug. It is a missing end-of-execute proof class in CrestOpenSpec.

## Root cause to encode in the workflow

The current acceptance architecture executes `completion.projectChecks` and applicable attached test-suite proofs. It does not provide a first-class external runtime-session proof, does not distinguish target reachability from behavior, and does not require the semantic reviewer to audit lifecycle and critical interleavings at the production boundary.

Fix that gap without making normal read operations execute project code and without moving acceptance back into archive. End-of-execute `/opsx:apply` and explicit `/opsx:verify` remain the owners of this work. Archive remains a later, non-executing approval and record operation.

## Required end-of-execute semantic guards

Add the following guards to the shared acceptance-review contract used by apply and verify. They must participate in the existing obligation ledger, evidence-complete finding model, generated templates, skills, documentation, and parity tests.

### 1. Runtime-boundary completeness

For every `CURRENT_SLICE` or `EVERGREEN_INVARIANT` claim involving a user-facing command, external process, native UI, device, network service, background worker, daemon, callback-driven runtime, or other owned runtime resource:

1. identify the exact production entry point;
2. classify its intended lifecycle explicitly as bounded, interactive-persistent, service-persistent, or background-owned;
3. identify the authoritative success condition and who owns termination;
4. identify every process, child process, window, stream, worker, task, device, socket, and other resource that must be released or deliberately retained;
5. map the claim to an executable witness at the same boundary; and
6. verify that the witness's environment fidelity matches the claim.

An in-process fake, mock, null device, dry run, command listing, compilation check, or construction-only test cannot satisfy a claim explicitly made about an external process, native window, physical device, production composition, or real service lifecycle. Such tests remain useful lower-level evidence but do not replace the matching runtime proof.

If an applicable runtime claim has no matching declared proof, report `BLOCKING_REQUIRED_PROOF_GAP`. Do not silently infer that a broad suite covered it.

### 2. Terminal-success coherence

Treat a success marker, completed report, ready state, or callback as an intermediate observation unless the declared lifecycle says otherwise.

For a bounded runtime, require this complete sequence:

`start -> observable progress -> success condition exactly as declared -> normal teardown -> parent exit -> no owned descendants or resources remain`

The gate must fail when:

- a success marker appears but the process does not exit within the declared completion-to-exit grace period;
- the parent exits while an owned descendant remains alive;
- a required marker is missing, duplicated, or out of order;
- exit zero occurs before the required success condition;
- teardown requires undeclared user input;
- a timeout kills the process after it claimed success; or
- output becomes silent indefinitely after the final progress/completion event.

A persistent interactive application or service may have a readiness proof, but it must declare persistent lifecycle explicitly, identify a bounded controller-owned teardown protocol, and prove that teardown. It must not masquerade as a bounded completion witness or keep `/opsx:apply` waiting forever.

### 3. Critical-interleaving completeness

For each applicable runtime path, identify independent producers that can act on the same state, transport, resource, snapshot, queue, generation, transaction, or lifecycle. Examples include user input versus automation, callbacks versus control logic, retries versus latest-wins state, workers versus shutdown, and device errors versus success reporting.

For each material race window:

1. name the before/after milestones that bound the window;
2. inject the competing action at that window through the production composition seam;
3. prove the action was actually delivered to the intended seam;
4. assert the contractually correct outcome, including state, projection, publication, log, generation, error, and lifecycle effects as applicable; and
5. prove the autonomous flow still reaches the correct terminal result, or fails with the exact required typed error.

A test that injects the action only before startup or after completion does not cover an in-flight interleaving. A negative assertion such as “no crash” or “no forbidden mutation” is insufficient when the contract also requires a visible error, ignored-input record, retry, cancellation, or successful continuation.

The semantic reviewer must not invent races from keyword searches. A blocking interleaving gap requires an applicable authority, a concrete shared boundary or producer trace, and a precise missing or failing witness.

### 4. Declaration-honesty guard

Separate these proof meanings in declarations and reports:

- target or command reachability;
- static/configuration validation;
- in-process behavioral test;
- external-process lifecycle;
- production-composition runtime;
- synthetic environment;
- physical or native environment;
- controlled interaction/interleaving.

`make -n`, `--help`, command enumeration, and equivalent dry-run operations may prove reachability only. They must never satisfy runtime behavior or lifecycle claims.

When the specification and tests encode a persistent lifecycle for an autonomous command that is also being used as a finite completion witness, report a semantic contradiction and require the lifecycle to be resolved in the authoritative artifacts before acceptance. Self-consistency among prose, mocks, and implementation is not enough when their proof roles conflict.

## First-class deterministic runtime-session proof

Extend the language-neutral acceptance declaration model with an explicit runtime-session proof type. Refine the exact CUE/TypeScript shape during design, but preserve semantics equivalent to this conceptual example:

```cue
proof: {
  type:     "runtime-session"
  provider: "process-lifecycle-v1"

  boundary:    "external-process"
  environment: "physical"
  lifecycle:   "bounded"

  startupTimeoutMs:       30000
  progressSilenceMs:      30000
  completionTimeoutMs:    180000
  completionToExitGraceMs: 5000
  teardownGraceMs:         5000

  progress: [{stream: "stdout", contains: "CHECKPOINT", minimumCount: 1}]
  completion: [
    {stream: "stdout", contains: "FINAL_EVENT_LOG", exactCount: 1},
    {stream: "stdout", contains: "FINAL_STATE", exactCount: 1},
    {stream: "stdout", contains: "FINAL_COVERAGE", exactCount: 1},
    {stream: "stdout", contains: "FINAL_SUMMARY", exactCount: 1},
  ]
  requireExitCode:       0
  requireNoDescendants:  true
  stdioMode:             "pty"
}
```

Do not hard-code these example marker names, Make, Rust, audio, or a UI toolkit. Marker predicates, lifecycle, environment, and timing are declared data.

### Process supervision semantics

The built-in lifecycle provider and runner must:

- execute an argument vector directly without a shell;
- use the canonical declared working directory;
- start a uniquely owned process/session group where the platform permits;
- monitor the process while it runs rather than treating the first success string as completion;
- use separate declared startup, progress-silence, completion, completion-to-exit, teardown, and total hard limits;
- support pipe mode and an explicitly requested PTY mode so buffering cannot turn a progressing process into false silence;
- capture bounded stdout and stderr, milestone times, exit code, signal, timeout stage, parent PID, and owned-descendant lifecycle without recording secrets;
- terminate only the exact process tree it spawned after a failed gate or timeout;
- escalate teardown in bounded stages and report every signal/action;
- verify after a grace interval that no owned descendant remains; and
- return a nonzero acceptance result for any lifecycle, assertion, marker, timeout, cleanup, or provider failure.

Never locate teardown targets by executable name, shell glob, or an unrelated PID. Tests must not leave fixture processes behind.

“Realistic timeout” is a declared contract, not a hard-coded short delay. A slow process that keeps producing valid progress within its declared budget must not be labeled hung. A process that has emitted terminal success but remains alive past the much shorter completion-to-exit grace period must fail promptly and specifically as `success_reported_but_process_resident` or an equivalent stable diagnostic.

### Interaction provider extension point

Core cannot know how to press a native key, trigger a device callback, send a protocol message, or coordinate a project-specific race. Add a language-neutral provider interface and registry for declared runtime interactions or allow a runtime-session proof to invoke an explicitly named project-owned interaction driver.

The declaration must bind each action to an observed runtime milestone and require structured evidence that:

- the intended action was attempted;
- it reached the declared production seam;
- its timing fell between the declared before/after milestones; and
- the expected state/lifecycle assertions were evaluated against the same session.

Unsupported or missing providers fail closed. Do not infer providers from command names, file extensions, framework output, or the host OS. Adding another interaction mechanism must not require changes to acceptance orchestration or archive logic.

## Inventory and applicability

Acceptance currently treats project checks and attached test-suite proofs as executable gates. Expand the inventory so every applicable attached runtime-session proof is independently binding too.

The report must bind immutable evidence to:

- validation ID;
- declaration owner and location;
- change applicability;
- exact command argv and canonical cwd;
- proof type and provider;
- boundary and environment fidelity;
- lifecycle classification;
- all timeout budgets;
- progress and completion observations;
- interaction evidence;
- parent and descendant termination state;
- assertion results; and
- bounded diagnostics.

An unavailable physical/native environment is not a pass or an implicit skip when the current slice requires that proof. It is a blocking required-proof gap. Projects may declare where a physical proof is applicable, but host capability detection must not silently weaken an applicable obligation. Any waiver mechanism must be explicit, scoped, user-approved, visible in the report, and must not be described as executed proof.

Projects without runtime-session declarations preserve current behavior. No normal read, planning, context, status, list, static validate, or archive command may begin executing runtime sessions.

## End-of-execute workflow changes

Update the shared workflow and generated skills so `/opsx:apply` does all of the following after the final implementation task, including when it starts with every checkbox already complete:

1. rebuild the obligation and architecture-conformance ledgers from evaluated CUE and the final implementation diff;
2. run strict change validation and the future merged-spec validation used by acceptance—an earlier `validate --strict` pass is not a substitute;
3. run the runtime-boundary, terminal-success, critical-interleaving, and declaration-honesty semantic guards;
4. execute `openspec acceptance <change> --json`, including all applicable runtime-session proofs;
5. monitor every runtime proof through teardown rather than returning on a marker;
6. repair and rerun when a gate fails; and
7. report execute/apply complete only when both semantic and deterministic layers pass.

If a required physical or interaction proof cannot be run, execution remains incomplete with `BLOCKING_REQUIRED_PROOF_GAP`. Do not suggest archive as if verification succeeded.

Archive and bulk archive must remain non-executing. They consume the already reviewed completion state and user approval; they do not rerun devices, windows, services, or project checks.

## Required self-contained regression fixtures

Use short, deterministic fixture executables and bounded timeouts. Cover at least:

1. emits the required success marker and then hangs forever: fails at completion-to-exit grace, exact process tree is cleaned up;
2. emits progress slowly but within declared silence and total budgets, then exits cleanly: passes;
3. becomes silent before completion: fails at the correct timeout stage;
4. exits zero before a required marker: fails;
5. emits a required marker zero times, twice, or out of order: fails with stable diagnostics;
6. parent exits while an owned child remains: fails and cleans up the child;
7. fully bounded command emits exact markers, exits zero, and leaves no descendants: passes;
8. fake/in-process test passes while mandatory external runtime proof hangs: overall acceptance fails;
9. dry-run/reachability declaration offered for a runtime claim: rejected as proof-role mismatch;
10. persistent service reaches readiness and is deliberately stopped by its declared controller: passes without being treated as bounded application completion;
11. required runtime provider is missing or malformed: fails closed;
12. PTY mode observes progress that a buffered pipe fixture with the same declared silence limit would not expose;
13. an interaction driver acts between two milestones and returns matching structured evidence: passes;
14. an action occurs before or after the required race window, does not reach the declared seam, or reports evidence from another session: fails;
15. host capability for an applicable physical proof is unavailable: produces a blocking proof-gap result, never pass/skip;
16. runtime timeout cleanup cannot terminate an unrelated process with the same executable name;
17. JSON mode emits exactly one complete versioned report for each pass or failure path;
18. generated apply/verify skills and command templates contain the same new semantic guards;
19. archive remains non-executing; and
20. projects without the new declaration retain documented compatibility.

Follow `test/AGENTS.md` for cross-platform path, signal, process-tree, and canonicalization behavior. Avoid tests that assume Unix-only process APIs unless an explicit platform adapter and equivalent Windows coverage are provided.

## Crest Synth read-only dogfood

After self-contained CrestOpenSpec tests pass, use `~/workspace/crest-synth` only to demonstrate the finding model:

- show that `make -n demo-live` is reachability evidence, not runtime-session evidence;
- show that a fake-window live test cannot claim the physical process boundary;
- show that the corrected `make demo-live` now emits each final record once, exits zero within the declared grace, and leaves no owned process behind; and
- show that the deterministic production-composition witness injects mapped input in the dispatch-to-observation interval and asserts the required isolation.

Do not make CrestOpenSpec's automated test suite depend on Crest Synth, a physical audio device, a desktop session, Make, Cargo, or any downstream checkout.

## Implementation scope

At minimum, inspect and update the compatible portions of:

- acceptance declaration parsing and inventory;
- acceptance types and versioned JSON report;
- process runner/supervisor and bounded output capture;
- proof-provider registry and runtime-session provider;
- generic marker/order/count assertions;
- shared semantic-review template;
- apply and verify source templates and generated skills;
- documentation and CLI/agent contracts;
- template parity tests; and
- end-to-end CLI acceptance fixtures.

Do not add a database, daemon, mutable acceptance ledger, downstream-specific parser, source-language AST heuristic, or framework-specific UI automation to core.

## Verification before handoff

Run and report:

- focused process-supervision, runtime-provider, inventory, report, apply-template, verify-template, and archive-nonexecution tests;
- the complete CrestOpenSpec test suite;
- lint, type checking, formatting, and required builds;
- strict validation of `add-runtime-lifecycle-acceptance-gates`;
- end-of-execute semantic review;
- `openspec acceptance add-runtime-lifecycle-acceptance-gates --json`; and
- fixture runs proving that “success marker then resident process” fails while “slow progress then clean teardown” passes.

Do not declare the execution phase complete if a fixture process remains alive, a runtime proof was skipped, an applicable physical/interaction proof is unavailable, generated templates drift, or the full acceptance report fails.

## Final handoff

Report:

- the OpenSpec change and branch/worktree used;
- the runtime-session declaration and provider architecture;
- how lifecycle classes, milestone timing, process-tree ownership, PTY mode, and interaction evidence remain language neutral;
- exact files changed;
- exact commands and results;
- example JSON for `success_reported_but_process_resident`;
- example JSON for a critical-interleaving timing mismatch;
- proof that the runner cleaned up only its owned process tree;
- proof that archive still does not execute acceptance;
- proof that dry-run reachability cannot satisfy runtime behavior;
- proof that projects without runtime-session declarations retain current behavior; and
- confirmation that no downstream repository or user-owned work was modified.
