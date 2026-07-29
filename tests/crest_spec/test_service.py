"""End-to-end deterministic acceptance service behavior."""

import json
import sys
from pathlib import Path

import pytest

from specify_cli.acceptance.deterministic.model import AcceptanceScope
from specify_cli.acceptance.deterministic.service import AcceptanceService

pytestmark = pytest.mark.integration

PROJECT_SCOPE = AcceptanceScope(mode="project")

PY = sys.executable

PROJECT_HEADER = """\
name: demo
mission: prove the service
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
  projectChecks: [validation.demo_check]
"""


def write_spec(root: Path, validations_yaml: str, project_yaml: str = PROJECT_HEADER) -> None:
    spec = root / ".kittify" / "crest-spec"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "project.yaml").write_text(project_yaml, encoding="utf-8")
    (spec / "proof").mkdir(exist_ok=True)
    (spec / "proof" / "validations.yaml").write_text(validations_yaml, encoding="utf-8")


def passing_validation(command_json: list[str], extra: str = "") -> str:
    argv = json.dumps(command_json)
    return f"""\
projectValidations:
  demo_check:
    scope: project
    command: {argv}
    workingDirectory: .
    limits: {{timeoutMs: 30000, stdoutBytes: 65536, stderrBytes: 65536}}
{extra}attachedValidations: {{}}
"""


def test_no_crest_spec_not_applicable(tmp_path: Path) -> None:
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.applicable is False and report.passed is True
    assert report.gates["crest_spec"]["status"] == "not_applicable"
    assert report.to_dict()["semanticReview"]["status"] == "not_evaluated"


def test_invalid_spec_fails_closed(tmp_path: Path) -> None:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(PROJECT_HEADER, encoding="utf-8")
    (spec / "goals.yaml").write_text("goals:\n  g:\n    capabilities: [nope]\n", encoding="utf-8")
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.applicable is True and report.passed is False
    assert report.gates["crest_spec"]["status"] == "failed"
    assert report.diagnostics[0]["code"] == "crest_spec_evaluation_failed"


def test_spec_without_executable_validations_not_applicable(tmp_path: Path) -> None:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(
        PROJECT_HEADER.replace("  projectChecks: [validation.demo_check]\n", ""), encoding="utf-8"
    )
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.applicable is False and report.passed is True
    assert report.gates["crest_spec"]["status"] == "passed"
    assert report.diagnostics[0]["code"] == "acceptance_not_applicable_no_executable_validations"


def test_passing_check_produces_passing_report(tmp_path: Path) -> None:
    write_spec(tmp_path, passing_validation([PY, "-c", "print('ok')"]))
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is True
    assert report.gates["validations"]["status"] == "passed"
    assert report.gates["validations"]["executed"] == 1
    check = report.checks[0]
    assert check["passed"] and check["process"]["termination"] == "exited"


def test_failing_check_fails_report_with_exit_one(tmp_path: Path) -> None:
    write_spec(tmp_path, passing_validation([PY, "-c", "raise SystemExit(3)"]))
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    check = report.checks[0]
    assert check["diagnostics"][0]["code"] == "validation_nonzero_exit"
    assert report.diagnostics[0]["code"] == "validation_failed"


def test_inventory_defect_blocks_execution(tmp_path: Path) -> None:
    validations = """\
projectValidations:
  demo_check:
    scope: project
    command: "not-an-argv-list"
    workingDirectory: .
    limits: {timeoutMs: 1000, stdoutBytes: 4096, stderrBytes: 4096}
attachedValidations: {}
"""
    write_spec(tmp_path, validations)
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    assert report.gates["validations"]["status"] == "failed"
    assert report.gates["validations"]["executed"] == 0
    codes = [d["code"] for d in report.gates["validations"]["diagnostics"]]
    assert "validation_command_malformed" in codes


def test_assertions_are_enforced(tmp_path: Path) -> None:
    extra = """\
    assertions:
    - {type: stdout-contains, value: MAGIC_MARKER}
"""
    validations = passing_validation([PY, "-c", "print('no marker here')"]).replace(
        "attachedValidations: {}", extra + "attachedValidations: {}"
    )
    write_spec(tmp_path, validations)
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    check = report.checks[0]
    assert check["processPassed"] is True and check["assertionsPassed"] is False


def test_green_process_with_zero_tests_fails_acceptance(tmp_path: Path) -> None:
    """The canonical worked example: exit 0, valid evidence, executed: 0."""
    evidence = {"selector": {"suite": "unit"}, "executed": 0, "passed": 0, "failed": 0, "source": {"kind": "fixture"}}
    (tmp_path / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    command = [PY, "-c", "import pathlib; print(pathlib.Path('evidence.json').read_text())"]
    extra = """\
    proof:
      type: test-suite
      provider: structured-json-v1
      minimumExecuted: 1
      selector: {suite: unit}
      options: {stream: stdout}
"""
    validations = passing_validation(command).replace("attachedValidations: {}", extra + "attachedValidations: {}")
    write_spec(tmp_path, validations)
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    check = report.checks[0]
    assert check["processPassed"] is True
    assert check["testEvidence"]["status"] == "failed"
    codes = [d["code"] for d in check["testEvidence"]["diagnostics"]]
    assert "test_evidence_minimum_not_met" in codes


def test_runtime_session_proof_fails_without_provider(tmp_path: Path) -> None:
    """With the real default registry, an unknown provider name still fails closed."""
    extra = """\
    proof:
      type: runtime-session
      provider: no-such-provider-v1
      role: external-process-lifecycle
      entryPoint: ./app
      boundary: external-process
      environment: synthetic
      lifecycle: bounded
      successCondition: terminal markers observed
      terminationOwner: application
      stdioMode: pipe
      requireExitCode: 0
      requireNoDescendants: true
      requiredCapabilities: []
      resources:
      - {id: proc, type: process, disposition: release, owner: fixture}
      timeouts:
        {startupTimeoutMs: 1000, progressSilenceMs: 1000, completionTimeoutMs: 2000, completionToExitGraceMs: 200, teardownGraceMs: 500, hardTimeoutMs: 3000}
      progress:
      - {id: checkpoint, stream: stdout, contains: CHECKPOINT, minimumCount: 1}
      completion:
      - {id: final, stream: stdout, contains: FINAL, exactCount: 1}
    applicability: {mode: always}
"""
    validations = passing_validation([PY, "-c", "print('ok')"]).replace(
        "attachedValidations: {}", extra + "attachedValidations: {}"
    )
    write_spec(tmp_path, validations)
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert report.passed is False
    check = report.checks[0]
    assert check["runtimeSession"]["status"] == "failed"
    codes = [d["code"] for d in check["runtimeSession"]["diagnostics"]]
    assert "runtime_session_provider_unsupported" in codes


def test_environment_never_serialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_ACCEPTANCE_TOKEN", "hunter2-do-not-leak")
    write_spec(tmp_path, passing_validation([PY, "-c", "print('ok')"]))
    report = AcceptanceService().run(tmp_path, PROJECT_SCOPE)
    assert "hunter2-do-not-leak" not in json.dumps(report.to_dict())
