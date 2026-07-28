"""Deterministic acceptance engine ported from CrestOpenSpec (research/crestopenspec-port/).

Three cooperating modules: bounded process execution (``process_runner``),
fail-closed assertion evaluation (``assertions``), and core-enforced
test-suite evidence (``test_evidence``).
"""

from __future__ import annotations

from specify_cli.acceptance.deterministic.assertions import (
    AcceptanceDiagnostic,
    AssertionEvaluator,
    AssertionEvaluatorRegistry,
    AssertionResult,
    assertion_diagnostics,
    create_default_assertion_registry,
    evaluate_assertions,
)
from specify_cli.acceptance.deterministic.process_runner import (
    MAX_ACCEPTANCE_STREAM_BYTES,
    MAX_ACCEPTANCE_TIMEOUT_MS,
    LocalCommandRunner,
    ProcessExecutionRequest,
    ProcessLimits,
    ProcessResult,
    ProcessSpawnError,
)
from specify_cli.acceptance.deterministic.test_evidence import (
    JUNIT_XML_TEST_EVIDENCE_PROVIDER,
    STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
    TestEvidenceProvider,
    TestEvidenceProviderRegistry,
    TestEvidenceResult,
    TestSuiteProof,
    create_default_test_evidence_registry,
    extract_test_evidence,
    validate_test_evidence,
)

__all__ = [
    "JUNIT_XML_TEST_EVIDENCE_PROVIDER",
    "MAX_ACCEPTANCE_STREAM_BYTES",
    "MAX_ACCEPTANCE_TIMEOUT_MS",
    "STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER",
    "AcceptanceDiagnostic",
    "AssertionEvaluator",
    "AssertionEvaluatorRegistry",
    "AssertionResult",
    "LocalCommandRunner",
    "ProcessExecutionRequest",
    "ProcessLimits",
    "ProcessResult",
    "ProcessSpawnError",
    "TestEvidenceProvider",
    "TestEvidenceProviderRegistry",
    "TestEvidenceResult",
    "TestSuiteProof",
    "assertion_diagnostics",
    "create_default_assertion_registry",
    "create_default_test_evidence_registry",
    "evaluate_assertions",
    "extract_test_evidence",
    "validate_test_evidence",
]
