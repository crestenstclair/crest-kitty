"""Structured, fail-closed diagnostics for the crest-spec loader."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrestSpecDiagnostic:
    """One defect found while loading or expanding the crest-spec."""

    code: str
    message: str
    file: str | None = None

    def render(self) -> str:
        location = f" [{self.file}]" if self.file else ""
        return f"{self.code}{location}: {self.message}"


class CrestSpecError(Exception):
    """Raised when a present crest-spec cannot be loaded fail-closed.

    Carries every diagnostic collected before the loader gave up, so callers
    (doctor, acceptance) can report all defects at once instead of the first.
    """

    def __init__(self, diagnostics: list[CrestSpecDiagnostic]):
        self.diagnostics = diagnostics
        super().__init__(
            "crest-spec failed to load: "
            + "; ".join(d.render() for d in diagnostics[:5])
            + (f" (+{len(diagnostics) - 5} more)" if len(diagnostics) > 5 else "")
        )
