"""The agent-facing interpretation contract and context rendering.

Ported from CrestOpenSpec's ``CUE_INTERPRETATION_CONTRACT``; the semantic
model (intent / architecture / proof) is unchanged, the evaluation section is
rewritten for the terse YAML crest-spec format, and the artifact-mapping
section is rewritten for spec-kitty's mission workflow with the derivation
direction made explicit: the crest-spec is the bedrock and every mission
artifact derives from it.
"""

# ruff: noqa: E501 — the interpretation contract is agent-facing prose kept as
# long semantic lines; wrapping would put hard newlines inside rendered bullets.
from __future__ import annotations

import json
from typing import Any

from .loader import CrestSpec
from .relationships import Relationship

CREST_SPEC_INTERPRETATION_CONTRACT = """How to interpret and use the crest-spec

Authority and derivation direction
- The crest-spec is the bedrock: the single source of implementation intent. Planning, work decomposition, code generation, and proof all derive FROM it; it is never reconciled TO other documents after the fact.
- A mission that adds, changes, or retires system structure BEGINS by editing the crest-spec. If the crest-spec does not declare it, it does not get built. Never edit the crest-spec merely to permit code that was already planned — when product intent (DESIGN.md, visual references) and the crest-spec disagree, that is a decision to make deliberately during crest-spec authoring, before planning.
- All listed files form one crest-spec namespace. File boundaries are organization, not scoping; declarations across files are one model.
- Resources are declared as named entries whose canonical dotted ID derives from section, context, and name (for example `valueObject.Control.PatchControlId`). References may use the shortest unique dot-suffix; the rendered project below has every reference expanded to its canonical ID.
- The rendered project is the concrete result of loader expansion. It is the primary input to planning.
- The crest-spec is authoritative for architectural intent, boundaries, dependency direction, contracts, invariants, traceability, and verification. Mission artifacts (spec/plan/tasks) reference its declarations; they never restate them.
- The crest-spec is also the dense, user-facing overview of the architecture. Keep declarations concise and relational; encode the authoritative model and proof instead of copying explanatory Markdown prose.
- The loader closes the model under you as you write: undeclared references fail immediately. Author the crest-spec first and lean on that referential integrity — it is faster and safer than discovering the gaps at acceptance.

Intent model
- `mission` is the whole-project why and must inform every local decision. `nonGoals` are explicit exclusions.
- `actors` are stable participants. `goals` are outcomes, not implementation work; their status is derived rather than authored in the spec.
- `capabilities` are observable functionality that can serve multiple goals. Their `acceptance` scenarios describe journeys and required evidence.
- `requirements` are functional or nonfunctional constraints linked to goals and/or capabilities.
- `evidence` declares the proof required. `completion.requiredGoals` and `completion.projectChecks` define what completion means.
- Goal/capability links are bidirectional by design. Preserve their traceability rather than inventing unlinked capabilities.

Architecture model
- `contexts` are bounded contexts. Their `purpose`, `ubiquitousLanguage`, and invariants define ownership and vocabulary.
- `valueObjects` are immutable domain values: `from` is a newtype/enum representation (a list means a union of variants); `state` is a structured value.
- `aggregates` are consistency boundaries. `state`, `commands`, `events`, and `invariants` define their behavioral model. Nested entities/value objects belong to that aggregate.
- `domainServices` hold domain behavior that does not naturally belong to one aggregate. `applicationServices` orchestrate use cases through operations and dependencies.
- `repositories` are persistence abstractions; `of` identifies the aggregate they store and `contract` defines the boundary.
- `ports` own boundary behavior. `direction` is inbound/outbound, `contract` defines operations, and `consumes` declares dependencies.
- `adapters` are delivery/infrastructure implementations of ports. `implements` points to the port; the port remains owner of the behavioral contract. Adapter profiles describe delivery mechanics, not domain behavior.
- `contextMap`, `layers`, and `layerRules` constrain context relationships and allowed dependency direction.

Resources and relations
- Canonical resource IDs are: `context.<Context>`, `aggregate.<Context>.<Name>`, `entity.<Context>.<Aggregate>.<Name>`, `valueObject.<Context>[.<Aggregate>].<Name>`, `port.<Context>.<Name>`, `repository.<Context>.<Name>`, `domainService.<Context>.<Name>`, `applicationService.<Context>.<Name>`, `adapter.<Name>`, `assetKind.<Name>`, and `asset.[<Context>.[<Aggregate>.]]<Name>`.
- `uses`, `consumes`, `publishes`, `implements`, `of`, and asset `targets` are directed architecture/dependency relations. Respect their direction when designing and sequencing work.
- `contributesTo` links an implementation resource to an observable capability. It is traceability, not a dependency edge. Use it to determine which resources realize a capability and which capabilities a resource can affect.
- Parent/containment relations express ownership, not dependency. Do not move behavior across bounded contexts or aggregate boundaries merely for implementation convenience.

Implementation and proof
- `assets` describe concrete implementation artifacts. Their kind, targets, prompts, profiles, and validations are the generation layer — the implementation intent work packages are derived from, not another planning database. Anything a work-package prompt would need that is not in the asset is a signal the asset is underspecified: push it into the crest-spec.
- `meta` is inherited guidance: language/style/rules/prompts/references/examples/avoid plus notes, rationale, framework, review level, mode, and amendments.
- Invariants are behavioral constraints. Treat them as non-negotiable acceptance/design constraints, not suggestions.
- `validations` are executable checks. Project validations are whole-system gates; attached validations prove local contracts or declared runtime sessions. Keep reachability, static, in-process behavior, external lifecycle, production composition, environment fidelity, and controlled interaction proof roles explicit.
- `witnesses` are behavioral proof with a positive command, a controlled negative command, structured observations, and predicates. Evidence links to validations/witnesses. Do not replace measured proof with self-reported success text.
- A runtime success marker is intermediate evidence, not completion. For applicable external-runtime claims, require a same-boundary runtime-session proof through declared success, teardown, parent exit, owned-resource cleanup, and any milestone-bound critical interaction.

How the crest-spec drives mission artifacts (derivation, not reconciliation)
- Specify: ground the mission's why and scope in mission, goals, non-goals, capabilities, and requirements. Reference the affected canonical IDs; never restate what the crest-spec already declares.
- Crest-spec authoring: for any mission that adds, changes, or retires a resource, edit the crest-spec FIRST — contexts, value objects, aggregates, ports, adapters, assets, capabilities, requirements, evidence, validations, witnesses, invariants — and reload until the model closes. This precedes planning.
- Plan: derive from the authored crest-spec and record the `## Crest-Spec Derivation` section: which canonical resources this mission adds, changes, or retires, and which assets therefore produce which files. Do NOT produce `data-model.md` or `contracts/` when a crest-spec exists — those are hand-copied, immediately-stale forks of `valueObjects`, `aggregates`, and `ports`; point at the canonical resources instead.
- Tasks: derive work packages from `assets[]` — each asset's kind, targets, prompts, profile, and attached validations already carry the generation intent; work packages add only mission-specific sequencing and ownership boundaries.
- Implement: build against the rendered model and relevant source files. Treat crest-spec constraints and relationships as the architectural source of truth.
- Accept: deterministic acceptance runs the declared project checks and applicable attached validations; adversarial review judges conformance against invariants and relations."""


def _stable_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable_value(value[key]) for key in sorted(value)}
    return value


def _render_relationships(relationships: list[Relationship]) -> str:
    if not relationships:
        return "- No explicit relationships declared."
    return "\n".join(
        f"- `{r.from_id}` --{r.relation}--> `{r.to_id}`" + (f" ({r.detail})" if r.detail else "")
        for r in relationships
    )


def render_crest_spec_context(crest_spec: CrestSpec) -> str:
    """Render the expanded crest-spec into the agent-facing project-context channel."""
    file_list = "\n".join(f"- {path}" for path in crest_spec.files)
    rendered_project = json.dumps(_stable_value(crest_spec.project), indent=2)
    return f"""Crest-spec (authoritative)

{CREST_SPEC_INTERPRETATION_CONTRACT}

Source files
Root: {crest_spec.root}
Files:
{file_list}

Resolved relationship index
{_render_relationships(crest_spec.relationships)}

Resolved project value
```json
{rendered_project}
```"""
