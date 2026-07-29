"""Project crest-spec: loading, expansion, and rendering.

The crest-spec is the bedrock declaration of what the system is: the terse,
ID-referenced multi-file YAML tree living at ``.kittify/crest-spec/`` (path
configurable via ``crest_spec.root`` in ``.kittify/config.yaml``). Planning,
work decomposition, code generation, and proof all derive FROM it. The loader
expands it into the canonical ``project`` mapping that every downstream
consumer (context injection, relationship index, acceptance inventory,
derivation gates) reads. Format reference:
``research/crestopenspec-port/spec-format-README.md``.

Absence of the crest-spec directory is not an error — ``load_crest_spec``
returns ``None`` and crest-spec-dependent gates report not-applicable. Every
defect inside a present crest-spec fails closed with structured diagnostics.
"""

from __future__ import annotations

from .contract import CREST_SPEC_INTERPRETATION_CONTRACT, render_crest_spec_context
from .diagnostics import CrestSpecDiagnostic, CrestSpecError
from .loader import CrestSpec, load_crest_spec, resolve_crest_spec_root
from .relationships import Relationship, build_relationships

__all__ = [
    "CREST_SPEC_INTERPRETATION_CONTRACT",
    "CrestSpec",
    "CrestSpecDiagnostic",
    "CrestSpecError",
    "Relationship",
    "build_relationships",
    "load_crest_spec",
    "render_crest_spec_context",
    "resolve_crest_spec_root",
]
