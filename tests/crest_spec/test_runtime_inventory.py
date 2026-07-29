"""Fail-closed runtime-session proof parsing (port of parseRuntimeSessionProof)."""

import copy
from pathlib import Path
from typing import Any

import pytest

from specify_cli.acceptance.deterministic.inventory import resolve_validation_inventory
from specify_cli.acceptance.deterministic.model import AcceptanceScope

pytestmark = pytest.mark.unit

PROJECT_SCOPE = AcceptanceScope(mode="project")


def runtime_proof(**overrides: Any) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "type": "runtime-session",
        "provider": "process-lifecycle-v1",
        "role": "external-process-lifecycle",
        "entryPoint": "app serve",
        "boundary": "external-process",
        "environment": "synthetic",
        "lifecycle": "bounded",
        "successCondition": "terminal markers observed in order",
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
        "completion": [
            {"id": "final-state", "stream": "stdout", "contains": "FINAL_STATE", "exactCount": 1},
            {"id": "final-summary", "stream": "stdout", "contains": "FINAL_SUMMARY", "exactCount": 1},
        ],
        "requireExitCode": 0,
        "requireNoDescendants": True,
        "requiredCapabilities": [],
        "interactions": [],
    }
    proof.update(copy.deepcopy(overrides))
    return proof


def project_with(proof: dict[str, Any]) -> dict[str, Any]:
    declaration = {
        "id": "validation.runtime_check",
        "scope": "attached",
        "command": ["true"],
        "workingDirectory": ".",
        "limits": {"timeoutMs": 5000, "stdoutBytes": 65536, "stderrBytes": 65536},
        "applicability": {"mode": "always"},
        "proof": proof,
    }
    return {"name": "demo", "contexts": {"Core": {"validations": [declaration]}}}


def resolve(tmp_path: Path, proof: dict[str, Any]):
    return resolve_validation_inventory(project_with(proof), str(tmp_path), PROJECT_SCOPE)


def codes(inventory) -> list[str]:
    return [d.code for d in inventory.diagnostics]


def test_valid_runtime_proof_parses_fully(tmp_path: Path) -> None:
    inventory = resolve(tmp_path, runtime_proof())
    assert not inventory.diagnostics
    assert inventory.applicable_attached_runtime_session_count == 1
    check = inventory.checks[0]
    assert check.declaration.kind == "attached_runtime"
    parsed = check.proof
    assert parsed is not None
    assert parsed["type"] == "runtime-session"
    assert parsed["lifecycle"] == "bounded"
    assert parsed["timeouts"]["hardTimeoutMs"] == 3000
    assert parsed["progress"][0] == {"id": "checkpoint", "stream": "stdout", "contains": "CHECKPOINT", "minimumCount": 1}
    assert parsed["completion"][1]["exactCount"] == 1
    assert parsed["interactions"] == [] and parsed["requiredCapabilities"] == []
    assert "teardown" not in parsed


def test_persistent_proof_keeps_teardown(tmp_path: Path) -> None:
    proof = runtime_proof(
        lifecycle="service-persistent",
        teardown={"provider": "owned-process-signal-v1", "request": {"signal": "SIGTERM"}},
    )
    inventory = resolve(tmp_path, proof)
    assert not inventory.diagnostics
    assert inventory.checks[0].proof["teardown"] == {"provider": "owned-process-signal-v1", "request": {"signal": "SIGTERM"}}


