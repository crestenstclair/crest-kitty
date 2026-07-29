"""Shared data model for the deterministic acceptance engine.

Ported from CrestOpenSpec ``src/core/acceptance/types.ts`` (reference copy at
``research/crestopenspec-port/reference-types.ts``). Diagnostic codes and shapes
are a portable contract — keep them verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 3.0: the report's ``architecture`` gate key became ``crest_spec`` and the
# ``architecture_*`` diagnostic codes became ``crest_spec_*`` (crest-spec
# bedrock rename). Everything else is shape-identical to 2.0.
ACCEPTANCE_REPORT_VERSION = "3.0"

ACCEPTANCE_PROOF_ROLES = frozenset(
    {
        "target-reachability",
        "static-validation",
        "in-process-behavior",
        "external-process-lifecycle",
        "production-composition-runtime",
    }
)


@dataclass(frozen=True)
class AcceptanceDiagnostic:
    """One acceptance-engine diagnostic (mirrors the TS AcceptanceDiagnostic)."""

    code: str
    message: str
    path: str | None = None
    severity: str = "error"
    fix: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path
        if self.fix is not None:
            payload["fix"] = self.fix
        return payload


@dataclass(frozen=True)
class AcceptanceScope:
    """What is being accepted: one mission, or the whole project.

    Mirrors upstream's change/project scope; crest-kitty's unit of change is
    the mission, and declaration files keep the upstream ``mode: changes`` /
    ``changes: [...]`` spelling (the listed IDs are mission slugs here).
    """

    mode: Literal["mission", "project"]
    mission: str | None = None


@dataclass(frozen=True)
class ProcessLimits:
    timeout_ms: int
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class ValidationApplicability:
    mode: str  # "project-check" | "always" | "changes"
    changes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationDeclarationRef:
    kind: str  # "project_check" | "attached_test" | "attached_runtime"
    location: str
    owner: str


@dataclass(frozen=True)
class ResolvedValidation:
    """One fully-validated, executable acceptance check."""

    id: str
    declaration: ValidationDeclarationRef
    argv: tuple[str, ...]
    cwd: str
    limits: ProcessLimits
    assertions: tuple[dict[str, Any], ...]
    applicability: ValidationApplicability
    proof_role: str | None = None
    proof: dict[str, Any] | None = None


@dataclass
class ValidationInventory:
    """The resolved inventory: what acceptance would execute, or why not."""

    declared: bool
    project_check_reference_count: int = 0
    applicable_attached_test_count: int = 0
    applicable_attached_runtime_session_count: int = 0
    checks: list[ResolvedValidation] = field(default_factory=list)
    diagnostics: list[AcceptanceDiagnostic] = field(default_factory=list)
