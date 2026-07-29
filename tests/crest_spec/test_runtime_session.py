"""Real-subprocess runtime lifecycle acceptance (port of runtime-session.ts behavior)."""

import copy
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import specify_cli.acceptance.runtime_lifecycle.launcher as launcher_module
from specify_cli.acceptance.deterministic.model import (
    AcceptanceScope,
    ProcessLimits,
    ResolvedValidation,
    ValidationApplicability,
    ValidationDeclarationRef,
)
from specify_cli.acceptance.deterministic.process_runner import ProcessExecutionRequest, ProcessLimits as RunnerLimits
from specify_cli.acceptance.deterministic.service import AcceptanceService
from specify_cli.acceptance.runtime_lifecycle import ProcessLifecycleRuntimeProvider, ScriptRuntimeProcessLauncher

pytestmark = pytest.mark.integration

PY = sys.executable
FIXTURE = str((Path(__file__).parents[1] / "fixtures" / "runtime" / "session_fixture.py").resolve())
DRIVER = str((Path(__file__).parents[1] / "fixtures" / "runtime" / "interaction_driver.py").resolve())
PROJECT_SCOPE = AcceptanceScope(mode="project")


def base_timeouts(**overrides: int) -> dict[str, int]:
    timeouts = {
        "startupTimeoutMs": 3000,
        "progressSilenceMs": 2500,
        "completionTimeoutMs": 4000,
        "completionToExitGraceMs": 400,
        "teardownGraceMs": 1500,
        "hardTimeoutMs": 4900,
    }
    timeouts.update(overrides)
    return timeouts


def make_proof(**overrides: Any) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "type": "runtime-session",
        "provider": "process-lifecycle-v1",
        "role": "external-process-lifecycle",
        "entryPoint": "session-fixture",
        "boundary": "external-process",
        "environment": "synthetic",
        "lifecycle": "bounded",
        "successCondition": "terminal markers observed in declared order",
        "terminationOwner": "application",
        "resources": [{"id": "proc", "type": "process", "disposition": "release", "owner": "fixture"}],
        "stdioMode": "pipe",
        "timeouts": base_timeouts(),
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


def run_provider(tmp_path: Path, argv: list[str], proof: dict[str, Any], provider: ProcessLifecycleRuntimeProvider | None = None):
    check = ResolvedValidation(
        id="validation.runtime_check",
        declaration=ValidationDeclarationRef(kind="attached_runtime", location="project.validations[0]", owner="project.demo"),
        argv=tuple(argv),
        cwd=str(tmp_path),
        limits=ProcessLimits(timeout_ms=15000, stdout_bytes=65536, stderr_bytes=65536),
        assertions=(),
        applicability=ValidationApplicability(mode="always"),
        proof_role=proof.get("role"),
        proof=proof,
    )
    request = ProcessExecutionRequest(
        command=list(argv),
        working_directory=str(tmp_path),
        limits=RunnerLimits(timeout_ms=15000, stdout_bytes=65536, stderr_bytes=65536),
    )
    provider = provider or ProcessLifecycleRuntimeProvider()
    return provider.run(check=check, request=request)


def codes(session: dict[str, Any]) -> list[str]:
    return [d["code"] for d in session["diagnostics"]]


def _assert_dead_within(pid: int, timeout_s: float) -> None:
    import os

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"owned pid {pid} was still alive after cleanup")


def test_bounded_passing_run(tmp_path: Path) -> None:
    result = run_provider(tmp_path, [PY, FIXTURE, "clean", "--delay", "30"], make_proof())
    session = result.runtime_session
    assert session["status"] == "passed" and session["diagnostics"] == []
    assert result.process.termination == "exited" and result.process.exit_code == 0
    evidence = session["evidence"]
    assert evidence["processTree"]["noOwnedProcessesRemain"] is True
    assert evidence["startupObservedAtMs"] is not None
    assert evidence["completionObservedAtMs"] >= evidence["startupObservedAtMs"]
    assert all(milestone["passed"] for milestone in evidence["milestones"])
    assert evidence["teardown"] == {"required": False, "passed": True}


