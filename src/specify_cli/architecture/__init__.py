"""Project architecture spec: loading, expansion, and rendering.

The architecture spec is the terse, ID-referenced multi-file YAML tree living
at ``.kittify/architecture/`` (path configurable via ``architecture.root`` in
``.kittify/config.yaml``). The loader expands it into the canonical ``project``
mapping that every downstream consumer (context injection, relationship index,
acceptance inventory) reads. Format reference:
``research/crestopenspec-port/spec-format-README.md``.

Absence of the spec directory is not an error — ``load_architecture`` returns
``None`` and architecture-dependent gates report not-applicable. Every defect
inside a present spec fails closed with structured diagnostics.
"""

from __future__ import annotations

from .contract import ARCHITECTURE_INTERPRETATION_CONTRACT, render_architecture_context
from .diagnostics import ArchitectureDiagnostic, ArchitectureSpecError
from .loader import Architecture, load_architecture, resolve_architecture_root
from .relationships import Relationship, build_relationships

__all__ = [
    "ARCHITECTURE_INTERPRETATION_CONTRACT",
    "Architecture",
    "ArchitectureDiagnostic",
    "ArchitectureSpecError",
    "Relationship",
    "build_relationships",
    "load_architecture",
    "render_architecture_context",
    "resolve_architecture_root",
]
