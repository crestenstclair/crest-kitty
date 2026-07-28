"""Validation-inventory resolution: evaluated architecture -> executable checks.

Faithful port of the non-runtime half of CrestOpenSpec's
``validation-inventory.ts`` (reference copy in ``research/crestopenspec-port``).
Every rule fails closed with the upstream diagnostic codes, before anything is
executed:

- The gate is armed iff ``completion.projectChecks`` is present (even ``[]``)
  or any attached validation carries a ``proof`` field. Otherwise the project
  has not opted in and the inventory reports ``declared: False``.
- Each project-check ID must resolve to exactly one top-level project
  validation with ``scope: "project"``.
- Only proof-bearing attached validations are binding; they require
  ``scope: "attached"`` and explicit applicability (``{mode: always}`` or
  ``{mode: changes, changes: [...]}`` — the listed IDs are mission slugs).
- Every executable declaration needs an argv ``command``, a
  ``workingDirectory`` canonicalizing inside the project root, and positive
  bounded ``limits``.
- Runtime-session proofs are fully parsed here (port of
  ``parseRuntimeSessionProof`` and helpers): entry point, boundary,
  environment, lifecycle, stdio mode, success condition, termination owner,
  the six timeout budgets, progress/completion markers, resources,
  interactions, teardown, and required capabilities all fail closed with the
  upstream diagnostic codes before anything executes. The parsed proof stays
  a plain JSON-shaped dict so downstream reports serialize unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import (
    ACCEPTANCE_PROOF_ROLES,
    AcceptanceDiagnostic,
    AcceptanceScope,
    ProcessLimits,
    ResolvedValidation,
    ValidationApplicability,
    ValidationDeclarationRef,
    ValidationInventory,
)

MAX_ACCEPTANCE_TIMEOUT_MS = 30 * 60 * 1000
MAX_ACCEPTANCE_STREAM_BYTES = 16 * 1024 * 1024

RUNTIME_BOUNDARIES = frozenset(
    {
        "external-process",
        "production-composition",
        "native-ui",
        "physical-device",
        "network-service",
        "background-worker",
        "callback-runtime",
    }
)

RUNTIME_ENVIRONMENTS = frozenset({"synthetic", "physical", "native", "production"})

RUNTIME_LIFECYCLES = frozenset({"bounded", "interactive-persistent", "service-persistent", "background-owned"})

RUNTIME_TIMEOUT_FIELDS = (
    "startupTimeoutMs",
    "progressSilenceMs",
    "completionTimeoutMs",
    "completionToExitGraceMs",
    "teardownGraceMs",
    "hardTimeoutMs",
)


def _error(code: str, message: str, location: str) -> AcceptanceDiagnostic:
    return AcceptanceDiagnostic(code=code, message=message, path=location)


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _is_safe_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass
class _Candidate:
    value: Any
    location: str
    owner: str
    source: str  # "project" | "attached"

    @property
    def id(self) -> str | None:
        if _is_object(self.value):
            declared = self.value.get("id")
            if isinstance(declared, str) and declared.strip():
                return declared
        return None


@dataclass
class _Collected:
    project: list[_Candidate]
    attached: list[_Candidate]
    references: list[tuple[str, str]]  # (id, location)
    malformed: list[AcceptanceDiagnostic]


def _collect_container(value: Any, location: str, owner: str, source: str, out: _Collected) -> None:
    target = out.project if source == "project" else out.attached
    if isinstance(value, list):
        entries: list[tuple[str, Any]] = [(f"{location}[{i}]", entry) for i, entry in enumerate(value)]
    elif _is_object(value):
        entries = [(f"{location}.{name}", value[name]) for name in sorted(value)]
    else:
        out.malformed.append(
            _error("validation_attachment_malformed", "A 'validations' field must be an array or object.", location)
        )
        return
    for entry_location, entry in entries:
        if isinstance(entry, str):
            out.references.append((entry, entry_location))
        elif _is_object(entry):
            target.append(_Candidate(entry, entry_location, owner, source))
        else:
            out.malformed.append(
                _error(
                    "validation_attachment_malformed",
                    "Validation attachments must contain declaration objects or string identity references.",
                    entry_location,
                )
            )


def _collect_architecture_validations(project: dict[str, Any]) -> _Collected:
    out = _Collected(project=[], attached=[], references=[], malformed=[])
    name = project.get("name")
    project_owner = f"project.{name}" if isinstance(name, str) and name.strip() else "project"
    if "validations" in project:
        _collect_container(project["validations"], "project.validations", project_owner, "project", out)

    def walk(value: Any, location: str) -> None:
        if isinstance(value, list):
            for index, entry in enumerate(value):
                walk(entry, f"{location}[{index}]")
            return
        if not _is_object(value):
            return
        for key in sorted(value):
            if location == "project" and key == "validations":
                continue
            child_location = f"{location}.{key}"
            if key == "validations":
                _collect_container(value[key], child_location, location, "attached", out)
            else:
                walk(value[key], child_location)

    walk(project, "project")
    return out


def _parse_project_check_references(
    project: dict[str, Any], diagnostics: list[AcceptanceDiagnostic]
) -> tuple[bool, list[tuple[str, str]]]:
    completion = project.get("completion")
    if completion is None and "completion" not in project:
        return False, []
    if not _is_object(completion):
        diagnostics.append(
            _error("project_completion_malformed", "Evaluated project 'completion' must be an object.", "project.completion")
        )
        return True, []
    if "projectChecks" not in completion:
        return False, []
    raw = completion["projectChecks"]
    if not isinstance(raw, list):
        diagnostics.append(
            _error(
                "project_checks_malformed",
                "Evaluated 'completion.projectChecks' must be an array of non-empty validation IDs.",
                "project.completion.projectChecks",
            )
        )
        return True, []
    references: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        location = f"project.completion.projectChecks[{index}]"
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                _error("project_check_reference_malformed", "Every project-check reference must be a non-empty string.", location)
            )
            continue
        if value in seen:
            diagnostics.append(
                _error(
                    "project_check_reference_duplicate",
                    f"Project-check reference '{value}' is declared more than once.",
                    location,
                )
            )
            continue
        seen.add(value)
        references.append((value, location))
    return True, references


def _validate_global_identity(
    candidates: list[_Candidate],
    references: list[tuple[str, str]],
    diagnostics: list[AcceptanceDiagnostic],
) -> None:
    by_id: dict[str, list[_Candidate]] = {}
    for entry in candidates:
        if not entry.id:
            diagnostics.append(
                _error(
                    "validation_identity_missing",
                    "Every validation declaration in an acceptance-governed project must have a non-empty string id.",
                    f"{entry.location}.id",
                )
            )
            continue
        by_id.setdefault(entry.id, []).append(entry)

    for validation_id in sorted(by_id):
        matches = by_id[validation_id]
        if len(matches) > 1:
            owners = "; ".join(f"{m.owner} at {m.location}" for m in matches)
            diagnostics.append(
                _error(
                    "validation_identity_ambiguous_owner",
                    f"Validation identity '{validation_id}' is declared by multiple owners: {owners}.",
                    matches[0].location,
                )
            )

    for reference_id, location in references:
        matches = by_id.get(reference_id, [])
        if not matches:
            diagnostics.append(
                _error(
                    "validation_evidence_reference_orphaned",
                    f"Validation reference '{reference_id}' does not resolve to a declaration.",
                    location,
                )
            )
        elif len(matches) > 1:
            diagnostics.append(
                _error(
                    "validation_evidence_reference_ambiguous",
                    f"Validation reference '{reference_id}' resolves to multiple declaration owners.",
                    location,
                )
            )


def _parse_attached_applicability(
    entry: _Candidate, scope: AcceptanceScope, diagnostics: list[AcceptanceDiagnostic]
) -> bool | None:
    if not _is_object(entry.value):
        return None
    value = entry.value.get("applicability")
    location = f"{entry.location}.applicability"
    if not _is_object(value):
        diagnostics.append(
            _error(
                "validation_applicability_missing",
                "Attached proof-bearing validation requires explicit applicability metadata.",
                location,
            )
        )
        return None
    if value.get("mode") == "always":
        return True
    if value.get("mode") != "changes":
        diagnostics.append(
            _error(
                "validation_applicability_malformed",
                "Attached proof applicability mode must be 'always' or 'changes'.",
                f"{location}.mode",
            )
        )
        return None
    changes = value.get("changes")
    if (
        not isinstance(changes, list)
        or not changes
        or not all(isinstance(c, str) and c.strip() for c in changes)
        or len(set(changes)) != len(changes)
    ):
        diagnostics.append(
            _error(
                "validation_applicability_malformed",
                "Change applicability requires a non-empty, unique array of change IDs.",
                f"{location}.changes",
            )
        )
        return None
    return scope.mode == "project" or bool(scope.mission and scope.mission in changes)


def _parse_limits(value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]) -> ProcessLimits | None:
    if not _is_object(value):
        diagnostics.append(
            _error(
                "validation_limits_malformed",
                "Validation limits must be an object with timeoutMs, stdoutBytes, and stderrBytes.",
                location,
            )
        )
        return None
    bounds = (
        ("timeoutMs", MAX_ACCEPTANCE_TIMEOUT_MS),
        ("stdoutBytes", MAX_ACCEPTANCE_STREAM_BYTES),
        ("stderrBytes", MAX_ACCEPTANCE_STREAM_BYTES),
    )
    valid = True
    for field_name, maximum in bounds:
        field_value = value.get(field_name)
        if not isinstance(field_value, int) or isinstance(field_value, bool) or not (1 <= field_value <= maximum):
            valid = False
            diagnostics.append(
                _error(
                    "validation_limits_malformed",
                    f"'{field_name}' must be an integer from 1 through {maximum}.",
                    f"{location}.{field_name}",
                )
            )
    if not valid:
        return None
    return ProcessLimits(
        timeout_ms=value["timeoutMs"], stdout_bytes=value["stdoutBytes"], stderr_bytes=value["stderrBytes"]
    )


def _canonical_working_directory(
    project_root: str, value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            _error(
                "validation_working_directory_malformed",
                "Validation 'workingDirectory' must be a non-empty path string.",
                location,
            )
        )
        return None
    canonical_root = Path(project_root).resolve()
    candidate_path = (canonical_root / value).resolve()
    if not candidate_path.is_dir():
        diagnostics.append(
            _error(
                "validation_working_directory_unavailable",
                f"Validation working directory is unavailable: {candidate_path}",
                location,
            )
        )
        return None
    try:
        candidate_path.relative_to(canonical_root)
    except ValueError:
        diagnostics.append(
            _error(
                "validation_working_directory_outside_root",
                f"Validation working directory resolves outside the canonical project root: {candidate_path}",
                location,
            )
        )
        return None
    return str(candidate_path)


def _parse_assertions(
    value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]
) -> tuple[dict[str, Any], ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        diagnostics.append(
            _error("validation_assertions_malformed", "Validation 'assertions' must be an array when present.", location)
        )
        return None
    assertions: list[dict[str, Any]] = []
    for index, entry in enumerate(value):
        entry_type = entry.get("type") if _is_object(entry) else None
        if not isinstance(entry_type, str) or not entry_type.strip():
            diagnostics.append(
                _error(
                    "validation_assertions_malformed",
                    "Every assertion must be an object with a non-empty string type.",
                    f"{location}[{index}]",
                )
            )
        else:
            assertions.append(entry)
    return tuple(assertions)


def _parse_test_suite_proof(
    value: dict[str, Any], location: str, diagnostics: list[AcceptanceDiagnostic]
) -> dict[str, Any] | None:
    provider = value.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        diagnostics.append(
            _error("validation_proof_malformed", "Test-suite proof requires a non-empty 'provider'.", f"{location}.provider")
        )
        return None
    role = value.get("role")
    if role is not None:
        if not isinstance(role, str) or role not in ACCEPTANCE_PROOF_ROLES:
            diagnostics.append(
                _error("validation_proof_malformed", "Test-suite proof 'role' is not a supported proof role.", f"{location}.role")
            )
            return None
        if role != "in-process-behavior":
            diagnostics.append(
                _error(
                    "validation_proof_role_mismatch",
                    f"A test-suite proof cannot satisfy the '{role}' role; declare an in-process behavior role or use a "
                    "runtime-session proof for an external runtime claim.",
                    f"{location}.role",
                )
            )
            return None
    if "selector" not in value or value.get("selector") is None:
        diagnostics.append(
            _error("validation_selector_missing", "Test-suite proof requires an explicit opaque selector.", f"{location}.selector")
        )
        return None
    minimum = value.get("minimumExecuted", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        diagnostics.append(
            _error(
                "validation_proof_malformed",
                "Test-suite 'minimumExecuted' must be an integer of at least one.",
                f"{location}.minimumExecuted",
            )
        )
        return None
    options = value.get("options", {})
    if not _is_object(options):
        diagnostics.append(
            _error("validation_proof_malformed", "Test-suite proof 'options' must be an object when present.", f"{location}.options")
        )
        return None
    proof: dict[str, Any] = {
        "type": "test-suite",
        "provider": provider,
        "minimumExecuted": minimum,
        "selector": value["selector"],
        "options": options,
    }
    if role:
        proof["role"] = role
    return proof


def _parse_runtime_timeouts(value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]) -> dict[str, int] | None:
    if not _is_object(value):
        diagnostics.append(_error("runtime_timeouts_malformed", "Runtime proof timeouts must declare every lifecycle budget.", location))
        return None
    valid = True
    for field_name in RUNTIME_TIMEOUT_FIELDS:
        field_value = value.get(field_name)
        if not _is_safe_int(field_value) or not (1 <= field_value <= MAX_ACCEPTANCE_TIMEOUT_MS):
            diagnostics.append(
                _error(
                    "runtime_timeouts_malformed",
                    f"'{field_name}' must be an integer from 1 through {MAX_ACCEPTANCE_TIMEOUT_MS}.",
                    f"{location}.{field_name}",
                )
            )
            valid = False
    if not valid:
        return None
    timeouts = {field_name: value[field_name] for field_name in RUNTIME_TIMEOUT_FIELDS}
    if (
        timeouts["startupTimeoutMs"] > timeouts["completionTimeoutMs"]
        or timeouts["completionTimeoutMs"] > timeouts["hardTimeoutMs"]
        or timeouts["progressSilenceMs"] > timeouts["hardTimeoutMs"]
        or timeouts["completionToExitGraceMs"] > timeouts["hardTimeoutMs"]
        or timeouts["teardownGraceMs"] > timeouts["hardTimeoutMs"]
    ):
        diagnostics.append(
            _error("runtime_timeouts_incoherent", "Runtime timeout stages must fit within the completion and hard limits.", location)
        )
        return None
    return timeouts


def _valid_runtime_marker(entry: Any, count_field: str) -> bool:
    return bool(
        _is_object(entry)
        and _non_empty_str(entry.get("id"))
        and entry.get("stream") in ("stdout", "stderr")
        and isinstance(entry.get("contains"), str)
        and entry["contains"]
        and _is_safe_int(entry.get(count_field))
        and entry[count_field] >= 1
    )


def _parse_runtime_markers(
    value: Any, phase: str, location: str, diagnostics: list[AcceptanceDiagnostic]
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value:
        diagnostics.append(_error("runtime_markers_malformed", f"Runtime '{phase}' must be a non-empty marker array.", location))
        return None
    count_field = "minimumCount" if phase == "progress" else "exactCount"
    output: list[dict[str, Any]] = []
    for index, entry in enumerate(value):
        if not _valid_runtime_marker(entry, count_field):
            diagnostics.append(
                _error(
                    "runtime_markers_malformed",
                    f"Each {phase} marker requires a non-empty id and substring, a stdout/stderr stream, and a positive {count_field}.",
                    f"{location}[{index}]",
                )
            )
            continue
        output.append({"id": entry["id"], "stream": entry["stream"], "contains": entry["contains"], count_field: entry[count_field]})
    return output if len(output) == len(value) else None


def _valid_runtime_resource(entry: Any, seen: set[str]) -> bool:
    return bool(
        _is_object(entry)
        and _non_empty_str(entry.get("id"))
        and _non_empty_str(entry.get("type"))
        and entry.get("disposition") in ("release", "retain-during-readiness")
        and _non_empty_str(entry.get("owner"))
        and entry["id"] not in seen
    )


def _parse_runtime_resources(
    value: Any, location: str, lifecycle: str, diagnostics: list[AcceptanceDiagnostic]
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value:
        diagnostics.append(_error("runtime_resources_malformed", "Runtime proof resources must be a non-empty array.", location))
        return None
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(value):
        resource_location = f"{location}[{index}]"
        if not _valid_runtime_resource(entry, seen):
            diagnostics.append(
                _error(
                    "runtime_resources_malformed",
                    "Each runtime resource requires a unique id, type, owner, and supported disposition.",
                    resource_location,
                )
            )
            continue
        if lifecycle == "bounded" and entry["disposition"] != "release":
            diagnostics.append(
                _error(
                    "runtime_resource_lifecycle_mismatch",
                    "A bounded runtime cannot declare a resource retained after terminal success.",
                    f"{resource_location}.disposition",
                )
            )
            continue
        seen.add(entry["id"])
        resources.append(dict(entry))
    return resources if len(resources) == len(value) else None


def _valid_runtime_interaction(entry: Any, ids: set[str], marker_order: dict[str, int]) -> bool:
    if (
        not _is_object(entry)
        or not _non_empty_str(entry.get("id"))
        or entry["id"] in ids
        or not _non_empty_str(entry.get("provider"))
        or not isinstance(entry.get("opensAfter"), str)
        or entry["opensAfter"] not in marker_order
        or not isinstance(entry.get("closesBefore"), str)
        or entry["closesBefore"] not in marker_order
        or entry["opensAfter"] == entry["closesBefore"]
        or marker_order[entry["opensAfter"]] >= marker_order[entry["closesBefore"]]
        or not _is_object(entry.get("request"))
    ):
        return False
    required = entry.get("requiredAssertions")
    return bool(
        isinstance(required, list)
        and required
        and all(_non_empty_str(assertion) for assertion in required)
        and len(set(required)) == len(required)
    )


def _parse_runtime_interactions(
    value: Any, present: bool, location: str, marker_order: dict[str, int], diagnostics: list[AcceptanceDiagnostic]
) -> list[dict[str, Any]] | None:
    if not present:
        return []
    if not isinstance(value, list):
        diagnostics.append(_error("runtime_interactions_malformed", "Runtime 'interactions' must be an array.", location))
        return None
    interactions: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, entry in enumerate(value):
        if not _valid_runtime_interaction(entry, ids, marker_order):
            diagnostics.append(
                _error(
                    "runtime_interactions_malformed",
                    "Each interaction requires a unique id, provider, ordered opening/closing marker references, an object request, "
                    "and unique required assertion IDs.",
                    f"{location}[{index}]",
                )
            )
            continue
        ids.add(entry["id"])
        interactions.append(
            {
                "id": entry["id"],
                "provider": entry["provider"],
                "opensAfter": entry["opensAfter"],
                "closesBefore": entry["closesBefore"],
                "request": entry["request"],
                "requiredAssertions": list(entry["requiredAssertions"]),
            }
        )
    return interactions if len(interactions) == len(value) else None


def _parse_runtime_teardown(
    value: Any, present: bool, lifecycle: str, location: str, diagnostics: list[AcceptanceDiagnostic]
) -> tuple[bool, dict[str, Any] | None]:
    """Returns ``(ok, teardown)``; ``ok`` is False when the declaration is invalid."""
    if lifecycle == "bounded":
        if present:
            diagnostics.append(
                _error(
                    "runtime_lifecycle_teardown_mismatch",
                    "A bounded runtime must terminate itself and cannot declare controller teardown.",
                    location,
                )
            )
            return False, None
        return True, None
    if not _is_object(value) or not _non_empty_str(value.get("provider")) or not _is_object(value.get("request")):
        diagnostics.append(
            _error("runtime_teardown_missing", "A persistent or background runtime requires a provider-backed controller teardown.", location)
        )
        return False, None
    return True, {"provider": value["provider"], "request": value["request"]}


def _runtime_scalar_rules() -> list[tuple[str, Callable[[Any], bool], str, str]]:
    return [
        ("provider", _non_empty_str, "validation_proof_malformed", "Runtime-session proof requires a non-empty 'provider'."),
        (
            "role",
            lambda v: v in ("external-process-lifecycle", "production-composition-runtime"),
            "validation_proof_role_mismatch",
            "A runtime-session proof must use role 'external-process-lifecycle' or 'production-composition-runtime'; "
            "reachability, static, and in-process roles cannot satisfy a runtime claim.",
        ),
        ("entryPoint", _non_empty_str, "runtime_entry_point_malformed", "Runtime proof entryPoint must name the exact production entry point."),
        (
            "boundary",
            lambda v: isinstance(v, str) and v in RUNTIME_BOUNDARIES,
            "runtime_boundary_malformed",
            "Runtime proof boundary is unsupported.",
        ),
        (
            "environment",
            lambda v: isinstance(v, str) and v in RUNTIME_ENVIRONMENTS,
            "runtime_environment_malformed",
            "Runtime proof environment is unsupported.",
        ),
        (
            "lifecycle",
            lambda v: isinstance(v, str) and v in RUNTIME_LIFECYCLES,
            "runtime_lifecycle_malformed",
            "Runtime proof lifecycle is unsupported.",
        ),
        (
            "successCondition",
            _non_empty_str,
            "runtime_success_condition_malformed",
            "Runtime proof successCondition must identify the authoritative condition.",
        ),
        (
            "terminationOwner",
            _non_empty_str,
            "runtime_termination_owner_malformed",
            "Runtime proof terminationOwner must identify who owns termination.",
        ),
        ("stdioMode", lambda v: v in ("pipe", "pty"), "runtime_stdio_mode_malformed", "Runtime stdioMode must be 'pipe' or 'pty'."),
        ("requireExitCode", _is_safe_int, "runtime_exit_requirement_malformed", "Runtime requireExitCode must be an integer."),
        (
            "requireNoDescendants",
            lambda v: v is True,
            "runtime_descendant_requirement_malformed",
            "Runtime requireNoDescendants must be true so acceptance cannot leave an owned fixture process behind.",
        ),
    ]


def _validate_runtime_marker_identity(
    all_markers: list[dict[str, Any]], progress_count: int, location: str, diagnostics: list[AcceptanceDiagnostic]
) -> None:
    marker_ids: set[str] = set()
    marker_predicates: set[tuple[str, str]] = set()
    for index, marker in enumerate(all_markers):
        predicate = (marker["stream"], marker["contains"])
        if marker["id"] in marker_ids or predicate in marker_predicates:
            section = "progress" if index < progress_count else "completion"
            diagnostics.append(
                _error(
                    "runtime_marker_identity_ambiguous",
                    "Runtime marker IDs and stream/substring predicates must be unique within a session.",
                    f"{location}.{section}",
                )
            )
        marker_ids.add(marker["id"])
        marker_predicates.add(predicate)


def _parse_runtime_capabilities(value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]) -> list[str] | None:
    if isinstance(value, list) and all(_non_empty_str(capability) for capability in value) and len(set(value)) == len(value):
        return list(value)
    diagnostics.append(
        _error(
            "runtime_capabilities_malformed",
            "Runtime requiredCapabilities must be a unique string array, including an empty array when no extra capability is required.",
            f"{location}.requiredCapabilities",
        )
    )
    return None


def _parse_runtime_session_proof(
    value: dict[str, Any], location: str, diagnostics: list[AcceptanceDiagnostic]
) -> dict[str, Any] | None:
    before = len(diagnostics)
    for field_name, valid, code, message in _runtime_scalar_rules():
        if not valid(value.get(field_name)):
            diagnostics.append(_error(code, message, f"{location}.{field_name}"))

    lifecycle = value["lifecycle"] if isinstance(value.get("lifecycle"), str) and value["lifecycle"] in RUNTIME_LIFECYCLES else "bounded"
    timeouts = _parse_runtime_timeouts(value.get("timeouts"), f"{location}.timeouts", diagnostics)
    progress = _parse_runtime_markers(value.get("progress"), "progress", f"{location}.progress", diagnostics)
    completion = _parse_runtime_markers(value.get("completion"), "completion", f"{location}.completion", diagnostics)
    resources = _parse_runtime_resources(value.get("resources"), f"{location}.resources", lifecycle, diagnostics)

    all_markers = [*(progress or []), *(completion or [])]
    if value.get("stdioMode") == "pty" and any(marker["stream"] == "stderr" for marker in all_markers):
        diagnostics.append(
            _error(
                "runtime_pty_stream_mismatch",
                "PTY transport combines terminal output; PTY milestone declarations must observe stdout.",
                f"{location}.stdioMode",
            )
        )
    _validate_runtime_marker_identity(all_markers, len(progress or []), location, diagnostics)
    marker_order = {marker["id"]: index for index, marker in enumerate(all_markers)}
    interactions = _parse_runtime_interactions(
        value.get("interactions"), "interactions" in value, f"{location}.interactions", marker_order, diagnostics
    )
    teardown_ok, teardown = _parse_runtime_teardown(value.get("teardown"), "teardown" in value, lifecycle, f"{location}.teardown", diagnostics)
    required_capabilities = _parse_runtime_capabilities(value.get("requiredCapabilities"), location, diagnostics)

    parts = (timeouts, progress, completion, resources, interactions, required_capabilities)
    if len(diagnostics) != before or any(part is None for part in parts) or not teardown_ok:
        return None
    proof: dict[str, Any] = {
        "type": "runtime-session",
        "provider": value["provider"],
        "role": value["role"],
        "entryPoint": value["entryPoint"],
        "boundary": value["boundary"],
        "environment": value["environment"],
        "lifecycle": lifecycle,
        "successCondition": value["successCondition"],
        "terminationOwner": value["terminationOwner"],
        "resources": resources,
        "stdioMode": value["stdioMode"],
        "timeouts": timeouts,
        "progress": progress,
        "completion": completion,
        "requireExitCode": value["requireExitCode"],
        "requireNoDescendants": value["requireNoDescendants"],
        "requiredCapabilities": required_capabilities,
        "interactions": interactions,
    }
    if teardown:
        proof["teardown"] = teardown
    return proof


def _parse_proof(value: Any, location: str, diagnostics: list[AcceptanceDiagnostic]) -> dict[str, Any] | None | bool:
    """Returns the parsed proof dict, None when absent, or False when malformed."""
    if value is None:
        return None
    if not _is_object(value):
        diagnostics.append(
            _error(
                "validation_proof_malformed",
                "Validation proof must be an object with type 'test-suite' or 'runtime-session'.",
                location,
            )
        )
        return False
    proof_type = value.get("type")
    if proof_type == "test-suite":
        parsed = _parse_test_suite_proof(value, location, diagnostics)
        return parsed if parsed is not None else False
    if proof_type == "runtime-session":
        parsed = _parse_runtime_session_proof(value, location, diagnostics)
        return parsed if parsed is not None else False
    diagnostics.append(
        _error("validation_proof_malformed", "Validation proof type must be 'test-suite' or 'runtime-session'.", f"{location}.type")
    )
    return False


def _parse_proof_role(
    value: dict[str, Any],
    proof: dict[str, Any] | None,
    location: str,
    diagnostics: list[AcceptanceDiagnostic],
) -> str | None:
    declared_role: str | None = None
    if "proofRole" in value:
        raw_role = value["proofRole"]
        if not isinstance(raw_role, str) or raw_role not in ACCEPTANCE_PROOF_ROLES:
            diagnostics.append(
                _error("validation_proof_role_malformed", "Validation 'proofRole' is not a supported proof role.", f"{location}.proofRole")
            )
        else:
            declared_role = raw_role
    proof_declared_role = proof.get("role") if proof else None
    if proof_declared_role and declared_role and proof_declared_role != declared_role:
        diagnostics.append(
            _error(
                "validation_proof_role_mismatch",
                f"Validation proofRole '{declared_role}' conflicts with proof role '{proof_declared_role}'.",
                f"{location}.proofRole",
            )
        )
    role = proof_declared_role or declared_role
    if role is None and proof and proof.get("type") == "test-suite":
        role = "in-process-behavior"
    if proof and proof.get("type") == "test-suite" and role != "in-process-behavior":
        diagnostics.append(
            _error(
                "validation_proof_role_mismatch",
                f"A test-suite proof cannot satisfy the '{role}' role; external lifecycle and production composition "
                "require runtime-session proof.",
                f"{location}.proofRole",
            )
        )
    if proof is None and role in ("external-process-lifecycle", "production-composition-runtime"):
        diagnostics.append(
            _error(
                "validation_proof_role_mismatch",
                f"Validation proofRole '{role}' requires a runtime-session proof.",
                f"{location}.proofRole",
            )
        )
    return role


def _parse_executable_validation(
    entry: _Candidate,
    expected_scope: str,
    kind: str,
    project_root: str,
    diagnostics: list[AcceptanceDiagnostic],
    applicability: ValidationApplicability,
) -> ResolvedValidation | None:
    if not _is_object(entry.value) or not entry.id:
        diagnostics.append(
            _error(
                "validation_declaration_malformed",
                "Executable validation must be an object with a unique non-empty id.",
                entry.location,
            )
        )
        return None
    value = entry.value
    before = len(diagnostics)
    if value.get("scope") != expected_scope:
        diagnostics.append(
            _error("validation_scope_invalid", f"Validation '{entry.id}' must declare scope '{expected_scope}'.", f"{entry.location}.scope")
        )

    command = value.get("command")
    argv: tuple[str, ...] | None = None
    if (
        isinstance(command, list)
        and command
        and all(isinstance(argument, str) for argument in command)
        and command[0].strip()
    ):
        argv = tuple(command)
    else:
        diagnostics.append(
            _error(
                "validation_command_malformed",
                "Validation 'command' must be a non-empty string argument vector with a non-empty executable.",
                f"{entry.location}.command",
            )
        )
    cwd = _canonical_working_directory(project_root, value.get("workingDirectory"), f"{entry.location}.workingDirectory", diagnostics)
    limits = _parse_limits(value.get("limits"), f"{entry.location}.limits", diagnostics)
    assertions = _parse_assertions(value.get("assertions"), f"{entry.location}.assertions", diagnostics)
    proof = _parse_proof(value.get("proof"), f"{entry.location}.proof", diagnostics)
    role = _parse_proof_role(value, proof if isinstance(proof, dict) else None, entry.location, diagnostics)

    if len(diagnostics) != before or argv is None or cwd is None or limits is None or assertions is None or proof is False:
        return None
    return ResolvedValidation(
        id=entry.id,
        declaration=ValidationDeclarationRef(kind=kind, location=entry.location, owner=entry.owner),
        argv=argv,
        cwd=cwd,
        limits=limits,
        assertions=assertions,
        applicability=applicability,
        proof_role=role,
        proof=proof if isinstance(proof, dict) else None,
    )


def _resolve_project_checks(
    references: list[tuple[str, str]],
    collected: _Collected,
    project_root: str,
    diagnostics: list[AcceptanceDiagnostic],
    checks: list[ResolvedValidation],
) -> None:
    for reference_id, location in references:
        matches = [entry for entry in collected.project if entry.id == reference_id]
        if not matches:
            diagnostics.append(
                _error(
                    "project_check_reference_missing",
                    f"Project-check reference '{reference_id}' does not resolve to a top-level project validation.",
                    location,
                )
            )
        elif len(matches) > 1:
            diagnostics.append(
                _error(
                    "project_check_reference_ambiguous",
                    f"Project-check reference '{reference_id}' resolves to multiple top-level validations.",
                    location,
                )
            )
        else:
            check = _parse_executable_validation(
                matches[0], "project", "project_check", project_root, diagnostics, ValidationApplicability(mode="project-check")
            )
            if check:
                checks.append(check)


def resolve_validation_inventory(
    project: dict[str, Any], project_root: str, scope: AcceptanceScope
) -> ValidationInventory:
    """Resolve every executable acceptance check from the evaluated project."""
    diagnostics: list[AcceptanceDiagnostic] = []
    collected = _collect_architecture_validations(project)
    field_present, references = _parse_project_check_references(project, diagnostics)
    attached_with_proof = [entry for entry in collected.attached if _is_object(entry.value) and "proof" in entry.value]
    if not field_present and not attached_with_proof:
        return ValidationInventory(declared=False)

    diagnostics.extend(collected.malformed)
    _validate_global_identity(collected.project + collected.attached, collected.references, diagnostics)

    checks: list[ResolvedValidation] = []
    _resolve_project_checks(references, collected, project_root, diagnostics, checks)

    attached_test_count = 0
    attached_runtime_count = 0
    for entry in attached_with_proof:
        applicable = _parse_attached_applicability(entry, scope, diagnostics)
        if applicable is not True:
            continue
        proof_value = entry.value.get("proof")
        proof_type = proof_value.get("type") if _is_object(proof_value) else None
        if proof_type == "runtime-session":
            attached_runtime_count += 1
            kind = "attached_runtime"
        else:
            attached_test_count += 1
            kind = "attached_test"
        applicability_value = entry.value.get("applicability")
        applicability = (
            ValidationApplicability(mode="changes", changes=tuple(applicability_value["changes"]))
            if _is_object(applicability_value) and applicability_value.get("mode") == "changes"
            else ValidationApplicability(mode="always")
        )
        check = _parse_executable_validation(entry, "attached", kind, project_root, diagnostics, applicability)
        if check:
            checks.append(check)

    return ValidationInventory(
        declared=True,
        project_check_reference_count=len(references),
        applicable_attached_test_count=attached_test_count,
        applicable_attached_runtime_session_count=attached_runtime_count,
        checks=checks,
        diagnostics=diagnostics,
    )
