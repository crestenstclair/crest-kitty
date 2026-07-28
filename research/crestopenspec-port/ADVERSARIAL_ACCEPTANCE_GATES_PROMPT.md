# Prompt: Language-Agnostic Adversarial Acceptance Gates

Work in `~/workspace/crestopenspec`.

## Objective

Integrate a phase-aware adversarial implementation review into OpenSpec acceptance, and make all of the following mandatory acceptance gates:

- successful CUE architecture evaluation;
- strict OpenSpec validation;
- execution of every declared project completion check;
- execution of every test-bearing validation attached to an applicable CUE resource or witness, even when a broader project check also runs;
- assertion evaluation for each executed check;
- proof that every test-bearing check executed at least one test.

The implementation must be language-, build-system-, and test-runner-agnostic. Project-specific behavior belongs behind explicit extension points, never in the acceptance model itself.

## Preflight and worktree isolation

1. Read every applicable `AGENTS.md`.
2. Inspect `git status`, `openspec list --json`, and `openspec context --json`.
3. The source ref must contain the in-progress CUE bridge and architecture-context work. Do not implement in a dirty checkout and do not stash, copy, discard, or overwrite uncommitted work. If that work is not committed, stop and report the exact prerequisite.
4. Create a dedicated sibling worktree and branch from the committed source ref, for example:
   - worktree: `../crestopenspec-adversarial-acceptance`
   - branch: `codex/adversarial-acceptance-gates`
5. Inspect the active `track-spec-progress` change. Do not silently broaden or replace it. Reuse a shared executable-check service if compatible, while preserving its rule that ordinary progress and context reads never execute project commands.
6. Use OpenSpec itself for this work. Create a new change such as `add-adversarial-acceptance-gates`, complete its proposal, design, delta specs, and tasks, validate it strictly, and then implement it. Do not use legacy crest-spec tooling.

Preserve unrelated user work and existing behavior for projects that do not declare CUE architecture or executable acceptance gates.

## Existing behavior to reconcile

- CUE is evaluated and injected into planning, exploration, apply, and verify context.
- Invalid or conflicting CUE already stops those context-producing paths.
- `/opsx:verify` is currently an advisory agent workflow in the expanded profile.
- It can declare readiness without executing `completion.projectChecks`.
- Archive validates OpenSpec deltas and task state but does not execute CUE project checks, and some paths allow validation to be skipped or accepted with warnings.
- The proposed progress command keeps normal reads non-executing and runs declared checks only through an explicit action. Preserve that trust boundary.

## Acceptance has two distinct layers

Implement and document two layers without conflating them:

1. **Deterministic acceptance gates** implemented in core code, producing structured evidence and an enforceable exit status.
2. **Adversarial semantic review** implemented through shared agent-workflow instructions, producing evidence-backed findings about implementation conformance.

Do not claim that command success proves semantic conformance. Do not let an agent's prose substitute for executable proof.

## Phase-aware applicability

Before reporting a contract violation, construct an obligation ledger from the repository's declared authority documents, evaluated CUE, the selected OpenSpec change and its artifacts, and the implementation diff.

Classify every reviewed obligation as exactly one of:

1. `CURRENT_SLICE`
   - Explicitly required by the selected increment, its evaluated CUE, or its OpenSpec proposal, specs, design, or tasks.

2. `EVERGREEN_INVARIANT`
   - A master safety, ownership, domain, dependency, compatibility, or architecture rule that applies to every implemented slice even if the complete product capability is scheduled later.

3. `DEFERRED_SCOPE`
   - A later roadmap phase, explicit non-goal, or future capability that the selected slice does not claim to implement.

4. `UNAUTHORIZED_EARLY_SCOPE`
   - Later functionality implemented prematurely in a way that contradicts current exclusions or the master architecture.

Only the following may block acceptance:

- an implemented path contradicts a `CURRENT_SLICE` obligation;
- an implemented path contradicts an `EVERGREEN_INVARIANT`;
- an `UNAUTHORIZED_EARLY_SCOPE` implementation exists;
- evidence explicitly required for an applicable obligation is missing or invalid;
- a deterministic gate fails.

