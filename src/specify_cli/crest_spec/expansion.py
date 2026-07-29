"""Expansion of the terse spec tree into the canonical ``project`` mapping.

The canonical shape is the one the CrestOpenSpec CUE bridge emitted (nested
contexts, full canonical IDs, attached validations nested under their owning
resources, pipe-joined union type expressions). The golden test asserts this
expansion is deep-equal to the checked-in bridge output for the crest-synth
spec, so every downstream consumer ports against an unchanged data model.
"""

from __future__ import annotations

from typing import Any

from .diagnostics import CrestSpecDiagnostic
from .identifiers import (
    CONTEXT_RESOURCE_KINDS,
    GENERIC_REFERENCE_FIELDS,
    TYPED_REFERENCE_FIELDS,
    IdentifierIndex,
    ReferenceResolver,
)

_TOP_LEVEL_SECTIONS: dict[str, str] = {
    "actors.yaml": "actors",
    "goals.yaml": "goals",
    "requirements.yaml": "requirements",
    "adapters.yaml": "adapters",
    "proof/witnesses.yaml": "witnesses",
    "proof/evidence.yaml": "evidence",
}
_SECTION_ID_PREFIX: dict[str, str] = {
    "actors": "actor.",
    "goals": "goal.",
    "requirements": "requirement.",
    "adapters": "adapter.",
    "witnesses": "witness.",
    "evidence": "evidence.",
}
_KNOWN_FILES = frozenset(_TOP_LEVEL_SECTIONS) | {
    "project.yaml",
    "capabilities.yaml",
    "assets.yaml",
    "proof/validations.yaml",
    "proof/invariants.yaml",
}


def _malformed(diags: list[CrestSpecDiagnostic], file: str, message: str) -> None:
    diags.append(
        CrestSpecDiagnostic("crest_spec_malformed_section", message, file=file)
    )


def _section_map(doc: Any, key: str, file: str, diags: list[CrestSpecDiagnostic]) -> dict[str, Any]:
    value = doc.get(key) if isinstance(doc, dict) else None
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return value
    _malformed(diags, file, f"section {key!r} must be a mapping of names to declarations")
    return {}


class _Declarations:
    """First pass: declare every canonical ID so references can resolve."""

    def __init__(self, diags: list[CrestSpecDiagnostic]):
        self.index = IdentifierIndex()
        self._diags = diags

    def declare(self, canonical_id: str, file: str) -> None:
        if not self.index.declare(canonical_id):
            self._diags.append(
                CrestSpecDiagnostic(
                    "crest_spec_duplicate_id",
                    f"{canonical_id} is declared more than once",
                    file=file,
                )
            )

    def collect_section_file(self, rel: str, doc: Any) -> None:
        section = _TOP_LEVEL_SECTIONS[rel]
        for name in _section_map(doc, section, rel, self._diags):
            self.declare(_SECTION_ID_PREFIX[section] + name, rel)

    def collect_capabilities(self, rel: str, doc: Any) -> None:
        for name, body in _section_map(doc, "capabilities", rel, self._diags).items():
            self.declare(f"capability.{name}", rel)
            if isinstance(body, dict):
                for scenario in body.get("acceptance", {}) or {}:
                    self.declare(f"acceptance.{name}.{scenario}", rel)

    def collect_assets(self, rel: str, doc: Any) -> None:
        for name in _section_map(doc, "assetKinds", rel, self._diags):
            self.declare(f"assetKind.{name}", rel)
        for name in _section_map(doc, "assets", rel, self._diags):
            self.declare(f"asset.{name}", rel)

    def collect_validations(self, rel: str, doc: Any) -> None:
        for key in ("projectValidations", "attachedValidations"):
            for name in _section_map(doc, key, rel, self._diags):
                self.declare(f"validation.{name}", rel)

    def collect_context(self, rel: str, doc: Any) -> None:
        context_name = doc.get("context") if isinstance(doc, dict) else None
        if not isinstance(context_name, str) or not context_name:
            _malformed(self._diags, rel, "context files require a top-level `context: <Name>`")
            return
        self.declare(f"context.{context_name}", rel)
        for section, kind in CONTEXT_RESOURCE_KINDS.items():
            if section in doc:
                for name in _section_map(doc, section, rel, self._diags):
                    self.declare(f"{kind}.{context_name}.{name}", rel)


def collect_identifiers(
    files: dict[str, Any], diags: list[CrestSpecDiagnostic]
) -> IdentifierIndex:
    declarations = _Declarations(diags)
    def _collect_non_goals(rel: str, doc: Any) -> None:
        for name in _section_map(doc, "nonGoals", rel, diags):
            declarations.declare(f"nonGoal.{name}", rel)

    collectors = {
        "project.yaml": _collect_non_goals,
        "capabilities.yaml": declarations.collect_capabilities,
        "assets.yaml": declarations.collect_assets,
        "proof/validations.yaml": declarations.collect_validations,
    }
    for rel, doc in files.items():
        if rel in _TOP_LEVEL_SECTIONS:
            declarations.collect_section_file(rel, doc)
        elif rel in collectors:
            collectors[rel](rel, doc)
        elif rel.startswith("contexts/"):
            declarations.collect_context(rel, doc)
    return declarations.index


