"""Top-level architecture spec loading.

``load_architecture(project_root)`` resolves the spec root (default
``.kittify/architecture``, configurable via ``architecture.root`` in
``.kittify/config.yaml``), parses every ``*.yaml`` beneath it with the
duplicate-key-rejecting parser, expands the terse tree into the canonical
``project`` mapping, and derives the relationship index.

Returns ``None`` when the spec directory is absent or holds no YAML files —
architecture-dependent behavior is opt-in by authoring the spec. Any defect in
a present spec raises :class:`ArchitectureSpecError` (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .diagnostics import ArchitectureDiagnostic, ArchitectureSpecError
from .expansion import expand_project
from .relationships import Relationship, build_relationships
from .yaml_io import DuplicateKeyError, load_yaml_strict

DEFAULT_ARCHITECTURE_ROOT = Path(".kittify") / "architecture"


@dataclass(frozen=True)
class Architecture:
    """A transient, expanded view of the architecture spec.

    The YAML tree remains the source of truth; this object exists only while
    spec-kitty assembles context or evaluates acceptance.
    """

    root: Path
    files: list[Path]
    project: dict[str, Any]
    relationships: list[Relationship]


def resolve_architecture_root(project_root: Path) -> Path:
    """The configured (or default) architecture spec directory, absolute."""
    configured = _configured_root(project_root)
    root = Path(configured) if configured else DEFAULT_ARCHITECTURE_ROOT
    if not root.is_absolute():
        root = project_root / root
    return root


def _configured_root(project_root: Path) -> str | None:
    """Best-effort read of ``architecture.root`` from ``.kittify/config.yaml``.

    Mirrors the ``review:`` section read pattern: a missing file, malformed
    YAML, or absent section all degrade to the default rather than erroring —
    the spec directory itself is the opt-in signal.
    """
    config_path = project_root / ".kittify" / "config.yaml"
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    section = loaded.get("architecture") if isinstance(loaded, dict) else None
    root = section.get("root") if isinstance(section, dict) else None
    return root if isinstance(root, str) and root else None


def _parse_files(root: Path) -> tuple[dict[str, Any], list[Path], list[ArchitectureDiagnostic]]:
    files: dict[str, Any] = {}
    paths: list[Path] = []
    diagnostics: list[ArchitectureDiagnostic] = []
    for path in sorted(root.rglob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        try:
            files[rel] = load_yaml_strict(path.read_text(encoding="utf-8"))
        except OSError as error:
            diagnostics.append(
                ArchitectureDiagnostic("architecture_unreadable", str(error), file=rel)
            )
            continue
        except DuplicateKeyError as error:
            diagnostics.append(
                ArchitectureDiagnostic("architecture_duplicate_key", str(error), file=rel)
            )
            continue
        except yaml.YAMLError as error:
            diagnostics.append(
                ArchitectureDiagnostic("architecture_invalid_yaml", str(error), file=rel)
            )
            continue
        paths.append(path)
    return files, paths, diagnostics


def load_architecture(project_root: Path) -> Architecture | None:
    """Load and expand the project's architecture spec, fail-closed.

    Ordinary reads only: nothing here executes declared commands.
    """
    root = resolve_architecture_root(project_root)
    if not root.is_dir():
        return None

    files, paths, diagnostics = _parse_files(root)
    if not files and not diagnostics:
        return None
    project = expand_project(files, diagnostics)
    if diagnostics:
        raise ArchitectureSpecError(diagnostics)
    return Architecture(
        root=root.resolve(),
        files=[p.resolve() for p in paths],
        project=project,
        relationships=build_relationships(project),
    )
