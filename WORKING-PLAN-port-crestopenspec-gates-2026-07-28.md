# Working Plan: Port CrestOpenSpec Additions to crest-kitty

> **Rev 4 (2026-07-28, branch `port/crest-spec-bedrock`): the concept is named
> the crest-spec and made the bedrock.** Supersedes this plan's naming: the
> spec home is `.kittify/crest-spec/` (config `crest_spec.root`; the legacy
> `architecture` layout fails loud), the module is
> `src/specify_cli/crest_spec/`, the CLI is `spec-kitty crest-spec
> context|doctor`, the plan artifact section is `## Crest-Spec Derivation`
> (reconciliation vocabulary retired), the software-dev workflow inserts a
> mandatory `crest-spec` authoring phase after specify (D5/C-008 superseded by
> operator instruction), and derivation is enforced by executable gates
> (`CREST_SPEC_UNDERIVED`, `crest_spec_underived`, `crest_spec_unproven`,
> `crest_spec_duplicate_artifacts`). References to `.kittify/architecture`
> below are historical.

Date: 2026-07-28 (rev 3 — Phases 0-5 complete on branch port/crestopenspec-gates; crest-synth cut over and 26/26 validations passing through the ported engine. Open: crest-kitty dogfood spec (needs owner intent) and CI enforcement once it exists.)
Source: `~/workspace/CrestOpenSpec` (fork of Fission-AI/OpenSpec, merge-base `19d4171`)
Feature inventory: `~/workspace/CrestOpenSpec/docs/crest-fork-features.md`
Format reference (normative example): `~/workspace/crest-synth/spec-terse/` + its README

## What is being ported

Four feature areas built in CrestOpenSpec as a test-bed (~14,200 insertions):

1. **Architecture-spec integration** — load a machine-readable architecture
   spec (intent + architecture + proof models), inject the interpretation
   contract, resolved model, and relationship index into agent context;
   enforce a planning-summary artifact that reconciles plans against it.
2. **Adversarial acceptance gates (deterministic layer)** — architecture gate
   → fail-closed validation inventory → strict validation → sandboxed
   execution of declared checks with assertions and mandatory nonzero test
   evidence. Versioned JSON report, ~70 stable diagnostic codes.
3. **Runtime lifecycle acceptance** — `runtime-session` proofs: launch the
   real entry point, supervise the owned process tree, verify marker order,
   exit, and cleanup (`success_reported_but_process_resident`), PTY fidelity,
   host-capability gaps, controlled mid-session interactions.
4. **Workflow/prompt enforcement** — shared `EXECUTION_ACCEPTANCE_CONTRACT`
   (obligation ledger, blocking classes, 9 architecture-drift guards) in
   apply+verify prompts; archive is approval-only; parity tests + the
   language-neutral drift-case fixture matrix.

## Locked decisions

| # | Decision |
|---|----------|
| D1 | **CUE is retired.** The architecture spec is authored in the terse YAML format (below), loaded and expanded by a pydantic loader. No Go, no `cue` CLI, no bridge binary, no external toolchain. |
| D2 | No new `spec-kitty acceptance` verb — extend **`spec-kitty accept`** (`--deterministic-only`, `--json`). |
| D3 | **Spec location: `.kittify/architecture/`** in consumer projects (see "Where the spec lives"). Path configurable via `architecture.root` in `.kittify/config.yaml`. |
| D4 | Blocking enforcement lives in `accept` and `archive` (which already hard-refuse), not the lane-gate registry (contractually fail-open, C-003). |
| D5 | The byte-locked workflow action sequence (C-008) is untouched; enforcement rides the `accept` step contract, prompts, and runbook. |
| D6 | Process-tree supervision uses `psutil` (existing dependency), keeping CrestOpenSpec semantics: own the spawned group, never select by executable name, bounded TERM→KILL with recorded actions. |

## Where the spec lives (D3)

Today crest-synth keeps 20 CUE files in a repo-root `spec/` directory — in the
way, and squatting on a generic name. New home:

```
.kittify/architecture/
  project.yaml          # name, mission, nonGoals, meta, layers, layerRules,
                        # contextMap, completion (requiredGoals + projectChecks)
  actors.yaml
  goals.yaml
  capabilities.yaml     # incl. acceptance scenarios
  requirements.yaml
  contexts/<name>.yaml  # one per bounded context
  adapters.yaml
  assets.yaml           # assetKinds + assets
  proof/
    validations.yaml    # defaults + projectValidations + attachedValidations
    witnesses.yaml
    evidence.yaml
    invariants.yaml
```

Rationale: `.kittify/` is already the project-owned spec-kitty surface
(config, overrides, doctrine, glossaries), so the architecture spec sits with
its tooling and out of the root. It must NOT go under `kitty-specs/` — that
tree is mission-scoped and discovered by glob; a permanent non-mission
directory there would pollute mission enumeration. `architecture.root` in
config.yaml lets a project that wants the spec visible put it at
`architecture/` instead; the loader treats the tree identically. Applicability
rule stays behavioral: no `architecture.root` dir → all architecture-dependent
gates report `not_applicable`.

## The spec format (approved)

Normative example: `crest-synth/spec-terse/` + README. Summary:

1. Single-level maps (`Name: {body}`), canonical IDs derived from
   section + context + name; max depth two to reach any resource.
2. Suffix references — shortest dot-suffix that resolves uniquely
   (`AppState`, `Kernel.PatchId`); field-typed resolution for `goals:`,
   `capabilities:`, `requirements:`, `actors:`, `projectChecks:`, evidence
   `validations:`; untyped fields resolve against all IDs.
3. `contributesTo` is a map of capability-ref → contribution.
4. `defaults:` block in `proof/validations.yaml` for shared
   workingDirectory/limits.
5. Union types are lists in `state:`/`from:`; strings are any other type
   expression.
6. The whole tree is one namespace; files are organization only.

**Loader contract:** expansion produces the exact canonical `project` object
the CUE bridge used to emit (proven by the lossless converter round-trips).
Everything downstream — inventory resolution, relationship index, acceptance
report — consumes that canonical shape, so all CrestOpenSpec semantics port
against an unchanged data model.

**Fail-closed loader diagnostics** (extend the CrestOpenSpec vocabulary):
duplicate map key, ambiguous suffix ref (list candidates), unresolved typed
ref, id/section mismatch, malformed section shape. Ordinary reads never
execute anything.

## Target mapping

| CrestOpenSpec artifact | crest-kitty home |
|---|---|
| `cuebridge/` + `cue-architecture.ts` | new `src/specify_cli/architecture/` — `models.py` (pydantic), `loader.py` (glob/merge/dup-detect), `refs.py` (suffix resolution + expansion), `relationships.py` (ID scheme + ~35 verbs), `contract.py` (interpretation prose, updated for YAML) |
| `context`/`instructions` injection | `spec-kitty context` output + `plan`/`implement` mission-step prompts via `mission_runtime` |
| `summary` planning artifact | `plan` step prompt/guidelines + `gates_core.py` check (pattern: `_check_workflow_run_evidence`) |
| `validation-inventory.ts` | `src/specify_cli/acceptance/inventory.py` (consumes canonical project dict) |
| `service.ts` gate pipeline | `acceptance/__init__.py` + new `gates_core.py` checks |
| `process-runner.ts` | extend `configured_command.py` (argv-only mode, 16 MiB stream caps, 30-min timeout cap, cwd canonicalization) |
| `assertions.ts` / `test-evidence.ts` | `acceptance/assertions.py`, `acceptance/test_evidence.py` (`structured-json-v1` + JUnit provider reusing `baseline._parse_junit_xml`) |
| `runtime-session.ts` + providers + launcher | `src/specify_cli/acceptance/runtime_lifecycle/` (state machine, psutil tree, PTY via `script(1)`, `process-json-v1` driver) |
| runtime evidence types | `proof/events.py`: `RuntimeEvidenceCaptured`; matrix `proof_type: "runtime_lifecycle"` |
| `EXECUTION_ACCEPTANCE_CONTRACT` | shared constant rendered verbatim into `accept`+`review` prompts; parity test asserts verbatim embed + absence in archive |
| archive non-execution | guard **AM-6** in `missions/_archive.py` + `spk-gate-archive` skill |
| drift-case fixtures | copy `architecture-drift-cases.json` unchanged into `tests/fixtures/` |
| `docs/acceptance.md` | `docs/` (adapt commands + YAML examples) |

