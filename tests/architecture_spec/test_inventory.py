"""Fail-closed validation-inventory resolution (port of validation-inventory.ts)."""

import json
from pathlib import Path
from typing import Any

import pytest

from specify_cli.acceptance.deterministic.inventory import resolve_validation_inventory
from specify_cli.acceptance.deterministic.model import AcceptanceScope

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parents[1] / "fixtures" / "architecture"
PROJECT_SCOPE = AcceptanceScope(mode="project")


def _codes(inventory) -> list[str]:
    return [d.code for d in inventory.diagnostics]


def _base_project(**overrides: Any) -> dict[str, Any]:
    project: dict[str, Any] = {
        "name": "demo",
        "validations": {
            "lint": {
                "id": "validation.lint",
                "scope": "project",
                "command": ["true"],
                "workingDirectory": ".",
                "limits": {"timeoutMs": 1000, "stdoutBytes": 4096, "stderrBytes": 4096},
            }
        },
        "completion": {"projectChecks": ["validation.lint"]},
    }
    project.update(overrides)
    return project


def test_not_declared_without_checks_or_proof(tmp_path: Path) -> None:
    project = {"name": "demo", "contexts": {"Core": {"valueObjects": {"Token": {"validations": [{"id": "validation.t", "command": ["true"]}]}}}}}
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert inventory.declared is False
    assert inventory.checks == [] and inventory.diagnostics == []


def test_empty_project_checks_arms_the_gate(tmp_path: Path) -> None:
    inventory = resolve_validation_inventory(
        {"name": "demo", "completion": {"projectChecks": []}}, str(tmp_path), PROJECT_SCOPE
    )
    assert inventory.declared is True
    assert inventory.checks == [] and inventory.diagnostics == []


def test_happy_path_project_check(tmp_path: Path) -> None:
    inventory = resolve_validation_inventory(_base_project(), str(tmp_path), PROJECT_SCOPE)
    assert inventory.declared and not inventory.diagnostics
    assert [c.id for c in inventory.checks] == ["validation.lint"]
    check = inventory.checks[0]
    assert check.argv == ("true",) and check.declaration.kind == "project_check"
    assert check.cwd == str(tmp_path.resolve())


def test_crest_synth_golden_inventory(tmp_path: Path) -> None:
    project = json.loads((FIXTURES / "crest-synth-project.json").read_text(encoding="utf-8"))
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert inventory.declared is True
    assert not inventory.diagnostics
    assert inventory.project_check_reference_count == 26
    assert len(inventory.checks) == 26
    # crest-synth's attached validations carry no proof, so none are binding.
    assert inventory.applicable_attached_test_count == 0
    assert inventory.applicable_attached_runtime_session_count == 0


def test_missing_and_duplicate_project_check_references(tmp_path: Path) -> None:
    project = _base_project(completion={"projectChecks": ["validation.lint", "validation.lint", "validation.ghost"]})
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    codes = _codes(inventory)
    assert "project_check_reference_duplicate" in codes
    assert "project_check_reference_missing" in codes


def test_ambiguous_identity_fails_closed(tmp_path: Path) -> None:
    project = _base_project()
    project["contexts"] = {
        "Core": {"valueObjects": {"Token": {"validations": [{"id": "validation.lint", "command": ["true"]}]}}}
    }
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert "validation_identity_ambiguous_owner" in _codes(inventory)


def test_identity_missing_when_gate_armed(tmp_path: Path) -> None:
    project = _base_project()
    project["adapters"] = {"X": {"validations": [{"command": ["true"]}]}}
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert "validation_identity_missing" in _codes(inventory)


def test_orphaned_string_reference(tmp_path: Path) -> None:
    project = _base_project()
    project["evidence"] = {"e1": {"validations": ["validation.ghost"]}}
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert "validation_evidence_reference_orphaned" in _codes(inventory)


def _attached_project(proof: dict[str, Any], applicability: Any = None, scope_value: str = "attached") -> dict[str, Any]:
    declaration: dict[str, Any] = {
        "id": "validation.attached_check",
        "scope": scope_value,
        "command": ["true"],
        "workingDirectory": ".",
        "limits": {"timeoutMs": 1000, "stdoutBytes": 4096, "stderrBytes": 4096},
        "proof": proof,
    }
    if applicability is not None:
        declaration["applicability"] = applicability
    return {
        "name": "demo",
        "contexts": {"Core": {"valueObjects": {"Token": {"validations": [declaration]}}}},
    }


TEST_SUITE_PROOF = {
    "type": "test-suite",
    "provider": "structured-json-v1",
    "selector": {"suite": "unit"},
    "minimumExecuted": 1,
    "options": {"stream": "stdout"},
}


def test_attached_proof_requires_applicability(tmp_path: Path) -> None:
    inventory = resolve_validation_inventory(_attached_project(TEST_SUITE_PROOF), str(tmp_path), PROJECT_SCOPE)
    assert inventory.declared is True
    assert "validation_applicability_missing" in _codes(inventory)


