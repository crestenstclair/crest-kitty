"""Assertion evaluation for the deterministic acceptance engine.

Port of ``research/crestopenspec-port/reference-assertions.ts``. Every declared
assertion is evaluated — even after the process itself failed — and every
abnormal condition (unsupported type, malformed declaration, evaluator
exception) produces a *failed* outcome instead of raising: the engine fails
closed. Diagnostic ``code`` strings are a portable contract with the
TypeScript implementation and must not be changed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from specify_cli.acceptance.deterministic.model import AcceptanceDiagnostic
from specify_cli.acceptance.deterministic.process_runner import ProcessResult

@dataclass(frozen=True)
class AssertionResult:
    """Outcome of one declared assertion (mirrors the TS AssertionOutcome shape)."""

    index: int
    type: str
    passed: bool
    expected: Any = None
    observed: Any = None
    diagnostic: AcceptanceDiagnostic | None = None


class AssertionEvaluator(Protocol):
    """One assertion type: a ``type`` string plus a pure evaluate function."""

    type: str

    def evaluate(self, declaration: Mapping[str, Any], process: ProcessResult, index: int) -> AssertionResult: ...


class AssertionEvaluatorRegistry:
    """Registry of assertion evaluators keyed by their declared type."""

    def __init__(self) -> None:
        self._evaluators: dict[str, AssertionEvaluator] = {}

    def register(self, evaluator: AssertionEvaluator) -> AssertionEvaluatorRegistry:
        """Register an evaluator; empty or duplicate types are programmer errors."""
        if not evaluator.type.strip():
            raise ValueError("Assertion evaluator type must not be empty.")
        if evaluator.type in self._evaluators:
            raise ValueError(f"Assertion evaluator '{evaluator.type}' is already registered.")
        self._evaluators[evaluator.type] = evaluator
        return self

    def get(self, type_: str) -> AssertionEvaluator | None:
        return self._evaluators.get(type_)

    def list(self) -> list[str]:
        return sorted(self._evaluators)


def _failed(index: int, type_: str, code: str, message: str, expected: Any = None, observed: Any = None) -> AssertionResult:
    return AssertionResult(
        index=index,
        type=type_,
        passed=False,
        expected=expected,
        observed=observed,
        diagnostic=AcceptanceDiagnostic(severity="error", code=code, message=message),
    )


def _is_integer(value: Any) -> bool:
    # bool is an int subclass in Python; the TS contract requires a real integer.
    return isinstance(value, int) and not isinstance(value, bool)


class _ExitCodeEvaluator:
    """``exit-code``: process exit code equals the declared integer."""

    type = "exit-code"

    def evaluate(self, declaration: Mapping[str, Any], process: ProcessResult, index: int) -> AssertionResult:
        expected = declaration.get("equals")
        if not _is_integer(expected):
            return _failed(
                index,
                self.type,
                "assertion_malformed",
                f"Assertion {index} ({self.type}) requires an integer 'equals' value.",
                observed=process.exit_code,
            )
        if process.exit_code == expected:
            return AssertionResult(index=index, type=self.type, passed=True, expected=expected, observed=process.exit_code)
        observed_text = "none" if process.exit_code is None else process.exit_code
        return _failed(
            index,
            self.type,
            "assertion_failed",
            f"Expected exit code {expected}, observed {observed_text}.",
            expected=expected,
            observed=process.exit_code,
        )


@dataclass(frozen=True)
class _StreamContainsEvaluator:
    """``{stream}-contains`` / ``{stream}-not-contains`` substring assertions."""

    type: str
    stream: str
    negated: bool

    def evaluate(self, declaration: Mapping[str, Any], process: ProcessResult, index: int) -> AssertionResult:
        expected = declaration.get("value")
        if not isinstance(expected, str):
            return _failed(index, self.type, "assertion_malformed", f"Assertion {index} ({self.type}) requires a string 'value'.")
        contains = expected in getattr(process, self.stream)
        passed = not contains if self.negated else contains
        if passed:
            return AssertionResult(index=index, type=self.type, passed=True, expected=expected, observed=contains)
        condition = "not contain" if self.negated else "contain"
        return _failed(
            index,
            self.type,
            "assertion_failed",
            f"Expected {self.stream} to {condition} the declared value.",
            expected=expected,
            observed=contains,
        )


def create_default_assertion_registry() -> AssertionEvaluatorRegistry:
    """Registry with the five built-in assertion types."""
    return (
        AssertionEvaluatorRegistry()
        .register(_ExitCodeEvaluator())
        .register(_StreamContainsEvaluator("stdout-contains", "stdout", negated=False))
        .register(_StreamContainsEvaluator("stdout-not-contains", "stdout", negated=True))
        .register(_StreamContainsEvaluator("stderr-contains", "stderr", negated=False))
        .register(_StreamContainsEvaluator("stderr-not-contains", "stderr", negated=True))
    )


def evaluate_assertions(
    declarations: Sequence[Mapping[str, Any]],
    process: ProcessResult,
    registry: AssertionEvaluatorRegistry,
) -> list[AssertionResult]:
    """Evaluate every declaration against the process result; never raises."""
    results: list[AssertionResult] = []
    for offset, declaration in enumerate(declarations):
        index = offset + 1
        raw_type = declaration.get("type")
        type_ = raw_type if isinstance(raw_type, str) else str(raw_type)
        evaluator = registry.get(raw_type) if isinstance(raw_type, str) else None
        if evaluator is None:
            results.append(_failed(index, type_, "assertion_unsupported", f"No assertion evaluator is registered for '{type_}'."))
            continue
        try:
            results.append(evaluator.evaluate(declaration, process, index))
        except Exception as error:  # fail closed: an evaluator bug is a failed assertion
            results.append(_failed(index, type_, "assertion_evaluator_error", f"Assertion evaluator '{type_}' failed: {error}"))
    return results


def assertion_diagnostics(results: Sequence[AssertionResult]) -> list[AcceptanceDiagnostic]:
    """Collect the diagnostics attached to failed assertion results."""
    return [result.diagnostic for result in results if result.diagnostic is not None]