## Phases and checklist

### Phase 0 — Groundwork
- [x] Copy porting-spec artifacts into `research/` in crest-kitty: both generic
      prompts, diagnostic-code inventory, report schema (`types.ts`),
      `EXECUTION_ACCEPTANCE_CONTRACT`, interpretation contract,
      `architecture-drift-cases.json`, `spec-terse/README.md`
- [x] Freeze the canonical `project` JSON shape as a fixture: check in
      crest-synth's evaluated JSON (`crest-cue-bridge` output) as the loader's
      golden expansion target
- [x] Wire the existing-but-unemitted `TestEvidenceCaptured` proof event from
      `pre_review_gate`/`baseline` runs
- [x] Create missions in kitty-specs (one per phase 1–4)

### Phase 1 — Architecture spec loader (~1.5 WP-weeks)
- [x] `architecture/models.py`: pydantic models for every section (project,
      actors, goals, capabilities+acceptance, requirements, context resources,
      adapters, assets/assetKinds, validations incl. defaults, witnesses,
      evidence, invariants); union-list semantics for `state:`/`from:`
- [x] `architecture/loader.py`: read `architecture.root` from config (default
      `.kittify/architecture`), glob recursively, duplicate-key-detecting YAML
      parse, merge into one namespace; absent dir → `None`; any diagnostic →
      fail closed
- [x] `architecture/refs.py`: canonical-ID derivation, suffix resolution with
      field-typed scoping, defaults expansion → emit the canonical `project`
      dict; **golden test: expansion of the converted crest-synth spec is
      deep-equal to the checked-in CUE-bridge JSON fixture**
- [x] `architecture/relationships.py`: port canonical ID scheme + relation
      verbs + deterministic sort from `cue-architecture.ts`
- [x] `architecture/contract.py`: interpretation-contract prose rewritten for
      the YAML format (semantic model unchanged)
- [x] `spec-kitty doctor architecture`: validate + report diagnostics; happy
      path prints resource/relationship counts
- [x] Tests: loader (absent/valid/ambiguous-ref/dup-key/unresolved-ref),
      relationship determinism; architectural ratchet baseline updates

### Phase 2 — Context injection + planning summary (~0.5 WP-week)
- [x] Inject architecture block (contract + file list + relationship counts)
      into `spec-kitty context` output
- [x] Inject into `plan`/`implement` mission-step prompts (source under
      `src/doctrine/missions/mission-steps/`, never generated copies)
- [x] Planning-summary: dense-summary + reconciliation guidance in the `plan`
      prompt; `gates_core.py` check that a reconciliation summary exists when
      an architecture spec exists
- [x] Regenerate skills (`spec-kitty doctor skills --fix`)

### Phase 3 — Deterministic acceptance gates (~2 WP-weeks)
- [x] `acceptance/inventory.py`: port declaration parsing (project checks with
      exactly-one resolution; attached validations with explicit scope +
      applicability; command/cwd/limits/assertions validation) — every
      malformation fails closed before execution; keep CrestOpenSpec
      diagnostic-code names verbatim
- [x] Applicability: gate armed iff `completion.projectChecks` present (even
      `[]`) or any validation carries `proof`
- [x] `configured_command.py`: argv-list mode, per-stream byte caps, timeout
      cap, cwd-inside-root canonicalization; env never serialized
- [x] `acceptance/assertions.py`: 5 assertion types, registry, fail-closed
- [x] `acceptance/test_evidence.py`: provider registry; `structured-json-v1`;
      core-enforced rules (`executed >= minimumExecuted >= 1`, zero failed,
      count consistency, deep-equal selector); JUnit provider
- [x] `accept` pipeline: architecture gate → inventory → strict validation →
      sequential execution; exit 0 iff pass; `--json` single versioned report
      with `semanticReview: not_evaluated`
