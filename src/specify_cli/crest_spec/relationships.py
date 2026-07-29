"""Relationship index derived from the canonical ``project`` mapping.

Faithful port of CrestOpenSpec's ``buildRelationships``
(``research/crestopenspec-port/reference-cue-architecture.ts``): same canonical
resource-ID scheme, same relation verbs, same deterministic ordering, so
agent-facing renderings match the proven upstream behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Relationship:
    from_id: str
    relation: str
    to_id: str
    detail: str | None = None


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _object_at(obj: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = obj.get(key)
    return value if isinstance(value, dict) else None


def _strings_at(obj: dict[str, Any], key: str) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _sorted_items(obj: dict[str, Any] | None) -> list[tuple[str, Any]]:
    return sorted(obj.items()) if obj else []


class _Builder:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str, str]] = set()
        self.relations: list[Relationship] = []

    def add(self, from_id: str, relation: str, to_id: str, detail: str | None = None) -> None:
        key = (from_id, relation, to_id, detail or "")
        if key in self._seen:
            return
        self._seen.add(key)
        self.relations.append(Relationship(from_id, relation, to_id, detail))

    def add_list(self, from_id: str, relation: str, values: list[str]) -> None:
        for to_id in values:
            self.add(from_id, relation, to_id)


def _register_validation(builder: _Builder, value: Any, fallback_id: str, owner_id: str) -> None:
    if not _is_object(value):
        return
    validation_id = value.get("id") if isinstance(value.get("id"), str) else fallback_id
    builder.add(owner_id, "validated_by", validation_id)
    builder.add_list(validation_id, "checks_resource", _strings_at(value, "resources"))
    builder.add_list(validation_id, "checks_capability", _strings_at(value, "capabilities"))
    builder.add_list(validation_id, "checks_goal", _strings_at(value, "goals"))


def _register_validations_field(builder: _Builder, container: Any, prefix: str, owner_id: str) -> None:
    if isinstance(container, list):
        for position, value in enumerate(container):
            _register_validation(builder, value, f"{prefix}.{position + 1}", owner_id)
    elif isinstance(container, dict):
        for name, value in _sorted_items(container):
            _register_validation(builder, value, f"{prefix}.{name}", owner_id)


def _register_resource(
    builder: _Builder, resource_id: str, declaration: dict[str, Any], parent: str | None
) -> None:
    if parent:
        builder.add(parent, "contains", resource_id)
    if isinstance(declaration.get("layer"), str):
        builder.add(resource_id, "belongs_to_layer", f"layer.{declaration['layer']}")
    if isinstance(declaration.get("implements"), str):
        builder.add(resource_id, "implements", declaration["implements"])
    if isinstance(declaration.get("of"), str):
        builder.add(resource_id, "of", declaration["of"])
    for relation in ("uses", "consumes", "publishes", "targets"):
        builder.add_list(resource_id, relation, _strings_at(declaration, relation))

    if resource_id.startswith("asset.") and isinstance(declaration.get("kind"), str):
        builder.add(resource_id, "uses", f"assetKind.{declaration['kind']}")

    contributions = declaration.get("contributesTo")
    if isinstance(contributions, list):
        for contribution in contributions:
            if not _is_object(contribution) or not isinstance(contribution.get("capability"), str):
                continue
            detail = contribution.get("contribution")
            builder.add(
                resource_id,
                "contributes_to",
                contribution["capability"],
                detail if isinstance(detail, str) else None,
            )

    _register_validations_field(
        builder, declaration.get("validations"), f"validation.local.{resource_id}", resource_id
    )


def _register_intent(builder: _Builder, project: dict[str, Any], project_id: str) -> None:
    for name, actor in _sorted_items(_object_at(project, "actors")):
        if _is_object(actor):
            builder.add(project_id, "defines", f"actor.{name}")
    for name, goal in _sorted_items(_object_at(project, "goals")):
        if not _is_object(goal):
            continue
        goal_id = f"goal.{name}"
        builder.add(project_id, "defines", goal_id)
        builder.add_list(goal_id, "serves_actor", _strings_at(goal, "actors"))
        builder.add_list(goal_id, "depends_on", _strings_at(goal, "dependsOn"))
        builder.add_list(goal_id, "requires_capability", _strings_at(goal, "capabilities"))
        builder.add_list(goal_id, "constrained_by", _strings_at(goal, "requirements"))
    for name, capability in _sorted_items(_object_at(project, "capabilities")):
        if not _is_object(capability):
            continue
        capability_id = f"capability.{name}"
        builder.add(project_id, "defines", capability_id)
        builder.add_list(capability_id, "supports_goal", _strings_at(capability, "goals"))
        for scenario_name, scenario in _sorted_items(_object_at(capability, "acceptance")):
            if not _is_object(scenario):
                continue
            scenario_id = f"acceptance.{name}.{scenario_name}"
            builder.add(capability_id, "accepted_by", scenario_id)
            if isinstance(scenario.get("actor"), str):
                builder.add(scenario_id, "performed_by", scenario["actor"])
            builder.add_list(scenario_id, "requires_evidence", _strings_at(scenario, "evidence"))
    for name, requirement in _sorted_items(_object_at(project, "requirements")):
        if not _is_object(requirement):
            continue
        requirement_id = f"requirement.{name}"
        builder.add(project_id, "defines", requirement_id)
        builder.add_list(requirement_id, "constrains_goal", _strings_at(requirement, "goals"))
        builder.add_list(
            requirement_id, "constrains_capability", _strings_at(requirement, "capabilities")
        )
    for name, evidence in _sorted_items(_object_at(project, "evidence")):
        if not _is_object(evidence):
            continue
        evidence_id = f"evidence.{name}"
        builder.add(project_id, "defines", evidence_id)
        builder.add_list(evidence_id, "proven_by", _strings_at(evidence, "validations"))
        builder.add_list(evidence_id, "witnessed_by", _strings_at(evidence, "witnesses"))

    completion = _object_at(project, "completion")
    if completion:
        builder.add_list(project_id, "completion_requires", _strings_at(completion, "requiredGoals"))
        builder.add_list(project_id, "completion_checks", _strings_at(completion, "projectChecks"))


def _register_contexts(builder: _Builder, project: dict[str, Any], project_id: str) -> None:
    nested_sections = (
        ("valueObjects", "valueObject"),
        ("repositories", "repository"),
        ("ports", "port"),
        ("domainServices", "domainService"),
        ("applicationServices", "applicationService"),
        ("assets", "asset"),
    )
    for context_name, context in _sorted_items(_object_at(project, "contexts")):
        if not _is_object(context):
            continue
        context_id = f"context.{context_name}"
        _register_resource(builder, context_id, context, project_id)
        for section, kind in nested_sections:
            for name, value in _sorted_items(_object_at(context, section)):
                if _is_object(value):
                    _register_resource(builder, f"{kind}.{context_name}.{name}", value, context_id)
        for aggregate_name, aggregate in _sorted_items(_object_at(context, "aggregates")):
            if not _is_object(aggregate):
                continue
            aggregate_id = f"aggregate.{context_name}.{aggregate_name}"
            _register_resource(builder, aggregate_id, aggregate, context_id)
            for section, kind in (
                ("entities", "entity"),
                ("valueObjects", "valueObject"),
                ("assets", "asset"),
            ):
                for name, value in _sorted_items(_object_at(aggregate, section)):
                    if _is_object(value):
                        _register_resource(
                            builder,
                            f"{kind}.{context_name}.{aggregate_name}.{name}",
                            value,
                            aggregate_id,
                        )


def _register_context_map(builder: _Builder, project: dict[str, Any]) -> None:
    context_map = project.get("contextMap")
    entries = (
        context_map
        if isinstance(context_map, list)
        else list(context_map.values())
        if isinstance(context_map, dict)
        else []
    )
    for relationship in entries:
        if (
            not _is_object(relationship)
            or not isinstance(relationship.get("from"), str)
            or not isinstance(relationship.get("to"), str)
        ):
            continue
        kind = relationship.get("kind") if isinstance(relationship.get("kind"), str) else "related"
        direction = relationship.get("direction")
        builder.add(
            f"context.{relationship['from']}",
            f"context_map:{kind}",
            f"context.{relationship['to']}",
            direction if isinstance(direction, str) else None,
        )


def _register_witnesses(builder: _Builder, project: dict[str, Any], project_id: str) -> None:
    for name, witness in _sorted_items(_object_at(project, "witnesses")):
        if not _is_object(witness):
            continue
        witness_id = f"witness.{name}"
        builder.add(project_id, "defines", witness_id)
        if isinstance(witness.get("goal"), str):
            builder.add(witness_id, "proves_goal", witness["goal"])
        if isinstance(witness.get("capability"), str):
            builder.add(witness_id, "proves_capability", witness["capability"])
        builder.add_list(witness_id, "observes", _strings_at(witness, "resources"))
        builder.add_list(witness_id, "may_repair", _strings_at(witness, "repairResources"))
        builder.add_list(
            witness_id,
            "counterexample_owned_by",
            _strings_at(witness, "counterexampleRepairResources"),
        )
        builder.add_list(witness_id, "produces_evidence", _strings_at(witness, "evidence"))
        builder.add_list(witness_id, "produces_artifact", _strings_at(witness, "artifacts"))


def build_relationships(project: dict[str, Any]) -> list[Relationship]:
    builder = _Builder()
    project_name = project.get("name") if isinstance(project.get("name"), str) else "project"
    project_id = f"project.{project_name}"

    _register_intent(builder, project, project_id)

    for layer, rule in _sorted_items(_object_at(project, "layerRules")):
        if _is_object(rule):
            builder.add_list(
                f"layer.{layer}",
                "may_depend_on",
                [f"layer.{name}" for name in _strings_at(rule, "dependsOn")],
            )

    for name, kind_value in _sorted_items(_object_at(project, "assetKinds")):
        if _is_object(kind_value):
            _register_resource(builder, f"assetKind.{name}", kind_value, project_id)

    _register_contexts(builder, project, project_id)

    for name, adapter in _sorted_items(_object_at(project, "adapters")):
        if _is_object(adapter):
            _register_resource(builder, f"adapter.{name}", adapter, project_id)
    for name, asset in _sorted_items(_object_at(project, "assets")):
        if _is_object(asset):
            _register_resource(builder, f"asset.{name}", asset, project_id)

    _register_context_map(builder, project)
    _register_validations_field(builder, project.get("validations"), "validation", project_id)
    _register_witnesses(builder, project, project_id)

    return sorted(
        builder.relations,
        key=lambda r: (r.from_id, r.relation, r.to_id, r.detail or ""),
    )
