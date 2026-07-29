"""Unit tests for deterministic test-evidence extraction and core validation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from specify_cli.acceptance.deterministic.process_runner import ProcessLimits, ProcessResult
from specify_cli.acceptance.deterministic.test_evidence import (
    JUNIT_XML_TEST_EVIDENCE_PROVIDER,
    STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
    TestEvidenceProviderRegistry,
    TestSuiteProof,
    create_default_test_evidence_registry,
    extract_test_evidence,
)

pytestmark = pytest.mark.unit

# Production classes whose names start with Test*; keep pytest from trying to collect them.
TestSuiteProof.__test__ = False  # type: ignore[attr-defined]
TestEvidenceProviderRegistry.__test__ = False  # type: ignore[attr-defined]

_SELECTOR = {"suite": "unit", "paths": ["tests/unit"]}
_LIMITS = ProcessLimits(timeout_ms=1000, stdout_bytes=1024, stderr_bytes=1024)


def _process(stdout: str = "", stderr: str = "", working_directory: str = "/tmp") -> ProcessResult:
    return ProcessResult(
        command=["pytest"],
        working_directory=working_directory,
        limits=_LIMITS,
        duration_ms=10,
        termination="exited",
        exit_code=0,
        signal=None,
        timed_out=False,
        stdout=stdout,
        stderr=stderr,
    )


def _proof(
    provider: str = STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
    minimum_executed: int = 1,
    selector: Any = None,
    options: dict[str, Any] | None = None,
) -> TestSuiteProof:
    return TestSuiteProof(
        provider=provider,
        minimum_executed=minimum_executed,
        selector=_SELECTOR if selector is None else selector,
        options={"stream": "stdout"} if options is None else options,
    )


def _document(**overrides: Any) -> str:
    document = {
        "selector": _SELECTOR,
        "discovered": 5,
        "executed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 1,
        "source": {"tool": "pytest", "command": "pytest tests/unit"},
    }
    document.update(overrides)
    return json.dumps(document)


def _codes(result) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def _extract(stdout: str, proof: TestSuiteProof | None = None):
    return extract_test_evidence(proof or _proof(), _process(stdout=stdout), create_default_test_evidence_registry())


class TestStructuredJsonProvider:
    def test_happy_path(self):
        result = _extract(_document())

        assert result.status == "passed"
        assert result.diagnostics == []
        assert result.evidence is not None
        assert result.evidence["provider"] == STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER
        assert result.evidence["executed"] == 4
        assert result.evidence["source"]["kind"] == "process-stream"
        assert result.evidence["source"]["stream"] == "stdout"
        assert result.evidence["source"]["report"] == {"tool": "pytest", "command": "pytest tests/unit"}

    def test_reads_from_stderr_when_configured(self):
        proof = _proof(options={"stream": "stderr"})
        result = extract_test_evidence(proof, _process(stderr=_document()), create_default_test_evidence_registry())
        assert result.status == "passed"
        assert result.evidence["source"]["stream"] == "stderr"

    def test_zero_executed_triggers_minimum_not_met(self):
        result = _extract(_document(discovered=0, executed=0, passed=0, failed=0, skipped=0))
        assert result.status == "failed"
        assert _codes(result) == ["test_evidence_minimum_not_met"]

    def test_below_declared_minimum(self):
        result = _extract(_document(), proof=_proof(minimum_executed=10))
        assert "test_evidence_minimum_not_met" in _codes(result)

    def test_failed_tests_rejected(self):
        result = _extract(_document(passed=3, failed=1))
        assert result.status == "failed"
        assert "test_evidence_failed_tests" in _codes(result)

    def test_selector_mismatch(self):
        result = _extract(_document(selector={"suite": "other"}))
        assert result.status == "failed"
        assert "test_evidence_selector_mismatch" in _codes(result)

    def test_selector_match_ignores_key_order(self):
        reordered = {"paths": ["tests/unit"], "suite": "unit"}
        result = _extract(_document(selector=reordered))
        assert result.status == "passed"

    def test_inconsistent_counts(self):
        result = _extract(_document(passed=3, failed=0))
        assert result.status == "failed"
        assert "test_evidence_inconsistent" in _codes(result)

    def test_discovered_less_than_executed_is_inconsistent(self):
        result = _extract(_document(discovered=2))
        assert "test_evidence_inconsistent" in _codes(result)

    def test_non_integer_count_is_malformed(self):
        result = _extract(_document(executed="four"))
        assert result.status == "failed"
        assert "test_evidence_malformed" in _codes(result)

    def test_malformed_json_stream_is_provider_error(self):
        result = _extract("this is {not json")
        assert result.status == "failed"
        assert _codes(result) == ["test_evidence_provider_error"]

    def test_two_json_documents_rejected(self):
        result = _extract(_document() + "\n" + _document())
        assert _codes(result) == ["test_evidence_provider_error"]

    def test_empty_stream_is_provider_error(self):
        result = _extract("   ")
        assert _codes(result) == ["test_evidence_provider_error"]
        assert "stream is empty" in result.diagnostics[0].message

    def test_invalid_stream_option_is_provider_error(self):
        result = _extract(_document(), proof=_proof(options={"stream": "both"}))
        assert _codes(result) == ["test_evidence_provider_error"]


class TestCoreEnforcement:
    def test_unsupported_provider(self):
        result = _extract(_document(), proof=_proof(provider="no-such-provider"))
        assert result.status == "failed"
        assert _codes(result) == ["test_evidence_provider_unsupported"]
        assert "no-such-provider" in result.diagnostics[0].message

    def test_provider_mismatch_label_detected_by_core(self):
        class _Mislabeled:
            id = "stub-v1"

            def extract(self, proof, process):
                return {"provider": "someone-else", "selector": proof.selector, "executed": 3, "source": {"tool": "stub"}}

        registry = TestEvidenceProviderRegistry().register(_Mislabeled())
        result = extract_test_evidence(_proof(provider="stub-v1"), _process(), registry)
        assert result.status == "failed"
        assert "test_evidence_provider_mismatch" in _codes(result)

    def test_non_object_return_is_malformed(self):
        class _ListReturner:
            id = "list-v1"

            def extract(self, proof, process):
                return [1, 2, 3]

        registry = TestEvidenceProviderRegistry().register(_ListReturner())
        result = extract_test_evidence(_proof(provider="list-v1"), _process(), registry)
        assert _codes(result) == ["test_evidence_malformed"]
        assert "finite, acyclic JSON object" in result.diagnostics[0].message

    def test_cyclic_return_is_malformed(self):
        class _CycleReturner:
            id = "cycle-v1"

            def extract(self, proof, process):
                evidence: dict[str, Any] = {"provider": self.id, "selector": proof.selector, "executed": 1, "source": {}}
                evidence["loop"] = evidence
                return evidence

        registry = TestEvidenceProviderRegistry().register(_CycleReturner())
        result = extract_test_evidence(_proof(provider="cycle-v1"), _process(), registry)
        assert _codes(result) == ["test_evidence_malformed"]

    def test_provider_exception_is_provider_error(self):
        class _Boom:
            id = "boom-v1"

            def extract(self, proof, process):
                raise RuntimeError("exploded")

        registry = TestEvidenceProviderRegistry().register(_Boom())
        result = extract_test_evidence(_proof(provider="boom-v1"), _process(), registry)
        assert _codes(result) == ["test_evidence_provider_error"]
        assert "exploded" in result.diagnostics[0].message

    def test_duplicate_provider_registration_raises(self):
        registry = create_default_test_evidence_registry()

        class _Duplicate:
            id = STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER

            def extract(self, proof, process):
                raise NotImplementedError

        with pytest.raises(ValueError, match="already registered"):
            registry.register(_Duplicate())

    def test_registry_lists_builtins_sorted(self):
        assert create_default_test_evidence_registry().list() == [
            JUNIT_XML_TEST_EVIDENCE_PROVIDER,
            STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
        ]


_JUNIT_PASSING = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="unit" tests="3">
    <testcase classname="a" name="one"/>
    <testcase classname="a" name="two"/>
    <testcase classname="a" name="three"><skipped message="later"/></testcase>
  </testsuite>
</testsuites>
"""