def test_success_hang_is_resident_failure(tmp_path: Path) -> None:
    proof = make_proof(timeouts=base_timeouts(completionToExitGraceMs=150))
    result = run_provider(tmp_path, [PY, FIXTURE, "success-hang"], proof)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "success_reported_but_process_resident" in codes(session)
    assert session["evidence"]["timeoutStage"] == "completion_to_exit"
    assert result.process.termination == "timed_out"
    # The exact owned tree was cleaned up after the failure.
    assert session["evidence"]["processTree"]["noOwnedProcessesRemain"] is True
    assert session["evidence"]["terminationActions"], "cleanup must record its termination actions"


def test_resident_child_fails_and_cleanup_kills_only_the_owned_tree(tmp_path: Path) -> None:
    # Same-basename decoy: identical executable as the fixture's lingering child,
    # but outside the owned pid/pgid tree — cleanup must leave it untouched.
    decoy = subprocess.Popen(
        [PY, "-c", "import time\nwhile True: time.sleep(1)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        result = run_provider(tmp_path, [PY, FIXTURE, "child-resident", "--parent-delay", "250"], make_proof())
        session = result.runtime_session
        assert session["status"] == "failed"
        assert "owned_descendant_resident" in codes(session)
        child_pid = int(re.search(r"CHILD_PID:(\d+)", result.process.stdout).group(1))
        assert child_pid in session["evidence"]["processTree"]["observedDescendantPids"]
        _assert_dead_within(child_pid, 3.0)
        assert decoy.poll() is None, "cleanup must never select processes by executable name"
    finally:
        decoy.kill()
        decoy.wait()


def test_wrong_exit_code(tmp_path: Path) -> None:
    result = run_provider(tmp_path, [PY, FIXTURE, "wrong-exit"], make_proof())
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_exit_code_mismatch" in codes(session)
    assert result.process.exit_code == 3


def test_out_of_order_completion_markers(tmp_path: Path) -> None:
    result = run_provider(tmp_path, [PY, FIXTURE, "out-of-order"], make_proof())
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "required_marker_out_of_order" in codes(session)
    # Observed occurrences remain in evidence.
    milestones = {m["id"]: m for m in session["evidence"]["milestones"]}
    assert milestones["final-state"]["observedCount"] == 1
    assert milestones["final-summary"]["observedCount"] == 1


def test_persistent_readiness_then_owned_signal_teardown(tmp_path: Path) -> None:
    proof = make_proof(
        lifecycle="service-persistent",
        completion=[{"id": "ready", "stream": "stdout", "contains": "READY", "exactCount": 1}],
        teardown={"provider": "owned-process-signal-v1", "request": {"signal": "SIGTERM"}},
    )
    result = run_provider(tmp_path, [PY, FIXTURE, "persistent"], proof)
    session = result.runtime_session
    assert session["status"] == "passed", codes(session)
    evidence = session["evidence"]
    assert "completionObservedAtMs" in evidence, "readiness must be reported"
    teardown = evidence["teardown"]
    assert teardown["required"] is True and teardown["passed"] is True
    assert teardown["provider"] == "owned-process-signal-v1"
    assert teardown["startedAtMs"] <= teardown["completedAtMs"]
    assert result.process.exit_code == 0
    assert evidence["processTree"]["noOwnedProcessesRemain"] is True


def test_persistent_teardown_provider_unsupported(tmp_path: Path) -> None:
    proof = make_proof(
        lifecycle="service-persistent",
        completion=[{"id": "ready", "stream": "stdout", "contains": "READY", "exactCount": 1}],
        teardown={"provider": "mystery-teardown-v1", "request": {"signal": "SIGTERM"}},
    )
    result = run_provider(tmp_path, [PY, FIXTURE, "persistent"], proof)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_teardown_provider_unsupported" in codes(session)
    assert session["evidence"]["processTree"]["noOwnedProcessesRemain"] is True


def test_persistent_teardown_request_must_be_sigterm(tmp_path: Path) -> None:
    proof = make_proof(
        lifecycle="service-persistent",
        completion=[{"id": "ready", "stream": "stdout", "contains": "READY", "exactCount": 1}],
        teardown={"provider": "owned-process-signal-v1", "request": {"signal": "SIGKILL"}},
    )
    result = run_provider(tmp_path, [PY, FIXTURE, "persistent"], proof)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_teardown_request_malformed" in codes(session)


def test_required_capability_gap_blocks_without_spawning(tmp_path: Path) -> None:
    proof = make_proof(requiredCapabilities=["physical-device:relay-board"])
    result = run_provider(tmp_path, [PY, FIXTURE, "clean"], proof)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert codes(session) == ["BLOCKING_REQUIRED_PROOF_GAP"]
    assert "physical-device:relay-board" in session["diagnostics"][0]["message"]
    assert result.process.termination == "spawn_error"
    assert result.process.spawn_error.code == "RUNTIME_CAPABILITY_UNAVAILABLE"


def test_pty_unavailable_is_proof_gap_never_pipe_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher_module, "_find_script_executable", lambda: None)
    launcher = ScriptRuntimeProcessLauncher()
    assert launcher.pty_available is False
    provider = ProcessLifecycleRuntimeProvider(launcher=launcher)
    result = run_provider(tmp_path, [PY, FIXTURE, "clean"], make_proof(stdioMode="pty"), provider=provider)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert codes(session) == ["BLOCKING_REQUIRED_PROOF_GAP"]
    assert "stdio:pty" in session["diagnostics"][0]["message"]
    # Never silently downgraded to pipe: no process was ever spawned.
    assert result.process.termination == "spawn_error"


def _interaction_proof(seam: Path, mode: str) -> dict[str, Any]:
    return make_proof(
        progress=[{"id": "window-open", "stream": "stdout", "contains": "WINDOW_OPEN", "minimumCount": 1}],
        completion=[
            {"id": "window-close", "stream": "stdout", "contains": "WINDOW_CLOSE", "exactCount": 1},
            {"id": "final-summary", "stream": "stdout", "contains": "FINAL_SUMMARY", "exactCount": 1},
        ],
        interactions=[
            {
                "id": "poke",
                "provider": "process-json-v1",
                "opensAfter": "window-open",
                "closesBefore": "window-close",
                "request": {
                    "command": [PY, DRIVER],
                    "timeoutMs": 3000,
                    "payload": {"mode": mode, "seamPath": str(seam), "action": "poke"},
                },
                "requiredAssertions": ["isolation-preserved"],
            }
        ],
    )


def _interaction_argv(seam: Path) -> list[str]:
    return [PY, FIXTURE, "interaction", "--seam", str(seam), "--seam-timeout", "3000"]


def test_interaction_within_window_passes(tmp_path: Path) -> None:
    seam = tmp_path / "seam.json"
    result = run_provider(tmp_path, _interaction_argv(seam), _interaction_proof(seam, "pass"))
    session = result.runtime_session
    assert session["status"] == "passed", codes(session)
    interaction = session["evidence"]["interactions"][0]
    assert interaction["status"] == "passed"
    assert interaction["openingObservedAtMs"] <= interaction["evidence"]["deliveredAtMs"] < interaction["closingObservedAtMs"]
    assert interaction["evidence"]["sessionId"] == session["evidence"]["sessionId"]
    assert interaction["evidence"]["reachedSeam"] is True


def test_interaction_session_mismatch_fails(tmp_path: Path) -> None:
    seam = tmp_path / "seam.json"
    result = run_provider(tmp_path, _interaction_argv(seam), _interaction_proof(seam, "wrong-session"))
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_interaction_session_mismatch" in codes(session)


def test_interaction_failed_assertion_fails(tmp_path: Path) -> None:
    seam = tmp_path / "seam.json"
    result = run_provider(tmp_path, _interaction_argv(seam), _interaction_proof(seam, "assertion-failed"))
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_interaction_assertion_failed" in codes(session)


def test_interaction_provider_unsupported_fails_closed(tmp_path: Path) -> None:
    seam = tmp_path / "seam.json"
    proof = _interaction_proof(seam, "pass")
    proof["interactions"][0]["provider"] = "mystery-driver-v1"
    result = run_provider(tmp_path, _interaction_argv(seam), proof)
    session = result.runtime_session
    assert session["status"] == "failed"
    assert "runtime_interaction_provider_unsupported" in codes(session)


# ---- end-to-end through AcceptanceService -----------------------------------

PROJECT_HEADER = """\
name: demo
mission: prove the runtime engine
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
  projectChecks: [validation.demo_check]
"""

RUNTIME_PROOF_YAML = """\
    proof:
      type: runtime-session
      provider: process-lifecycle-v1
      role: external-process-lifecycle
      entryPoint: session-fixture
      boundary: external-process
      environment: synthetic
      lifecycle: bounded
      successCondition: terminal markers observed in declared order
      terminationOwner: application
      stdioMode: pipe
      requireExitCode: 0
      requireNoDescendants: true
      requiredCapabilities: []
      resources:
      - {id: proc, type: process, disposition: release, owner: fixture}
      timeouts:
        {startupTimeoutMs: 3000, progressSilenceMs: 2500, completionTimeoutMs: 4000, completionToExitGraceMs: 400, teardownGraceMs: 1500, hardTimeoutMs: 4900}
      progress:
      - {id: checkpoint, stream: stdout, contains: CHECKPOINT, minimumCount: 1}
      completion:
      - {id: final-state, stream: stdout, contains: FINAL_STATE, exactCount: 1}
      - {id: final-summary, stream: stdout, contains: FINAL_SUMMARY, exactCount: 1}
"""


def write_runtime_spec(root: Path, command: list[str]) -> None:
    spec = root / ".kittify" / "crest-spec"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "project.yaml").write_text(PROJECT_HEADER, encoding="utf-8")
    (spec / "proof").mkdir(exist_ok=True)
    validations = f"""\
projectValidations:
  demo_check:
    scope: project
    command: {json.dumps(command)}
    workingDirectory: .
    limits: {{timeoutMs: 30000, stdoutBytes: 65536, stderrBytes: 65536}}
{RUNTIME_PROOF_YAML}attachedValidations: {{}}
"""
    (spec / "proof" / "validations.yaml").write_text(validations, encoding="utf-8")


def test_end_to_end_runtime_proof_through_acceptance_service(tmp_path: Path) -> None:
    write_runtime_spec(tmp_path, [PY, FIXTURE, "clean", "--delay", "30"])
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is True, json.dumps(report.to_dict()["diagnostics"])
    check = report.checks[0]
    assert check["passed"] is True and check["processPassed"] is True
    assert check["runtimeSession"]["status"] == "passed"
    assert check["runtimeSession"]["evidence"]["processTree"]["noOwnedProcessesRemain"] is True
    assert check["proof"] == {"type": "runtime-session", "provider": "process-lifecycle-v1"}


def test_end_to_end_runtime_failure_through_acceptance_service(tmp_path: Path) -> None:
    write_runtime_spec(tmp_path, [PY, FIXTURE, "wrong-exit"])
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    check = report.checks[0]
    assert check["runtimeSession"]["status"] == "failed"
    assert "runtime_exit_code_mismatch" in [d["code"] for d in check["runtimeSession"]["diagnostics"]]