def test_attached_applicability_mission_match(tmp_path: Path) -> None:
    project = _attached_project(TEST_SUITE_PROOF, {"mode": "changes", "changes": ["my-mission"]})
    matching = resolve_validation_inventory(project, str(tmp_path), AcceptanceScope(mode="mission", mission="my-mission"))
    assert [c.id for c in matching.checks] == ["validation.attached_check"]
    assert matching.applicable_attached_test_count == 1

    other = resolve_validation_inventory(project, str(tmp_path), AcceptanceScope(mode="mission", mission="other"))
    assert other.checks == [] and not other.diagnostics

    # Conservative inclusion: project scope runs mission-scoped attached checks.
    project_run = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert [c.id for c in project_run.checks] == ["validation.attached_check"]


def test_attached_scope_must_be_attached(tmp_path: Path) -> None:
    project = _attached_project(TEST_SUITE_PROOF, {"mode": "always"}, scope_value="project")
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert "validation_scope_invalid" in _codes(inventory)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"command": "true"}, "validation_command_malformed"),
        ({"command": []}, "validation_command_malformed"),
        ({"workingDirectory": "/etc"}, "validation_working_directory_outside_root"),
        ({"workingDirectory": "does-not-exist"}, "validation_working_directory_unavailable"),
        ({"limits": {"timeoutMs": 0, "stdoutBytes": 1, "stderrBytes": 1}}, "validation_limits_malformed"),
        ({"limits": {"timeoutMs": 10**9, "stdoutBytes": 1, "stderrBytes": 1}}, "validation_limits_malformed"),
        ({"assertions": "nope"}, "validation_assertions_malformed"),
        ({"proofRole": "external-process-lifecycle"}, "validation_proof_role_mismatch"),
    ],
)
def test_declaration_defects_fail_closed(tmp_path: Path, mutation: dict[str, Any], expected_code: str) -> None:
    project = _base_project()
    project["validations"]["lint"].update(mutation)
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert expected_code in _codes(inventory)
    assert inventory.checks == []


@pytest.mark.parametrize(
    ("proof_mutation", "expected_code"),
    [
        ({"selector": None}, "validation_selector_missing"),
        ({"minimumExecuted": 0}, "validation_proof_malformed"),
        ({"provider": ""}, "validation_proof_malformed"),
        ({"role": "external-process-lifecycle"}, "validation_proof_role_mismatch"),
        ({"type": "mystery"}, "validation_proof_malformed"),
    ],
)
def test_test_suite_proof_defects(tmp_path: Path, proof_mutation: dict[str, Any], expected_code: str) -> None:
    proof = {**TEST_SUITE_PROOF, **proof_mutation}
    if proof_mutation.get("selector", "sentinel") is None:
        del proof["selector"]
    project = _attached_project(proof, {"mode": "always"})
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert expected_code in _codes(inventory)


def test_runtime_session_proof_is_fully_parsed(tmp_path: Path) -> None:
    """A runtime-session proof now needs every required runtime declaration field."""
    proof = {
        "type": "runtime-session",
        "provider": "process-lifecycle-v1",
        "role": "external-process-lifecycle",
        "entryPoint": "./app",
        "boundary": "external-process",
        "environment": "synthetic",
        "lifecycle": "bounded",
        "successCondition": "terminal markers observed",
        "terminationOwner": "application",
        "resources": [{"id": "proc", "type": "process", "disposition": "release", "owner": "fixture"}],
        "stdioMode": "pipe",
        "timeouts": {
            "startupTimeoutMs": 1000,
            "progressSilenceMs": 1000,
            "completionTimeoutMs": 2000,
            "completionToExitGraceMs": 200,
            "teardownGraceMs": 500,
            "hardTimeoutMs": 3000,
        },
        "progress": [{"id": "checkpoint", "stream": "stdout", "contains": "CHECKPOINT", "minimumCount": 1}],
        "completion": [{"id": "final", "stream": "stdout", "contains": "FINAL", "exactCount": 1}],
        "requireExitCode": 0,
        "requireNoDescendants": True,
        "requiredCapabilities": [],
    }
    project = _attached_project(proof, {"mode": "always"})
    inventory = resolve_validation_inventory(project, str(tmp_path), PROJECT_SCOPE)
    assert not inventory.diagnostics
    assert inventory.applicable_attached_runtime_session_count == 1
    assert inventory.checks[0].declaration.kind == "attached_runtime"
    parsed = inventory.checks[0].proof
    assert parsed is not None and parsed["type"] == "runtime-session"
    assert parsed["lifecycle"] == "bounded" and parsed["interactions"] == []
    # A partial runtime declaration (the old opaque-carry shape) now fails closed.
    partial = {"type": "runtime-session", "provider": "process-lifecycle-v1", "entryPoint": ["./app"]}
    failing = resolve_validation_inventory(_attached_project(partial, {"mode": "always"}), str(tmp_path), PROJECT_SCOPE)
    assert failing.checks == []
    assert "runtime_entry_point_malformed" in _codes(failing)