- [x] Non-execution boundary tests (context/status/lint/archive execute
      nothing) + archive guard **AM-6**
- [x] Port fixture-project generator scenario matrix (`create-project.mjs`)

### Phase 4 — Runtime lifecycle acceptance (~2 WP-weeks)
- [x] `runtime_lifecycle/session.py`: bounded + persistent lifecycles, six
      timeout budgets, ordered markers, failure stages
- [x] `runtime_lifecycle/process_tree.py` on psutil; test that an unrelated
      same-named process survives cleanup
- [x] `runtime_lifecycle/launcher.py`: pipe + PTY via `script(1)`;
      PTY-unavailable → proof gap, never silent downgrade
- [x] Host capabilities (`process`, `stdio:pipe`, `platform:<os>` only) →
      anything else is `BLOCKING_REQUIRED_PROOF_GAP`
- [x] `runtime_lifecycle/interactions.py`: `process-json-v1` window/session/
      assertion semantics; reject evidence predating invocation
- [x] Inventory runtime-declaration parsing + diagnostics
- [x] `RuntimeEvidenceCaptured` proof event + `proof_type: "runtime_lifecycle"`
- [x] Port runtime fixtures incl. `success-hang` →
      `success_reported_but_process_resident`

### Phase 5 — Prompt/workflow enforcement (~1 WP-week)
- [x] Shared constant with `EXECUTION_ACCEPTANCE_CONTRACT` + 9 guard IDs
- [x] Embed in `accept` + `review` prompts; `spk-gate-accept` extended; new
      `spk-gate-archive` (approval-only, no acceptance rerun, no runtime
      sessions)
- [x] `accept` step contract declares the deterministic gate as `quality_gate`
- [x] Parity tests + drift-case fixture matrix
- [x] Runbook update (`spec-kitty-mission-workflow.md` Phase 5 wording)

### Phase 6 — crest-synth cutover + dogfood
- [x] Regenerate `spec-terse/` from current CUE (converters:
      `scripts/convert_cue_spec_to_yaml.py` → `convert_spec_to_terse.py`) and
      move it to `crest-synth/.kittify/architecture/`
- [x] Validate with `spec-kitty doctor architecture`; run
      `spec-kitty accept --deterministic-only` against the real validations
- [x] Retire `crest-synth/spec/*.cue` (git history preserves it); keep the
      converters until the first successful accepted mission
- [ ] Author crest-kitty's **own** `.kittify/architecture/` spec so the gates
      dogfood in this repo (CrestOpenSpec never did — known gap)
- [ ] CI: deterministic acceptance as `[ENFORCED]` in `ci-quality.yml` once
      the dogfood spec exists
- [x] Docs: port `docs/acceptance.md` with YAML worked examples (keep the
      "green process, zero tests executed, fails acceptance" example)
- [x] Cleanup in CrestOpenSpec: archive `add-adversarial-acceptance-gates`
      (53/53 done, unsynced); remove committed `tmp/refactoring-review.md`

## Risks / gotchas

- Sonar S3776 complexity ≤15 shapes crest-kitty modules — pre-split the big
  ports (`validation-inventory` ~1,400 lines, `runtime-session` ~1,000 lines).
- `tests/architectural/` ratchet baselines trip on new modules; budget updates
  per phase. `test_pyproject_shape.py` constrains new dependencies (none
  needed now that CUE/Go is gone — the biggest de-risking of rev 2).
- YAML-specific: duplicate map keys are silent in default parsers — the
  duplicate-detecting loader is mandatory, not optional. Suffix-ref ambiguity
  grows with the spec; the fail-closed candidate-listing diagnostic is the
  containment (forces qualification, like an import collision).
- `gates_core.py` deferred-import pattern is deliberate — follow it.
- Terminology: "mission" not "feature"; `AGENTS.md` + charter are binding.
- Estimated effort: ~7 WP-weeks. Phase 1 is the hard prerequisite for 3/4
  (the first acceptance gate IS the loader); Phase 2 can overlap 3; Phase 4
  can overlap 5.