def _join_union(value: Any) -> Any:
    if isinstance(value, list) and value and all(isinstance(p, str) for p in value):
        return " | ".join(value)
    return value


class _Expander:
    """Second pass: rewrite references and re-nest into the canonical shape."""

    def __init__(self, index: IdentifierIndex, file: str):
        self.resolver = ReferenceResolver(index)
        self.file = file

    def _ref(self, value: Any, kind: str | None, *, required: bool) -> Any:
        if isinstance(value, str):
            return self.resolver.resolve(value, kind, file=self.file, required=required)
        if isinstance(value, list):
            return [self._ref(v, kind, required=required) for v in value]
        return value

    def _contributes(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return [
            {
                "capability": self.resolver.resolve(
                    ref, "capability", file=self.file, required=True
                ),
                "contribution": contribution,
            }
            for ref, contribution in value.items()
        ]

    def walk(self, node: Any) -> Any:
        if isinstance(node, list):
            return [self.walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "contributesTo":
                out[key] = self._contributes(value)
            elif key in TYPED_REFERENCE_FIELDS:
                out[key] = self._ref(value, TYPED_REFERENCE_FIELDS[key], required=True)
            elif key in GENERIC_REFERENCE_FIELDS:
                out[key] = self._ref(value, None, required=False)
            elif key == "validations" and isinstance(value, list) and all(
                isinstance(v, str) for v in value
            ):
                out[key] = self._ref(value, "validation", required=True)
            elif key == "state" and isinstance(value, dict):
                out[key] = {state_key: _join_union(sv) for state_key, sv in value.items()}
            elif key == "from":
                out[key] = _join_union(value)
            else:
                out[key] = self.walk(value)
        return out


def _expand_section(
    files: dict[str, Any],
    rel: str,
    section: str,
    index: IdentifierIndex,
    diags: list[CrestSpecDiagnostic],
) -> dict[str, Any]:
    doc = files.get(rel)
    if doc is None:
        return {}
    expander = _Expander(index, rel)
    result = {
        name: expander.walk(body)
        for name, body in _section_map(doc, section, rel, diags).items()
    }
    diags.extend(expander.resolver.diagnostics)
    return result


def _expand_contexts(
    files: dict[str, Any], index: IdentifierIndex, diags: list[CrestSpecDiagnostic]
) -> dict[str, Any]:
    contexts: dict[str, Any] = {}
    for rel in sorted(files):
        if not rel.startswith("contexts/"):
            continue
        doc = files[rel]
        if not isinstance(doc, dict) or not isinstance(doc.get("context"), str):
            continue  # already diagnosed during identifier collection
        expander = _Expander(index, rel)
        context: dict[str, Any] = {
            key: expander.walk(value)
            for key, value in doc.items()
            if key != "context" and key not in CONTEXT_RESOURCE_KINDS
        }
        for section in CONTEXT_RESOURCE_KINDS:
            if section in doc:
                context[section] = {
                    name: expander.walk(body)
                    for name, body in _section_map(doc, section, rel, diags).items()
                }
        diags.extend(expander.resolver.diagnostics)
        contexts[doc["context"]] = context
    return contexts


def _expand_validations(
    files: dict[str, Any],
    project: dict[str, Any],
    index: IdentifierIndex,
    diags: list[CrestSpecDiagnostic],
) -> None:
    rel = "proof/validations.yaml"
    doc = files.get(rel)
    if doc is None:
        return
    expander = _Expander(index, rel)
    defaults = doc.get("defaults") or {}
    if not isinstance(defaults, dict):
        _malformed(diags, rel, "`defaults` must be a mapping")
        defaults = {}

    project_validations: dict[str, Any] = {}
    for name, body in _section_map(doc, "projectValidations", rel, diags).items():
        entry = {"id": f"validation.{name}", **expander.walk(body)}
        for default_key, default_value in defaults.items():
            entry.setdefault(default_key, default_value)
        project_validations[name] = entry
    project["validations"] = project_validations

    for name, body in _section_map(doc, "attachedValidations", rel, diags).items():
        if not isinstance(body, dict) or not isinstance(body.get("attachedTo"), str):
            _malformed(diags, rel, f"attached validation {name!r} requires `attachedTo`")
            continue
        owner_id = expander.resolver.resolve(
            body["attachedTo"], None, file=rel, required=True
        )
        entry = {
            "id": f"validation.{name}",
            **expander.walk({k: v for k, v in body.items() if k != "attachedTo"}),
        }
        owner = _locate_owner(project, owner_id)
        if owner is None:
            diags.append(
                CrestSpecDiagnostic(
                    "crest_spec_unresolved_reference",
                    f"attached validation {name!r} names owner {owner_id!r} "
                    "which is not a declared resource",
                    file=rel,
                )
            )
            continue
        owner.setdefault("validations", []).append(entry)
    diags.extend(expander.resolver.diagnostics)


def _locate_owner(project: dict[str, Any], owner_id: str) -> dict[str, Any] | None:
    parts = owner_id.split(".")
    kind = parts[0]
    if kind == "adapter" and len(parts) == 2:
        owner = project.get("adapters", {}).get(parts[1])
        return owner if isinstance(owner, dict) else None
    if kind == "asset" and len(parts) == 2:
        owner = project.get("assets", {}).get(parts[1])
        return owner if isinstance(owner, dict) else None
    plural = {v: k for k, v in CONTEXT_RESOURCE_KINDS.items()}.get(kind)
    if plural and len(parts) == 3:
        owner = project.get("contexts", {}).get(parts[1], {}).get(plural, {}).get(parts[2])
        return owner if isinstance(owner, dict) else None
    return None


def _expand_capabilities(
    files: dict[str, Any], index: IdentifierIndex, diags: list[CrestSpecDiagnostic]
) -> dict[str, Any]:
    rel = "capabilities.yaml"
    doc = files.get(rel)
    if doc is None:
        return {}
    expander = _Expander(index, rel)
    capabilities: dict[str, Any] = {}
    for name, body in _section_map(doc, "capabilities", rel, diags).items():
        if not isinstance(body, dict):
            _malformed(diags, rel, f"capability {name!r} must be a mapping")
            continue
        entry = expander.walk({k: v for k, v in body.items() if k != "acceptance"})
        if "acceptance" in body:
            entry["acceptance"] = {
                scenario: expander.walk(scenario_body)
                for scenario, scenario_body in (body["acceptance"] or {}).items()
            }
        capabilities[name] = entry
    diags.extend(expander.resolver.diagnostics)
    return capabilities


def _expand_project_file(
    files: dict[str, Any],
    project: dict[str, Any],
    index: IdentifierIndex,
    diags: list[CrestSpecDiagnostic],
) -> None:
    rel = "project.yaml"
    doc = files.get(rel)
    if not isinstance(doc, dict):
        _malformed(diags, rel, "project.yaml is required and must be a mapping")
        return
    expander = _Expander(index, rel)
    for key, value in doc.items():
        if key == "nonGoals":
            project[key] = dict(_section_map(doc, key, rel, diags))
        elif key == "completion":
            project[key] = expander.walk(value)
        else:
            project[key] = value
    diags.extend(expander.resolver.diagnostics)


def _expand_invariants(
    files: dict[str, Any], diags: list[CrestSpecDiagnostic]
) -> dict[str, Any]:
    rel = "proof/invariants.yaml"
    doc = files.get(rel)
    if doc is None:
        return {}
    groups = doc.get("invariantGroups") if isinstance(doc, dict) else None
    if not isinstance(groups, list):
        _malformed(diags, rel, "`invariantGroups` must be a list of {group, invariants}")
        return {}
    result: dict[str, Any] = {}
    for group in groups:
        if not isinstance(group, dict) or "group" not in group:
            _malformed(diags, rel, "each invariant group requires `group` and `invariants`")
            continue
        result[group["group"]] = group.get("invariants", [])
    return result


def expand_project(
    files: dict[str, Any], diags: list[CrestSpecDiagnostic]
) -> dict[str, Any]:
    """Expand parsed terse files into the canonical ``project`` mapping."""
    for rel in files:
        if rel not in _KNOWN_FILES and not rel.startswith("contexts/"):
            diags.append(
                CrestSpecDiagnostic(
                    "crest_spec_unknown_file",
                    f"{rel} is not a recognized crest-spec file",
                    file=rel,
                )
            )

    index = collect_identifiers(files, diags)
    project: dict[str, Any] = {}
    _expand_project_file(files, project, index, diags)
    for rel, section in _TOP_LEVEL_SECTIONS.items():
        project[section] = _expand_section(files, rel, section, index, diags)
    project["capabilities"] = _expand_capabilities(files, index, diags)
    project["contexts"] = _expand_contexts(files, index, diags)
    project["assetKinds"] = _expand_section(files, "assets.yaml", "assetKinds", index, diags)
    project["assets"] = _expand_section(files, "assets.yaml", "assets", index, diags)
    project["invariants"] = _expand_invariants(files, diags)
    _expand_validations(files, project, index, diags)
    return project