def test_valid_interaction_declaration_parses(tmp_path: Path) -> None:
    proof = runtime_proof(
        interactions=[
            {
                "id": "poke",
                "provider": "process-json-v1",
                "opensAfter": "checkpoint",
                "closesBefore": "final-state",
                "request": {"command": ["driver"]},
                "requiredAssertions": ["isolation-preserved"],
            }
        ]
    )
    inventory = resolve(tmp_path, proof)
    assert not inventory.diagnostics
    assert inventory.checks[0].proof["interactions"][0]["id"] == "poke"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"provider": " "}, "validation_proof_malformed"),
        ({"role": "in-process-behavior"}, "validation_proof_role_mismatch"),
        ({"entryPoint": ""}, "runtime_entry_point_malformed"),
        ({"entryPoint": ["./app"]}, "runtime_entry_point_malformed"),
        ({"boundary": "imaginary"}, "runtime_boundary_malformed"),
        ({"environment": "staging"}, "runtime_environment_malformed"),
        ({"lifecycle": "forever"}, "runtime_lifecycle_malformed"),
        ({"successCondition": ""}, "runtime_success_condition_malformed"),
        ({"terminationOwner": ""}, "runtime_termination_owner_malformed"),
        ({"stdioMode": "tty"}, "runtime_stdio_mode_malformed"),
        ({"requireExitCode": "0"}, "runtime_exit_requirement_malformed"),
        ({"requireExitCode": True}, "runtime_exit_requirement_malformed"),
        ({"requireNoDescendants": False}, "runtime_descendant_requirement_malformed"),
        ({"timeouts": None}, "runtime_timeouts_malformed"),
        (
            {
                "timeouts": {
                    "startupTimeoutMs": 1000,
                    "progressSilenceMs": 1000,
                    "completionTimeoutMs": 2000,
                    "completionToExitGraceMs": 200,
                    "teardownGraceMs": 500,
                }
            },
            "runtime_timeouts_malformed",
        ),
        (
            {
                "timeouts": {
                    "startupTimeoutMs": 3000,
                    "progressSilenceMs": 1000,
                    "completionTimeoutMs": 2000,
                    "completionToExitGraceMs": 200,
                    "teardownGraceMs": 500,
                    "hardTimeoutMs": 3000,
                }
            },
            "runtime_timeouts_incoherent",
        ),
        ({"progress": []}, "runtime_markers_malformed"),
        ({"completion": [{"id": "final", "stream": "stdout", "contains": "DONE"}]}, "runtime_markers_malformed"),
        ({"progress": [{"id": "final-state", "stream": "stdout", "contains": "X", "minimumCount": 1}]}, "runtime_marker_identity_ambiguous"),
        (
            {"completion": [
                {"id": "a", "stream": "stdout", "contains": "SAME", "exactCount": 1},
                {"id": "b", "stream": "stdout", "contains": "SAME", "exactCount": 1},
            ]},
            "runtime_marker_identity_ambiguous",
        ),
        ({"resources": []}, "runtime_resources_malformed"),
        (
            {"resources": [{"id": "port", "type": "tcp-port", "disposition": "retain-during-readiness", "owner": "fixture"}]},
            "runtime_resource_lifecycle_mismatch",
        ),
        ({"interactions": "nope"}, "runtime_interactions_malformed"),
        (
            {"interactions": [
                {
                    "id": "poke",
                    "provider": "process-json-v1",
                    "opensAfter": "final-state",
                    "closesBefore": "checkpoint",
                    "request": {},
                    "requiredAssertions": ["a"],
                }
            ]},
            "runtime_interactions_malformed",
        ),
        ({"teardown": {"provider": "owned-process-signal-v1", "request": {"signal": "SIGTERM"}}}, "runtime_lifecycle_teardown_mismatch"),
        ({"lifecycle": "service-persistent"}, "runtime_teardown_missing"),
        ({"requiredCapabilities": ["a", "a"]}, "runtime_capabilities_malformed"),
    ],
)
def test_runtime_proof_defects_fail_closed(tmp_path: Path, overrides: dict[str, Any], expected_code: str) -> None:
    inventory = resolve(tmp_path, runtime_proof(**overrides))
    assert expected_code in codes(inventory)
    assert inventory.checks == []


def test_missing_required_capabilities_field_is_malformed(tmp_path: Path) -> None:
    proof = runtime_proof()
    del proof["requiredCapabilities"]
    inventory = resolve(tmp_path, proof)
    assert "runtime_capabilities_malformed" in codes(inventory)


def test_pty_with_stderr_marker_is_stream_mismatch(tmp_path: Path) -> None:
    proof = runtime_proof(
        stdioMode="pty",
        progress=[{"id": "checkpoint", "stream": "stderr", "contains": "CHECKPOINT", "minimumCount": 1}],
    )
    inventory = resolve(tmp_path, proof)
    assert "runtime_pty_stream_mismatch" in codes(inventory)