`DEFERRED_SCOPE` is never a failure merely because it is absent. Record it as `not applicable — deferred` or omit it. A deliberately narrow implementation is allowed; it must not redefine or contradict the master design.

A reported violation requires all of:

- a cited authoritative requirement;
- an explicit applicability classification and rationale;
- concrete evidence from a current or executed implementation path;
- a specific contradiction or falsifiable consequence.

Keyword searches, architectural suspicion, missing future features, or lack of investigation are not proven violations. Use these finding classes:

- `BLOCKING_CURRENT_VIOLATION`
- `BLOCKING_EVERGREEN_VIOLATION`
- `BLOCKING_REQUIRED_PROOF_GAP`
- `DEFERRED_NOT_APPLICABLE`
- `INFORMATIONAL_FUTURE_RISK`

## Mandatory architecture-drift guards

For every `CURRENT_SLICE` obligation and `EVERGREEN_INVARIANT`, review the complete trace from evaluated architecture declaration to production composition, runtime behavior, and behavioral witness. A locally correct component is not sufficient when the production composition drops, bypasses, overwrites, or makes its contract unreachable.

These guards have two enforcement routes:

- deterministic acceptance enforces declared validation coverage, process results, assertions, and structured evidence;
- adversarial semantic review inspects composition and implementation meaning that cannot be established by a language-neutral command runner.

Do not add source-language AST assumptions, framework names, method spellings, or ecosystem-specific heuristics to core acceptance. If a project wants machine-enforced source analysis, it must declare an executable validation or install an explicit provider. Unsupported semantic inference never becomes a passing deterministic gate.

### Composition-root and dependency-direction guard

Use evaluated CUE relationships, ports, adapters, layers, application services, assets, and composition-root declarations to build a production dependency map.

For every declared port or injected dependency:

- identify the declared owner that selects and constructs the concrete implementation;
- identify the production composition site that supplies it;
- trace the value into the application service that consumes the port;
- verify that production code uses the supplied dependency instead of constructing, importing, or selecting a concrete adapter internally;
- verify that the port is not present only in declarations or tests while production bypasses it;
- verify that declared layer direction is preserved by the production dependency graph.

Report a blocking violation when an application service constructs or selects a concrete provider, adapter, transport, device, repository, or boundary that the applicable architecture assigns to a composition root or injection port. Do not invent a blanket dependency-injection rule: construction inside a service is a violation only when the applicable architecture places that decision elsewhere.

Require a production-composition witness that substitutes or deliberately mismatches the dependency at the declared port and observes the specified typed acceptance or rejection. A unit test of the concrete adapter alone does not prove that the production composition honors the port.

### Negotiation-before-preparation guard

For every prepared artifact whose validity depends on a runtime-selected environment value—such as a device format, protocol version, schema revision, capacity, topology, feature set, page size, or hardware limit—trace:

1. where the actual runtime value is negotiated or discovered;
2. where it is validated;
3. where dependent state is prepared;
4. where runtime processing starts;
5. how later runtime values are checked against the prepared contract.

The required order is negotiate or discover → validate → prepare a complete compatible artifact → start runtime processing. Report a blocking violation when code prepares from a default or requested value before negotiation, ignores the actual negotiated value, silently truncates work beyond prepared capacity, or starts processing with an artifact prepared for an incompatible environment.

Require controlled witnesses using at least one supported non-default negotiated value and relevant capacity boundaries. Unsupported configurations must fail visibly before processing begins; silent truncation, silent padding, or degraded fallback is not proof of compatibility.

### Asynchronous runtime-failure guard

Trace both startup failures and failures delivered after startup through callbacks, futures, event streams, worker completions, device notifications, and background tasks.

When the applicable contract requires a typed, visible, observable, or recoverable failure:

