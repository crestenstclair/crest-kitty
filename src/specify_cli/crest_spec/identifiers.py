"""Canonical resource IDs and suffix-reference resolution.

Every resource in the spec has a canonical dotted ID
(``valueObject.Control.PatchControlId``, ``goal.play_test_song``). Authors
reference resources by the shortest dot-suffix that resolves uniquely;
fields with a known target kind resolve within that kind only. Ambiguity is
a fail-closed diagnostic, never a guess.
"""

from __future__ import annotations

from .diagnostics import CrestSpecDiagnostic

# Terse section name -> canonical ID kind for context resource sections.
CONTEXT_RESOURCE_KINDS: dict[str, str] = {
    "valueObjects": "valueObject",
    "aggregates": "aggregate",
    "ports": "port",
    "repositories": "repository",
    "domainServices": "domainService",
    "applicationServices": "applicationService",
}

# Reference fields whose targets are a single known kind.
TYPED_REFERENCE_FIELDS: dict[str, str] = {
    "goals": "goal",
    "requiredGoals": "goal",
    "goal": "goal",
    "capabilities": "capability",
    "capability": "capability",
    "requirements": "requirement",
    "actors": "actor",
    "actor": "actor",
    "projectChecks": "validation",
}

# Reference fields resolved against every declared ID. These may also carry
# non-reference type expressions (`Vec<String>`); an unresolved value in one of
# these fields is left verbatim rather than diagnosed.
GENERIC_REFERENCE_FIELDS: frozenset[str] = frozenset(
    {"implements", "resources", "repairResources", "targets", "uses", "consumes", "publishes"}
)


class IdentifierIndex:
    """All declared canonical IDs, queryable by kind, with suffix resolution."""

    def __init__(self) -> None:
        self._all: set[str] = set()
        self._by_kind: dict[str, set[str]] = {}

    def declare(self, canonical_id: str) -> bool:
        """Register an ID; returns False when it was already declared."""
        if canonical_id in self._all:
            return False
        self._all.add(canonical_id)
        self._by_kind.setdefault(canonical_id.split(".", 1)[0], set()).add(canonical_id)
        return True

    def scope(self, kind: str | None) -> set[str]:
        if kind is None:
            return self._all
        return self._by_kind.get(kind, set())

    def matches(self, reference: str, kind: str | None) -> list[str]:
        scope = self.scope(kind)
        return sorted(
            i for i in scope if i == reference or i.endswith("." + reference)
        )


class ReferenceResolver:
    """Expands suffix references, collecting diagnostics instead of raising."""

    def __init__(self, index: IdentifierIndex):
        self._index = index
        self.diagnostics: list[CrestSpecDiagnostic] = []

    def resolve(self, reference: str, kind: str | None, *, file: str, required: bool) -> str:
        matches = self._index.matches(reference, kind)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            self.diagnostics.append(
                CrestSpecDiagnostic(
                    code="crest_spec_ambiguous_reference",
                    message=(
                        f"reference {reference!r} matches multiple declared IDs: "
                        + ", ".join(matches[:6])
                        + " — qualify it with more of the dotted path"
                    ),
                    file=file,
                )
            )
            return reference
        if required:
            self.diagnostics.append(
                CrestSpecDiagnostic(
                    code="crest_spec_unresolved_reference",
                    message=(
                        f"reference {reference!r} does not resolve to any declared "
                        + (f"{kind} ID" if kind else "ID")
                    ),
                    file=file,
                )
            )
        return reference
