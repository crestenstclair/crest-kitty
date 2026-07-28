"""Unit tests for the deterministic acceptance assertion evaluators."""

from __future__ import annotations

import pytest

from specify_cli.acceptance.deterministic.assertions import (
    AssertionEvaluatorRegistry,
    assertion_diagnostics,
    create_default_assertion_registry,
    evaluate_assertions,
)
from specify_cli.acceptance.deterministic.process_runner import (
    ProcessLimits,
    ProcessResult,
    ProcessSpawnError,
)

pytestmark = pytest.mark.unit

_LIMITS = ProcessLimits(timeout_ms=1000, stdout_bytes=1024, stderr_bytes=1024)


def _process(
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    termination: str = "exited",
    spawn_error: ProcessSpawnError | None = None,
) -> ProcessResult:
    return ProcessResult(
        command=["echo"],
        working_directory="/tmp",
        limits=_LIMITS,
        duration_ms=5,
        termination=termination,
        exit_code=exit_code,
        signal=None,
        timed_out=False,
        spawn_error=spawn_error,
        stdout=stdout,
        stderr=stderr,
    )


def _one(declaration, process):
    results = evaluate_assertions([declaration], process, create_default_assertion_registry())
    assert len(results) == 1
    return results[0]


class TestExitCode:
    def test_passes_on_matching_code(self):
        result = _one({"type": "exit-code", "equals": 0}, _process(exit_code=0))
        assert result.passed is True
        assert result.expected == 0
        assert result.observed == 0
        assert result.diagnostic is None

    def test_fails_on_mismatched_code(self):
        result = _one({"type": "exit-code", "equals": 0}, _process(exit_code=2))
        assert result.passed is False
        assert result.diagnostic is not None
        assert result.diagnostic.code == "assertion_failed"
        assert "Expected exit code 0, observed 2." in result.diagnostic.message

    def test_reports_none_for_missing_exit_code(self):
        result = _one({"type": "exit-code", "equals": 0}, _process(exit_code=None, termination="signaled"))
        assert result.passed is False
        assert "observed none" in result.diagnostic.message

    @pytest.mark.parametrize("equals", ["0", None, 1.5, True])
    def test_malformed_equals_fails_closed(self, equals):
        result = _one({"type": "exit-code", "equals": equals}, _process(exit_code=0))
        assert result.passed is False
        assert result.diagnostic.code == "assertion_malformed"


class TestStreamContains:
    @pytest.mark.parametrize(
        ("type_", "stdout", "stderr", "should_pass"),
        [
            ("stdout-contains", "hello world", "", True),
            ("stdout-contains", "goodbye", "", False),
            ("stdout-not-contains", "goodbye", "", True),
            ("stdout-not-contains", "hello world", "", False),
            ("stderr-contains", "", "hello error", True),
            ("stderr-contains", "", "clean", False),
            ("stderr-not-contains", "", "clean", True),
            ("stderr-not-contains", "", "hello error", False),
        ],
    )
    def test_contains_variants(self, type_, stdout, stderr, should_pass):
        result = _one({"type": type_, "value": "hello"}, _process(stdout=stdout, stderr=stderr))
        assert result.passed is should_pass
        if should_pass:
            assert result.diagnostic is None
        else:
            assert result.diagnostic.code == "assertion_failed"

    def test_failure_message_names_stream_and_condition(self):
        result = _one({"type": "stderr-not-contains", "value": "boom"}, _process(stderr="boom"))
        assert result.diagnostic.message == "Expected stderr to not contain the declared value."

    @pytest.mark.parametrize("value", [42, None, ["x"], {"v": 1}])
    def test_malformed_value_fails_closed(self, value):
        result = _one({"type": "stdout-contains", "value": value}, _process(stdout="anything"))
        assert result.passed is False
        assert result.diagnostic.code == "assertion_malformed"


class TestFailClosed:
    def test_unsupported_type_fails_closed(self):
        result = _one({"type": "regex-matches", "value": "x"}, _process())
        assert result.passed is False
        assert result.diagnostic.code == "assertion_unsupported"
        assert "regex-matches" in result.diagnostic.message

    def test_missing_type_fails_closed(self):
        result = _one({"value": "x"}, _process())
        assert result.passed is False
        assert result.diagnostic.code == "assertion_unsupported"

    def test_evaluator_exception_fails_closed(self):
        class _Boom:
            type = "boom"

            def evaluate(self, declaration, process, index):
                raise RuntimeError("kaput")

        registry = create_default_assertion_registry().register(_Boom())
        results = evaluate_assertions([{"type": "boom"}], _process(), registry)
        assert results[0].passed is False
        assert results[0].diagnostic.code == "assertion_evaluator_error"
        assert "kaput" in results[0].diagnostic.message

    def test_all_assertions_evaluated_after_process_failure(self):
        failed_process = _process(
            exit_code=None,
            termination="spawn_error",
            spawn_error=ProcessSpawnError(message="no such file", code="ENOENT"),
        )
        declarations = [
            {"type": "exit-code", "equals": 0},
            {"type": "stdout-contains", "value": "ok"},
            {"type": "stderr-not-contains", "value": "err"},
            {"type": "unknown-type"},
            {"type": "exit-code", "equals": "bad"},
        ]
        results = evaluate_assertions(declarations, failed_process, create_default_assertion_registry())

        assert [result.index for result in results] == [1, 2, 3, 4, 5]
        # stderr-not-contains legitimately passes against the empty stream.
        assert [result.passed for result in results] == [False, False, True, False, False]


class TestRegistry:
    def test_default_registry_lists_builtins_sorted(self):
        assert create_default_assertion_registry().list() == [
            "exit-code",
            "stderr-contains",
            "stderr-not-contains",
            "stdout-contains",
            "stdout-not-contains",
        ]

    def test_duplicate_registration_raises(self):
        registry = create_default_assertion_registry()
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_stub("exit-code"))

    def test_empty_type_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            AssertionEvaluatorRegistry().register(_stub("   "))


def _stub(type_: str):
    class _Stub:
        type = type_

        def evaluate(self, declaration, process, index):
            raise NotImplementedError

    return _Stub()


def test_assertion_diagnostics_collects_only_failures():
    process = _process(stdout="ok", exit_code=0)
    declarations = [
        {"type": "exit-code", "equals": 0},
        {"type": "stdout-contains", "value": "missing"},
        {"type": "nope"},
    ]
    results = evaluate_assertions(declarations, process, create_default_assertion_registry())
    diagnostics = assertion_diagnostics(results)

    assert [diagnostic.code for diagnostic in diagnostics] == ["assertion_failed", "assertion_unsupported"]