- every asynchronous error entry point must feed a bounded status, error transport, state transition, or other declared observation path;
- an empty error handler, ignored callback argument, detached failed task, caught-and-discarded exception, conversion to unconditional success, or silent output is a blocking violation;
- the observation must reach the declared control or user-visible boundary rather than remaining trapped inside an adapter;
- success after startup must not be treated as proof that later failures are handled.

Require a controlled negative witness that injects a failure after successful startup and proves the exact production observation or recovery behavior.

### End-to-end failure-observability guard

When a component returns a typed status or error and the applicable contract says the failure is observable, trace that result through every production caller.

Report a blocking violation when a caller discards the result, reduces it to an unused boolean, catches it without recording the failure, substitutes ordinary success, or proves only that corrupt mutation did not occur. “Nothing was misrouted” and “the failure was observable” are separate obligations and require separate assertions.

The behavioral witness must enter through the production composition seam, provoke the failure, prove that no forbidden mutation or fallback occurred, and independently prove the required error/status/counter observation. A direct component test that observes a returned error does not cover a production caller that later erases it.

### Validation-declaration integrity guard

Build a validation inventory from both:

- `completion.projectChecks`; and
- validations attached to every applicable CUE resource, relationship, capability, invariant, witness, or acceptance asset.

Every applicable test-bearing validation declaration is independently binding. It must either execute with trustworthy nonzero evidence under its own declared selector or be rejected as malformed or unsupported. A broad test-suite command does not rehabilitate a stale targeted validation, and a targeted validation that selects zero tests must fail even when the complete suite passes.

The deterministic report must bind evidence to the exact validation identity, declaration location, argument vector, provider, selector, and execution. Do not reuse an unrelated invocation's test count, a success marker, or a broad suite's count to make a zero-selection validation pass. Exact duplicate commands may share one physical execution, but each declaration must reference the same immutable evidence record and satisfy its own assertions and minimum execution count.

If applicability cannot be derived deterministically from explicit evaluated metadata, fail closed or conservatively include the validation. Do not let the core acceptance service guess roadmap intent from prose.

## Deterministic acceptance service

Create one core acceptance service with a coherent CLI surface. Prefer `openspec acceptance <change-name> [--json]` unless repository conventions identify a clearly better, non-conflicting name.

The service must:

1. Resolve repositories and stores through existing canonical root-selection behavior.
2. Evaluate the complete top-level CUE package in memory.
3. Fail closed on bridge errors, conflicts, incomplete CUE, invalid output, or unresolved architecture.
4. Strictly validate the selected OpenSpec change and every canonical specification affected by it using shared validator code.
5. Provide a project/release mode that strictly validates all applicable OpenSpec material.
6. Resolve every `completion.projectChecks` reference to exactly one project-scope validation. Missing, duplicated, malformed, or ambiguous references fail acceptance.
7. Build the applicable validation inventory described above. Include resource- and witness-level test validations; do not assume a broad project check covers their declared selectors. Missing applicability metadata, orphaned evidence references, duplicated identities, and ambiguous ownership fail closed according to the designed schema.
8. Execute every resolved project check and every applicable test-bearing validation from its declared argument vector:
   - never use shell interpolation;
   - use an explicit canonical working directory;
   - enforce the declared timeout and resource limits;
   - capture exit, signal, timeout, stdout, and stderr;
   - evaluate every declared assertion;
   - treat nonzero exit, signal termination, timeout, or failed assertion as blocking.
9. Return nonzero whenever any mandatory gate fails.
10. Produce deterministic human output and exactly one documented JSON result in JSON mode.
11. Include execution provenance without recording environment secrets: validation ID, declaration location and owner, argument vector, working directory, timing, termination state, assertion results, test evidence, and bounded stdout/stderr diagnostics.
12. Remain transient. Do not add a database, cache, generated status manifest, daemon, or mutable verification ledger.

Only explicit acceptance/check operations may execute repository-declared commands. `context`, `list`, ordinary progress reads, planning, and static validation must not unexpectedly execute them.

## Language-agnostic executable checks

Model command execution, assertions, and test evidence as independent concepts:

- A command runner executes an argument vector and produces a neutral process result.
- Assertion evaluators consume that result and implement declared assertions.
- Test-evidence providers determine whether a test-bearing validation actually executed tests.

Core acceptance types must not contain names, flags, output grammar, or assumptions from any specific programming language, package manager, compiler, build tool, or test runner.

Project-specific parsing or invocation behavior must live behind a provider interface and registry. Providers may be built in, installed, or selected by explicit validation metadata, but they are peers; no ecosystem is the default architecture.

Prefer explicit structured metadata such as the following conceptual contract, refining the exact schema during design:

```yaml
proof:
  type: test-suite
  provider: <provider-id>
  minimumExecuted: 1
```

The neutral result should be able to report:

```yaml
testEvidence:
  provider: <provider-id>
  discovered: <integer-or-unknown>
  executed: <integer>
  passed: <integer-or-unknown>
  failed: <integer-or-unknown>
  skipped: <integer-or-unknown>
  source: <structured explanation of how the count was established>
```

The exact serialized shape may differ, but its semantics must remain tool-independent.

## Mandatory nonzero-test validation

A successful process exit is insufficient for a test-bearing check.

For every validation declared as a test suite:

- require trustworthy evidence that `executed >= minimumExecuted`;
- default `minimumExecuted` to at least one;
- do not count discovered, filtered, skipped, ignored, compiled, or merely enumerated tests as executed;
- fail if the provider cannot establish an executed count;
- fail if the evidence is malformed, internally inconsistent, or reports zero execution;
- bind the executed count to the exact declared invocation and selector rather than another broad or related test run;
- preserve the process result and test evidence as separate report fields.

Do not infer test success from validation descriptions, filenames, success markers, or arbitrary human-readable text in core code. If a provider parses runner-specific output, that parser must be isolated in the provider and covered by provider-specific tests.

Non-test integration checks, smoke programs, linters, compilers, formatters, and other executable proofs must not be subjected to test-count rules unless they explicitly declare test-suite proof.

Design the provider registry so support for a new test runner does not require changes to the acceptance service, archive flow, report model, or CUE/OpenSpec semantics.

## Adversarial semantic review

Refactor verify and archive workflow templates to share one acceptance-review contract instead of duplicating prose that can drift.

The review must:

- read evaluated CUE before reviewing artifacts and implementation;
- build the phase-aware obligation ledger above;
- build an architecture-conformance matrix linking each applicable port, layer, composition decision, prepared-runtime constraint, failure channel, and validation declaration to its production implementation and witness;
- trace current behavior through declared relationships, layers, boundaries, resources, assets, validations, witnesses, and production paths;
- apply every mandatory architecture-drift guard above and distinguish local component correctness from end-to-end production conformance;
- prefer production execution and controlled negative proof over success strings, mocks that bypass the behavior, or construction-only tests;
- run the deterministic acceptance service;
- never report `ready to archive` when a deterministic gate or applicable blocking finding fails;
- include authority citation, applicability, implementation evidence, proof command, observed result, severity, and repair direction for every blocking finding;
- list deferred observations separately and state explicitly that they do not affect acceptance.

Integrate the shared review contract into:

- source and generated `/opsx:verify` skill/command templates;
- `/opsx:archive`;
- bulk archive where applicable;
- documentation;
- generated-skill and template-parity tests.

## Archive enforcement

For CUE-governed projects:

- Core `openspec archive` must run deterministic acceptance before modifying canonical specs or moving a change.
- `/opsx:archive` must perform the shared adversarial review and deterministic gates before archiving.
- Bulk archive must enforce the same rule independently for each change and report partial eligibility without archiving failures.
- `--yes`, incomplete-task confirmation, warning acceptance, and existing validation-skip behavior must not bypass CUE evaluation, strict OpenSpec validation, project checks, assertions, or test evidence.
- Make backward compatibility for existing validation-skip flags explicit in the design. At most they may retain legacy behavior for projects outside the new gate contract; they cannot mean “skip mandatory acceptance.”
- No archive mutation may occur before all mandatory checks pass.

