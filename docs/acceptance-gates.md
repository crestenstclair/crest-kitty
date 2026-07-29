# Deterministic acceptance gates

Spec Kitty's acceptance has two deliberately separate layers:

1. **Deterministic acceptance** — core CLI code with an enforceable exit
   status. It evaluates the project's crest-spec, resolves every
   declared validation fail-closed, executes them under strict process
   bounds, and emits one versioned JSON report.
2. **Adversarial semantic review** — the agent workflow embedded in the
   `accept` and `review` mission-step prompts (obligation ledger,
   evidence-complete findings, nine crest-spec drift guards; see
   `specify_cli.acceptance.execution_contract`).

Both must pass before a mission is accepted. Archive later consumes the
recorded verdict (guard AM-6) and never re-runs either layer.

## When the gate is armed

Deterministic acceptance applies only when the project opts in through its
crest-spec (`.kittify/crest-spec/`, see
`research/crestopenspec-port/spec-format-README.md` for the format):

- the spec's `completion.projectChecks` is present (even as `[]`), **or**
- any declared validation carries a `proof` field.

No spec, or a spec without either signal, reports `not_applicable` and passes
vacuously. An invalid spec, or any malformed declaration, **fails closed**
before anything executes.

## Declaring validations

Project-scope checks live in `proof/validations.yaml` and are referenced by
ID from `completion.projectChecks` (exactly-one resolution — missing,
duplicate, or ambiguous references fail closed):

```yaml
# .kittify/crest-spec/proof/validations.yaml
defaults:
  workingDirectory: .
  limits: {timeoutMs: 300000, stdoutBytes: 8388608, stderrBytes: 8388608}
projectValidations:
  unit_suite:
    scope: project
    command: [cargo, test, --workspace]
    assertions:
    - {type: exit-code, equals: 0}
    - {type: stdout-contains, value: "test result: ok"}
```

Attached validations (hoisted with `attachedTo: <resource-id>`) are binding
only when they carry a `proof`; proof-bearing attachments require
`scope: attached` and explicit applicability (`{mode: always}` or
`{mode: changes, changes: [<mission-slugs>]}` — mission-scoped checks also run
conservatively in project scope).

## The process boundary

- `command` is an argv **array**, never a shell string.
- `workingDirectory` must canonicalize inside the project root.
- `limits` are hard caps: timeout at most 30 minutes, 16 MiB per captured
  stream. Exceeding them terminates the check
  (`validation_timed_out` / `validation_output_limit`).
- Environment values are never serialized into reports.
- Assertion types: `exit-code`, `stdout-contains`, `stdout-not-contains`,
  `stderr-contains`, `stderr-not-contains`. Every declared assertion is
  evaluated even after process failure; anything malformed fails closed.

## Trustworthy test evidence

A `{type: test-suite}` proof requires structured evidence from its declared
provider — a green exit code is not enough:

```yaml
    proof:
      type: test-suite
      provider: structured-json-v1     # or junit-xml-v1
      minimumExecuted: 12
      selector: {suite: engine-selection}
      options: {stream: stdout}
```

The core (not the provider) enforces: non-negative consistent counts, zero
failures, deep-equal selector match, and `executed >= minimumExecuted >= 1`.
**The canonical example: a process that exits 0 while reporting
`executed: 0` fails acceptance with `test_evidence_minimum_not_met`.**
Discovered, skipped, or filtered tests never count as executed.

## Runtime-session proofs

Claims about an external process lifecycle (a user-facing command that must
start, emit its markers in order, exit cleanly, and leave no resident
descendants) require a `{type: runtime-session}` proof executed by the runtime
lifecycle engine (`specify_cli.acceptance.runtime_lifecycle`). The signature
failure it exists to catch: `success_reported_but_process_resident` — all
success markers emitted, process still resident. Persistent lifecycles declare
readiness plus a bounded teardown protocol. Unavailable host capabilities
(display, audio, devices) are a `BLOCKING_REQUIRED_PROOF_GAP`, never an
implicit skip.

## Where it runs

- `spec-kitty accept --mission <handle>` — runs readiness + the deterministic
  engine, records `<mission>/deterministic-acceptance.json`, and fails the
  acceptance on any gate failure.
- `spec-kitty accept --mission <handle> --deterministic-only [--json]` — just
  the deterministic engine and its report.
- `spec-kitty crest-spec doctor` / `spec-kitty crest-spec context` —
  ordinary reads: validate and render the spec, never execute validations.
- `spec-kitty archive create` — refuses a merged mission without a recorded
  passing verdict (AM-6) and executes nothing.

The explicit-execution boundary is tested
(`tests/crest_spec/test_nonexecution_boundary.py`): only accept
executes declared commands; every other surface is a read.
