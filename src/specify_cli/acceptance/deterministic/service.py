"""Deterministic acceptance orchestration: gates -> checks -> versioned report.

Port of CrestOpenSpec's ``service.ts`` (reference in
``research/crestopenspec-port/``), adapted to crest-kitty:

- The architecture gate loads the terse-YAML spec instead of evaluating CUE;
  the upstream codes ``cue_architecture_evaluation_failed`` /
  ``acceptance_not_applicable_no_cue`` are renamed
  ``architecture_evaluation_failed`` / ``acceptance_not_applicable_no_architecture``.
- Upstream's strict-OpenSpec gate has no analogue here: mission-artifact
  validation is `spec-kitty accept`'s existing summary machinery, which runs
  around this engine. The deterministic report carries the ``architecture``
  and ``validations`` gates only.
- Runtime-session proofs dispatch through ``runtime_session_registry``; the
  default registry registers ``process-lifecycle-v1`` from
  ``specify_cli.acceptance.runtime_lifecycle``. An unknown provider name still
  fails closed with ``runtime_session_provider_unsupported`` — a declared
  runtime proof can never silently pass.

Every dependency is injectable (loader, runner, registries) so downstream
extension requires no orchestration changes. The report never contains
environment values, and always carries
``semanticReview: {status: not_evaluated}`` — deterministic acceptance does
not establish semantic implementation conformance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from collections.abc import Callable

from .assertions import (
    AssertionEvaluatorRegistry,
    assertion_diagnostics,
    create_default_assertion_registry,
    evaluate_assertions,
)
from .inventory import resolve_validation_inventory
from .model import (
    ACCEPTANCE_REPORT_VERSION,
    AcceptanceDiagnostic,
    AcceptanceScope,
    ResolvedValidation,
)
from .process_runner import (
    LocalCommandRunner,
    ProcessExecutionRequest,
    ProcessLimits as RunnerLimits,
    ProcessResult,
    ProcessSpawnError,
)
from .test_evidence import (
    TestEvidenceProviderRegistry,
    TestSuiteProof,
    create_default_test_evidence_registry,
    extract_test_evidence,
)

SEMANTIC_REVIEW_BOUNDARY = {
    "status": "not_evaluated",
    "message": (
        "Deterministic acceptance does not establish semantic implementation "
        "conformance; adversarial review is a separate, mandatory layer."
    ),
}


class RuntimeSessionRegistry(Protocol):
    def get(self, provider: str) -> Any | None: ...


@dataclass
class AcceptanceReport:
    version: str
    scope: dict[str, Any]
    root: str | None
    applicable: bool
    passed: bool
    gates: dict[str, Any]
    checks: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    semantic_review: dict[str, Any] = field(default_factory=lambda: dict(SEMANTIC_REVIEW_BOUNDARY))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scope": self.scope,
            "root": self.root,
            "applicable": self.applicable,
            "passed": self.passed,
            "gates": self.gates,
            "checks": self.checks,
            "diagnostics": self.diagnostics,
            "semanticReview": self.semantic_review,
        }


def _scope_dict(scope: AcceptanceScope) -> dict[str, Any]:
    payload: dict[str, Any] = {"mode": scope.mode}
    if scope.mission:
        payload["mission"] = scope.mission
    return payload


def _gates_skeleton() -> dict[str, Any]:
    return {
        "architecture": {"status": "not_applicable", "files": [], "diagnostics": []},
        "validations": {
            "status": "not_applicable",
            "declaredProjectChecks": 0,
            "applicableAttachedTests": 0,
            "applicableAttachedRuntimeSessions": 0,
            "resolved": 0,
            "executed": 0,
            "diagnostics": [],
        },
    }


def _process_failure_diagnostic(result: ProcessResult) -> AcceptanceDiagnostic | None:
    if result.termination == "spawn_error":
        spawn: ProcessSpawnError | None = result.spawn_error
        detail = spawn.message if spawn else "unknown spawn error"
        prefix = f"Could not start validation ({spawn.code}): " if spawn and spawn.code else "Could not start validation: "
        return AcceptanceDiagnostic(code="validation_spawn_failed", message=prefix + detail)
    if result.termination == "timed_out":
        return AcceptanceDiagnostic(
            code="validation_timed_out",
            message=f"Validation exceeded its {result.limits.timeout_ms} ms timeout.",
        )
    if result.termination == "output_limit":
        streams = " and ".join(result.output_limit_exceeded)
        return AcceptanceDiagnostic(
            code="validation_output_limit",
            message=f"Validation exceeded its declared {streams} capture limit.",
        )
    if result.termination == "signaled":
        return AcceptanceDiagnostic(
            code="validation_signaled",
            message=f"Validation terminated by signal {result.signal or 'unknown'}.",
        )
    if result.exit_code != 0:
        exit_text = "none" if result.exit_code is None else result.exit_code
        return AcceptanceDiagnostic(code="validation_nonzero_exit", message=f"Validation exited with code {exit_text}.")
    return None


def _unexpected_process_result(request: ProcessExecutionRequest, error: Exception) -> ProcessResult:
    return ProcessResult(
        command=list(request.command),
        working_directory=request.working_directory,
        limits=request.limits,
        duration_ms=0,
        termination="spawn_error",
        exit_code=None,
        signal=None,
        timed_out=False,
        spawn_error=ProcessSpawnError(message=f"Command runner failed: {error}"),
    )


def _process_dict(result: ProcessResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["limits"] = asdict(result.limits)
    if result.spawn_error is not None:
        payload["spawn_error"] = asdict(result.spawn_error)
    return payload


class AcceptanceService:
    """The deterministic acceptance engine; all collaborators injectable."""

    def __init__(
        self,
        *,
        architecture_loader: Callable[[Path], Any] | None = None,
        command_runner: Any | None = None,
        assertion_registry: AssertionEvaluatorRegistry | None = None,
        test_evidence_registry: TestEvidenceProviderRegistry | None = None,
        runtime_session_registry: RuntimeSessionRegistry | None = None,
    ) -> None:
        if architecture_loader is None:
            from specify_cli.architecture import load_architecture

            architecture_loader = load_architecture
        self._load_architecture = architecture_loader
        self._runner = command_runner or LocalCommandRunner()
        self._assertions = assertion_registry or create_default_assertion_registry()
        self._test_evidence = test_evidence_registry or create_default_test_evidence_registry()
        if runtime_session_registry is None:
            from specify_cli.acceptance.runtime_lifecycle.registry import create_default_runtime_session_registry

            runtime_session_registry = create_default_runtime_session_registry()
        self._runtime_sessions = runtime_session_registry

    def run(self, project_root: Path, scope: AcceptanceScope) -> AcceptanceReport:
        report = AcceptanceReport(
            version=ACCEPTANCE_REPORT_VERSION,
            scope=_scope_dict(scope),
            root=str(project_root),
            applicable=True,
            passed=False,
            gates=_gates_skeleton(),
        )

        architecture, stop = self._architecture_gate(project_root, report)
        if stop or architecture is None:
            return report

        resolution = resolve_validation_inventory(architecture.project, str(project_root), scope)
        if not resolution.declared:
            diagnostic = AcceptanceDiagnostic(
                code="acceptance_not_applicable_no_executable_validations",
                message=(
                    "The architecture spec declares neither project completion checks nor attached "
                    "test/runtime validations; executable acceptance gates are not applicable."
                ),
                path="project",
                severity="info",
            )
            report.gates["validations"]["diagnostics"] = [diagnostic.to_dict()]
            report.diagnostics = [diagnostic.to_dict()]
            report.applicable = False
            report.passed = True
            return report

        gate = report.gates["validations"]
        gate["declaredProjectChecks"] = resolution.project_check_reference_count
        gate["applicableAttachedTests"] = resolution.applicable_attached_test_count
        gate["applicableAttachedRuntimeSessions"] = resolution.applicable_attached_runtime_session_count
        gate["resolved"] = len(resolution.checks)

        if any(d.severity == "error" for d in resolution.diagnostics):
            gate["status"] = "failed"
            gate["diagnostics"] = [d.to_dict() for d in resolution.diagnostics]
            report.diagnostics = [d.to_dict() for d in resolution.diagnostics]
            return report

        checks = [self._execute_check(check) for check in resolution.checks]
        report.checks = checks
        failures = [
            AcceptanceDiagnostic(
                code="validation_failed",
                message=f"Validation '{check['id']}' failed.",
                path=f"checks.{check['id']}",
            ).to_dict()
            for check in checks
            if not check["passed"]
        ]
        gate["executed"] = len(checks)
        gate["status"] = "passed" if not failures else "failed"
        gate["diagnostics"] = failures
        report.diagnostics = failures
        report.passed = not failures
        return report

    def _architecture_gate(self, project_root: Path, report: AcceptanceReport) -> tuple[Any, bool]:
        """Populate the architecture gate.

        Returns ``(architecture, stop)``: ``stop`` is True when the gate failed
        or reported not-applicable and ``run`` must return the report as-is.
        """
        try:
            architecture = self._load_architecture(project_root)
        except Exception as cause:
            diagnostic = AcceptanceDiagnostic(
                code="architecture_evaluation_failed", message=str(cause), path=str(project_root)
            )
            report.gates["architecture"] = {"status": "failed", "files": [], "diagnostics": [diagnostic.to_dict()]}
            report.diagnostics = [diagnostic.to_dict()]
            return None, True
        if architecture is None:
            diagnostic = AcceptanceDiagnostic(
                code="acceptance_not_applicable_no_architecture",
                message="No architecture spec is present; deterministic acceptance gates are not applicable.",
                severity="info",
            )
            report.gates["architecture"] = {
                "status": "not_applicable",
                "files": [],
                "diagnostics": [diagnostic.to_dict()],
            }
            report.diagnostics = [diagnostic.to_dict()]
            report.applicable = False
            report.passed = True
            return None, True
        report.gates["architecture"] = {
            "status": "passed",
            "root": str(architecture.root),
            "files": [str(f) for f in architecture.files],
            "diagnostics": [],
        }
        return architecture, False

    def _run_check_process(
        self, check: ResolvedValidation, request: ProcessExecutionRequest
    ) -> tuple[ProcessResult, dict[str, Any] | None]:
        """Returns (process result, runtime-session evidence or None)."""
        proof = check.proof or {}
        if proof.get("type") != "runtime-session":
            try:
                return self._runner.run(request), None
            except Exception as cause:
                return _unexpected_process_result(request, cause), None

        provider_name = str(proof.get("provider", ""))
        provider = self._runtime_sessions.get(provider_name)
        if provider is None:
            message = f"No runtime-session provider is registered for '{provider_name}'."
            return _unexpected_process_result(request, RuntimeError(message)), {
                "provider": provider_name,
                "status": "failed",
                "diagnostics": [
                    AcceptanceDiagnostic(
                        code="runtime_session_provider_unsupported", message=message, path="proof.provider"
                    ).to_dict()
                ],
            }
        try:
            result = provider.run(check=check, request=request)
            return result.process, result.runtime_session
        except Exception as cause:
            message = f"Runtime-session provider '{provider_name}' failed unexpectedly: {cause}"
            return _unexpected_process_result(request, RuntimeError(message)), {
                "provider": provider_name,
                "status": "failed",
                "diagnostics": [
                    AcceptanceDiagnostic(
                        code="runtime_session_provider_failed", message=message, path="proof.provider"
                    ).to_dict()
                ],
            }

    def _execute_check(self, check: ResolvedValidation) -> dict[str, Any]:
        request = ProcessExecutionRequest(
            command=list(check.argv),
            working_directory=check.cwd,
            limits=RunnerLimits(
                timeout_ms=check.limits.timeout_ms,
                stdout_bytes=check.limits.stdout_bytes,
                stderr_bytes=check.limits.stderr_bytes,
            ),
        )
        process, runtime_session = self._run_check_process(check, request)
        proof = check.proof or {}
        is_runtime = proof.get("type") == "runtime-session"

        process_diagnostic = None if is_runtime else _process_failure_diagnostic(process)
        process_passed = (
            process.termination == "exited" and process.exit_code == proof.get("requireExitCode", 0)
            if is_runtime
            else process_diagnostic is None
        )

        assertion_results = evaluate_assertions(list(check.assertions), process, self._assertions)
        assertions_passed = all(result.passed for result in assertion_results)

        test_evidence = None
        if proof.get("type") == "test-suite":
            suite_proof = TestSuiteProof(
                provider=proof["provider"],
                minimum_executed=proof["minimumExecuted"],
                selector=proof["selector"],
                options=proof.get("options", {}),
                role=proof.get("role"),
            )
            test_evidence = extract_test_evidence(suite_proof, process, self._test_evidence)

        diagnostics: list[dict[str, Any]] = []
        if process_diagnostic:
            diagnostics.append(process_diagnostic.to_dict())
        diagnostics.extend(d.to_dict() for d in assertion_diagnostics(assertion_results))
        if test_evidence:
            diagnostics.extend(d.to_dict() for d in test_evidence.diagnostics)
        if runtime_session:
            diagnostics.extend(runtime_session.get("diagnostics", []))

        passed = (
            process_passed
            and assertions_passed
            and (test_evidence is None or test_evidence.status == "passed")
            and (runtime_session is None or runtime_session.get("status") == "passed")
        )

        payload: dict[str, Any] = {
            "id": check.id,
            "declaration": asdict(check.declaration),
            "applicability": {"mode": check.applicability.mode, "changes": list(check.applicability.changes)},
            "process": _process_dict(process),
            "processPassed": process_passed,
            "assertions": [asdict(result) for result in assertion_results],
            "assertionsPassed": assertions_passed,
            "passed": passed,
            "diagnostics": diagnostics,
        }
        if check.proof_role:
            payload["proofRole"] = check.proof_role
        if check.proof:
            payload["proof"] = {"type": proof.get("type"), "provider": proof.get("provider")}
        if test_evidence:
            payload["testEvidence"] = {
                "provider": test_evidence.provider,
                "status": test_evidence.status,
                "evidence": test_evidence.evidence,
                "diagnostics": [d.to_dict() for d in test_evidence.diagnostics],
            }
        if runtime_session:
            payload["runtimeSession"] = runtime_session
        return payload