Projects without CUE or without the new executable-gate declarations must preserve documented legacy behavior and report unavailable gates as `not applicable`, not silently pretend they ran.

Keep the enforcement boundary honest: a direct CLI archive can enforce deterministic gates but cannot itself perform semantic agent reasoning. Document that distinction rather than claiming otherwise.

## Security and execution constraints

- Treat repository-declared commands as trusted only after the user invokes an explicit command-running workflow.
- Execute argument vectors directly without a shell.
- Do not interpolate repository data into command strings.
- Apply timeouts and bounded output capture.
- Do not include environment values or secrets in reports.
- Preserve platform-neutral path handling and canonical path identity.
- Return structured failure for unavailable executables and unsupported evidence providers.
- Never convert an unsupported proof into a passing or skipped gate.

## Required tests

Use self-contained temporary fixture projects and neutral fixture executables. The acceptance test suite must not require a particular application language or globally installed project toolchain.

Cover at least:

- valid and invalid CUE evaluation;
- missing, duplicated, malformed, and ambiguous project-check references;
- an applicable resource-level test validation selecting zero tests while a broad project suite succeeds;
- evidence from a broad test run being rejected when offered for a different targeted validation selector;
- command success, nonzero exit, signal, timeout, and assertion failure;
- a test provider reporting zero executed tests while the process exits successfully;
- a provider reporting positive execution;
- malformed or inconsistent test evidence;
- a test-bearing check with no available provider failing closed;
- provider registration and selection without changes to core acceptance logic;
- non-test executable checks remaining unaffected by test-count enforcement;
- argument-vector safety and paths containing spaces;
- store-aware and canonicalized root behavior;
- one-document JSON failure output and nonzero status;
- archive blocked before any filesystem mutation;
- confirmation flags unable to bypass mandatory gates;
- projects without CUE retaining documented behavior;
- generated verify/archive skill and command parity;
- phase-aware wording that expressly forbids treating deferred roadmap scope as a violation.

Also test the shared adversarial-review contract with self-contained fixtures that contain:

- a declared injected port whose application service constructs the concrete adapter internally;
- a declared port that exists in tests but is bypassed by production composition;
- a prepared artifact built from a default before a different supported runtime value is negotiated;
- work beyond a declared prepared capacity being silently truncated or padded;
- an asynchronous error callback or failed task that is ignored after successful startup;
- a component-level typed failure that a production caller discards;
- a negative test that proves non-mutation but omits the separately required failure observation;
- conforming counterparts for every case above so the review rules do not mandate one implementation style beyond the evaluated architecture.

Keep these fixtures language-neutral or use multiple deliberately different fixture syntaxes. They test the review contract and evidence model, not a source-language parser.

Follow `test/AGENTS.md` for cross-platform paths and canonicalization.

## Verification before handoff

Run and report:

- every build required by the repository;
- focused tests for CUE evaluation, acceptance execution, evidence providers, CLI output, archive behavior, and generated templates;
- the complete repository test suite;
- linting and type checking;
- strict validation of the new OpenSpec change;
- the new acceptance command against self-contained passing, failing, unsupported-provider, and zero-test fixtures.

Do not edit a downstream application repository as part of this implementation. Downstream repositories may be used read-only for optional manual dogfooding only after self-contained tests pass.

## Final handoff

Report:

- the OpenSpec change name;
- the chosen architecture and why it is language agnostic;
- core interfaces and extension points;
- files changed;
- exact verification commands and results;
- example JSON for a successful process that fails acceptance because it executed zero tests;
- confirmation that adding another test runner requires only a provider, not changes to acceptance or archive logic;
- confirmation that deferred roadmap functionality cannot produce a blocking violation;
- confirmation that applicable resource-level test validations cannot hide behind a passing broad suite;
- confirmation that composition, negotiation order, asynchronous failures, and end-to-end error observability were each exercised by conforming and violating fixtures;
- confirmation that no user-owned work was reverted or overwritten.
