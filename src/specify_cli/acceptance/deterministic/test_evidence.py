"""Test-suite evidence extraction and validation for the deterministic acceptance engine.

Port of ``research/crestopenspec-port/reference-test-evidence.ts``. Providers
only *extract* an evidence document; the core (:func:`extract_test_evidence` +
:func:`validate_test_evidence`) enforces the trust rules — count sanity, zero
failures, minimum-executed, selector identity — so a buggy or malicious
provider cannot self-certify. Diagnostic ``code`` strings are a portable
contract with the TypeScript implementation and must not be changed.

Built-in providers:

- ``structured-json-v1``: parses exactly one complete JSON document from the
  configured process stream.
- ``junit-xml-v1`` (Python-side addition): parses a JUnit XML report file
  relative to the check working directory.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from specify_cli.acceptance.deterministic.assertions import AcceptanceDiagnostic
from specify_cli.acceptance.deterministic.process_runner import ProcessResult

STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER = "structured-json-v1"
JUNIT_XML_TEST_EVIDENCE_PROVIDER = "junit-xml-v1"


@dataclass(frozen=True)
class TestSuiteProof:
    """A declared test-suite proof: which provider must produce evidence, and the floor it must clear."""

    provider: str
    minimum_executed: int
    selector: Any
    options: Mapping[str, Any] = field(default_factory=dict)
    role: str | None = None
    type: str = "test-suite"


@dataclass(frozen=True)
class TestEvidenceResult:
    """Core verdict over one proof: the evidence (if extracted) plus diagnostics."""

    provider: str
    minimum_executed: int
    selector: Any
    status: str  # 'passed' | 'failed'
    diagnostics: list[AcceptanceDiagnostic]
    evidence: dict[str, Any] | None = None


class TestEvidenceProvider(Protocol):
    """Extracts a raw evidence document; the core validates it afterwards."""

    id: str

    def extract(self, proof: TestSuiteProof, process: ProcessResult) -> dict[str, Any]: ...


class TestEvidenceProviderRegistry:
    """Registry of test-evidence providers keyed by provider id."""

    def __init__(self) -> None:
        self._providers: dict[str, TestEvidenceProvider] = {}

    def register(self, provider: TestEvidenceProvider) -> TestEvidenceProviderRegistry:
        """Register a provider; empty or duplicate ids are programmer errors."""
        if not provider.id.strip():
            raise ValueError("Test-evidence provider ID must not be empty.")
        if provider.id in self._providers:
            raise ValueError(f"Test-evidence provider '{provider.id}' is already registered.")
        self._providers[provider.id] = provider
        return self

    def get(self, provider_id: str) -> TestEvidenceProvider | None:
        return self._providers.get(provider_id)

    def list(self) -> list[str]:
        return sorted(self._providers)


def _is_json_object(value: Any) -> bool:
    # Plain dict only, mirroring the TS plain-object prototype check.
    return type(value) is dict


def _is_json_safe_value(value: Any, ancestors: set[int] | None = None) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if type(value) not in (dict, list):
        return False
    if ancestors is None:
        ancestors = set()
    if id(value) in ancestors:
        return False
    ancestors.add(id(value))
    if isinstance(value, list):
        safe = all(_is_json_safe_value(entry, ancestors) for entry in value)
    else:
        safe = all(isinstance(key, str) and _is_json_safe_value(entry, ancestors) for key, entry in value.items())
    ancestors.discard(id(value))
    return safe


def _is_json_safe_evidence(value: Any) -> bool:
    return _is_json_object(value) and _is_json_safe_value(value)


def _selectors_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    except (TypeError, ValueError):
        return False


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _error(code: str, message: str, path: str) -> AcceptanceDiagnostic:
    return AcceptanceDiagnostic(severity="error", code=code, message=message, path=path)


def _count_field_diagnostics(evidence: Mapping[str, Any]) -> list[AcceptanceDiagnostic]:
    diagnostics: list[AcceptanceDiagnostic] = []
    for field_name in ("discovered", "executed", "passed", "failed", "skipped"):
        required = field_name == "executed"
        if (required or field_name in evidence) and not _is_nonnegative_integer(evidence.get(field_name)):
            suffix = "" if required else " when present"
            diagnostics.append(
                _error("test_evidence_malformed", f"Test evidence '{field_name}' must be a nonnegative integer{suffix}.", f"testEvidence.{field_name}")
            )
    return diagnostics


def _identity_diagnostics(evidence: Mapping[str, Any], proof: TestSuiteProof) -> list[AcceptanceDiagnostic]:
    diagnostics: list[AcceptanceDiagnostic] = []
    if evidence.get("provider") != proof.provider:
        diagnostics.append(
            _error(
                "test_evidence_provider_mismatch",
                f"Provider '{proof.provider}' returned evidence labeled '{evidence.get('provider')}'.",
                "testEvidence.provider",
            )
        )
    if "selector" not in evidence or not _selectors_equal(evidence["selector"], proof.selector):
        diagnostics.append(
            _error("test_evidence_selector_mismatch", "Test evidence selector does not match the exact validation declaration.", "testEvidence.selector")
        )
    if not _is_json_object(evidence.get("source")):
        diagnostics.append(_error("test_evidence_malformed", "Test evidence must include a structured source explanation.", "testEvidence.source"))
    return diagnostics


def _consistency_diagnostics(evidence: Mapping[str, Any], executed: int) -> list[AcceptanceDiagnostic]:
    diagnostics: list[AcceptanceDiagnostic] = []
    passed = evidence.get("passed")
    failed = evidence.get("failed")
    discovered = evidence.get("discovered")
    skipped = evidence.get("skipped")

    if _is_nonnegative_integer(passed) and passed > executed:
        diagnostics.append(_error("test_evidence_inconsistent", f"Passed count {passed} exceeds executed count {executed}.", "testEvidence.passed"))
    if _is_nonnegative_integer(failed) and failed > executed:
        diagnostics.append(_error("test_evidence_inconsistent", f"Failed count {failed} exceeds executed count {executed}.", "testEvidence.failed"))
    if _is_nonnegative_integer(passed) and _is_nonnegative_integer(failed) and passed + failed != executed:
        diagnostics.append(
            _error("test_evidence_inconsistent", f"Passed ({passed}) plus failed ({failed}) must equal executed ({executed}).", "testEvidence")
        )
    if _is_nonnegative_integer(failed) and failed > 0:
        diagnostics.append(_error("test_evidence_failed_tests", f"Test evidence reports {failed} failed test(s).", "testEvidence.failed"))
    if _is_nonnegative_integer(discovered) and discovered < executed:
        diagnostics.append(
            _error("test_evidence_inconsistent", f"Discovered count {discovered} is less than executed count {executed}.", "testEvidence.discovered")
        )
    if _is_nonnegative_integer(discovered) and _is_nonnegative_integer(skipped) and discovered < executed + skipped:
        diagnostics.append(
            _error(
                "test_evidence_inconsistent",
                f"Discovered count {discovered} is less than executed plus skipped ({executed + skipped}).",
                "testEvidence.discovered",
            )
        )
    return diagnostics


def validate_test_evidence(evidence: Mapping[str, Any], proof: TestSuiteProof) -> list[AcceptanceDiagnostic]:
    """Core enforcement of the evidence trust rules; returns error diagnostics."""
    diagnostics = _count_field_diagnostics(evidence)
    diagnostics.extend(_identity_diagnostics(evidence, proof))

    executed = evidence.get("executed")
    if not _is_nonnegative_integer(executed):
        return diagnostics

    diagnostics.extend(_consistency_diagnostics(evidence, executed))
    if executed < proof.minimum_executed:
        diagnostics.append(
            _error(
                "test_evidence_minimum_not_met",
                f"Executed {executed} test(s); at least {proof.minimum_executed} must execute.",
                "testEvidence.executed",
            )
        )
    return diagnostics


class _StructuredJsonProvider:
    """``structured-json-v1``: one complete JSON evidence document on a process stream."""

    id = STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER

    def extract(self, proof: TestSuiteProof, process: ProcessResult) -> dict[str, Any]:
        stream = proof.options.get("stream")
        if stream not in ("stdout", "stderr"):
            raise ValueError("Option 'stream' must be exactly 'stdout' or 'stderr'.")
        document = getattr(process, stream).strip()
        if not document:
            raise ValueError(f"The selected {stream} stream is empty.")
        try:
            parsed = json.loads(document)
        except ValueError as error:
            raise ValueError(f"The selected {stream} stream is not one JSON document: {error}") from error
        if not _is_json_object(parsed):
            raise ValueError("The structured test-evidence document must be a JSON object.")
        if not _is_json_object(parsed.get("source")):
            raise ValueError("The structured test-evidence document requires an object-valued 'source'.")
        if "selector" not in parsed:
            raise ValueError("The structured test-evidence document requires a 'selector'.")

        evidence: dict[str, Any] = {"provider": self.id, "selector": parsed["selector"]}
        if "discovered" in parsed:
            evidence["discovered"] = parsed["discovered"]
        evidence["executed"] = parsed.get("executed")
        for key in ("passed", "failed", "skipped"):
            if key in parsed:
                evidence[key] = parsed[key]
        evidence["source"] = {"kind": "process-stream", "stream": stream, "format": self.id, "report": parsed["source"]}
        return evidence


class _JunitXmlProvider:
    """``junit-xml-v1``: evidence from a JUnit XML report file.

    ``options.reportPath`` is resolved relative to the check working
    directory. Counts follow the repo's JUnit idiom (per-testcase iteration,
    nested suites included): executed = tests - skipped, failed = failures +
    errors. The report format carries no selector, so the declared selector is
    echoed; selector identity for this provider attests to the report only.
    """

    id = JUNIT_XML_TEST_EVIDENCE_PROVIDER

    def extract(self, proof: TestSuiteProof, process: ProcessResult) -> dict[str, Any]:
        report_path = proof.options.get("reportPath")
        if not isinstance(report_path, str) or not report_path.strip():
            raise ValueError("Option 'reportPath' must be a non-empty string.")
        resolved = Path(process.working_directory) / report_path
        try:
            root = ET.parse(str(resolved)).getroot()  # noqa: S314 — report comes from local test-runner output, not network input
        except (OSError, ET.ParseError) as error:
            raise ValueError(f"Cannot parse JUnit report '{report_path}': {error}") from error

        total = failed = skipped = 0
        for testcase in root.iter("testcase"):
            total += 1
            if testcase.find("failure") is not None or testcase.find("error") is not None:
                failed += 1
            elif testcase.find("skipped") is not None:
                skipped += 1
        executed = total - skipped
        return {
            "provider": self.id,
            "selector": proof.selector,
            "discovered": total,
            "executed": executed,
            "passed": executed - failed,
            "failed": failed,
            "skipped": skipped,
            "source": {"kind": "junit-xml-report", "format": self.id, "reportPath": report_path, "tests": total},
        }


def create_default_test_evidence_registry() -> TestEvidenceProviderRegistry:
    """Registry with the built-in structured-json-v1 and junit-xml-v1 providers."""
    return TestEvidenceProviderRegistry().register(_StructuredJsonProvider()).register(_JunitXmlProvider())


def _failed_result(proof: TestSuiteProof, diagnostic: AcceptanceDiagnostic) -> TestEvidenceResult:
    return TestEvidenceResult(
        provider=proof.provider,
        minimum_executed=proof.minimum_executed,
        selector=proof.selector,
        status="failed",
        diagnostics=[diagnostic],
    )


def extract_test_evidence(proof: TestSuiteProof, process: ProcessResult, registry: TestEvidenceProviderRegistry) -> TestEvidenceResult:
    """Run the declared provider and validate its evidence; never raises."""
    provider = registry.get(proof.provider)
    if provider is None:
        return _failed_result(
            proof,
            _error("test_evidence_provider_unsupported", f"No test-evidence provider is registered for '{proof.provider}'.", "proof.provider"),
        )

    try:
        extracted = provider.extract(proof, process)
    except Exception as error:  # fail closed: a provider bug is failed evidence
        return _failed_result(
            proof,
            _error("test_evidence_provider_error", f"Test-evidence provider '{proof.provider}' failed: {error}", "proof.provider"),
        )

    if not _is_json_safe_evidence(extracted):
        return _failed_result(
            proof,
            _error(
                "test_evidence_malformed",
                f"Test-evidence provider '{proof.provider}' returned a value that is not a finite, acyclic JSON object.",
                "testEvidence",
            ),
        )

    diagnostics = validate_test_evidence(extracted, proof)
    return TestEvidenceResult(
        provider=proof.provider,
        minimum_executed=proof.minimum_executed,
        selector=proof.selector,
        status="failed" if any(diagnostic.severity == "error" for diagnostic in diagnostics) else "passed",
        diagnostics=diagnostics,
        evidence=extracted,
    )