_JUNIT_FAILING = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="unit" tests="4">
    <testcase classname="a" name="one"/>
    <testcase classname="a" name="two"><failure message="assert failed"/></testcase>
    <testcase classname="a" name="three"><error message="raised"/></testcase>
    <testcase classname="a" name="four"><skipped/></testcase>
  </testsuite>
</testsuites>
"""


class TestJunitXmlProvider:
    def _proof(self, minimum_executed: int = 1) -> TestSuiteProof:
        return _proof(
            provider=JUNIT_XML_TEST_EVIDENCE_PROVIDER,
            minimum_executed=minimum_executed,
            options={"reportPath": "report.xml"},
        )

    def test_happy_path(self, tmp_path):
        (tmp_path / "report.xml").write_text(_JUNIT_PASSING, encoding="utf-8")
        result = extract_test_evidence(
            self._proof(minimum_executed=2),
            _process(working_directory=str(tmp_path)),
            create_default_test_evidence_registry(),
        )

        assert result.status == "passed"
        assert result.diagnostics == []
        assert result.evidence["discovered"] == 3
        assert result.evidence["executed"] == 2
        assert result.evidence["passed"] == 2
        assert result.evidence["failed"] == 0
        assert result.evidence["skipped"] == 1
        assert result.evidence["source"]["kind"] == "junit-xml-report"
        assert result.evidence["source"]["reportPath"] == "report.xml"

    def test_failure_and_error_counts(self, tmp_path):
        (tmp_path / "report.xml").write_text(_JUNIT_FAILING, encoding="utf-8")
        result = extract_test_evidence(
            self._proof(),
            _process(working_directory=str(tmp_path)),
            create_default_test_evidence_registry(),
        )

        assert result.status == "failed"
        assert "test_evidence_failed_tests" in _codes(result)
        assert result.evidence["executed"] == 3  # tests - skipped
        assert result.evidence["failed"] == 2  # failures + errors
        assert result.evidence["passed"] == 1
        assert result.evidence["skipped"] == 1

    def test_missing_report_is_provider_error(self, tmp_path):
        result = extract_test_evidence(
            self._proof(),
            _process(working_directory=str(tmp_path)),
            create_default_test_evidence_registry(),
        )
        assert _codes(result) == ["test_evidence_provider_error"]

    def test_unparseable_report_is_provider_error(self, tmp_path):
        (tmp_path / "report.xml").write_text("<testsuite><unclosed>", encoding="utf-8")
        result = extract_test_evidence(
            self._proof(),
            _process(working_directory=str(tmp_path)),
            create_default_test_evidence_registry(),
        )
        assert _codes(result) == ["test_evidence_provider_error"]

    def test_missing_report_path_option_is_provider_error(self, tmp_path):
        proof = _proof(provider=JUNIT_XML_TEST_EVIDENCE_PROVIDER, options={})
        result = extract_test_evidence(proof, _process(working_directory=str(tmp_path)), create_default_test_evidence_registry())
        assert _codes(result) == ["test_evidence_provider_error"]
        assert "reportPath" in result.diagnostics[0].message
