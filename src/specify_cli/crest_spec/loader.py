"""Top-level crest-spec loading.

``load_crest_spec(project_root)`` resolves the crest-spec root (default
``.kittify/crest-spec``, configurable via ``crest_spec.root`` in
``.kittify/config.yaml``), parses every ``*.yaml`` beneath it with the
duplicate-key-rejecting parser, expands the terse tree into the canonical
``project`` mapping, and derives the relationship index.

Returns ``None`` when the crest-spec directory is absent or holds no YAML
files — crest-spec-dependent behavior is opt-in by authoring the crest-spec.
Any defect in a present crest-spec raises :class:`CrestSpecError` (fail
closed).

Legacy layout (pre-rename ``.kittify/architecture`` / ``architecture.root``)
is a fail-loud error, never a silent fallback: the crest-spec has exactly one
name and one home, and a stale layout must be migrated, not quietly read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .diagnostics import CrestSpecDiagnostic, CrestSpecError
from .expansion import expand_project
from .relationships import Relationship, build_relationships
from .yaml_io import DuplicateKeyError, load_yaml_strict

DEFAULT_CREST_SPEC_ROOT = Path(".kittify") / "crest-spec"

# The pre-rename home. Its presence is a migration error (fail-loud), never a
# fallback read location.
LEGACY_CREST_SPEC_ROOT = Path(".kittify") / "architecture"


@dataclass(frozen=True)
class CrestSpec:
    """A transient, expanded view of the crest-spec.

    The YAML tree remains the source of truth; this object exists only while
    spec-kitty assembles context or evaluates acceptance.
    """

    root: Path
    files: list[Path]
    project: dict[str, Any]
    relationships: list[Relationship]


def resolve_crest_spec_root(project_root: Path) -> Path:
    """The configured (or default) crest-spec directory, absolute."""
    configured = _configured_root(project_root, "crest_spec")
    root = Path(configured) if configured else DEFAULT_CREST_SPEC_ROOT
    if not root.is_absolute():
        root = project_root / root
    return root


def _configured_root(project_root: Path, section_key: str) -> str | None:
    """Best-effort read of ``<section_key>.root`` from ``.kittify/config.yaml``.

    Mirrors the ``review:`` section read pattern: a missing file, malformed
    YAML, or absent section all degrade to the default rather than erroring —
    the crest-spec directory itself is the opt-in signal.
    """
    config_path = project_root / ".kittify" / "config.yaml"
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    section = loaded.get(section_key) if isinstance(loaded, dict) else None
    root = section.get("root") if isinstance(section, dict) else None
    return root if isinstance(root, str) and root else None


def _legacy_layout_diagnostics(project_root: Path) -> list[CrestSpecDiagnostic]:
    """Detect the retired ``architecture`` naming; each hit is fail-loud.

    No silent fallback: a legacy directory or config key means the operator
    must migrate (one ``git mv`` / one config-key rename), and every consumer
    (context, doctor, acceptance, archive) reports the same instruction.
    """
    diagnostics: list[CrestSpecDiagnostic] = []
    legacy_dir = project_root / LEGACY_CREST_SPEC_ROOT
    if legacy_dir.is_dir():
        diagnostics.append(
            CrestSpecDiagnostic(
                "crest_spec_legacy_root",
                "the crest-spec now lives at .kittify/crest-spec/ — rename the "
                "legacy directory: git mv .kittify/architecture .kittify/crest-spec",
                file=str(LEGACY_CREST_SPEC_ROOT),
            )
        )
    if _configured_root(project_root, "architecture"):
        diagnostics.append(
            CrestSpecDiagnostic(
                "crest_spec_legacy_config",
                "the config key architecture.root was renamed to crest_spec.root — "
                "update .kittify/config.yaml",
                file=".kittify/config.yaml",
            )
        )
    return diagnostics


def _parse_files(root: Path) -> tuple[dict[str, Any], list[Path], list[CrestSpecDiagnostic]]:
    files: dict[str, Any] = {}
    paths: list[Path] = []
    diagnostics: list[CrestSpecDiagnostic] = []
    for path in sorted(root.rglob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        try:
            files[rel] = load_yaml_strict(path.read_text(encoding="utf-8"))
        except OSError as error:
            diagnostics.append(
                CrestSpecDiagnostic("crest_spec_unreadable", str(error), file=rel)
            )
            continue
        except DuplicateKeyError as error:
            diagnostics.append(
                CrestSpecDiagnostic("crest_spec_duplicate_key", str(error), file=rel)
            )
            continue
        except yaml.YAMLError as error:
            diagnostics.append(
                CrestSpecDiagnostic("crest_spec_invalid_yaml", str(error), file=rel)
            )
            continue
        paths.append(path)
    return files, paths, diagnostics


def load_crest_spec(project_root: Path) -> CrestSpec | None:
    """Load and expand the project's crest-spec, fail-closed.

    Ordinary reads only: nothing here executes declared commands.
    """
    legacy = _legacy_layout_diagnostics(project_root)
    if legacy:
        raise CrestSpecError(legacy)

    root = resolve_crest_spec_root(project_root)
    if not root.is_dir():
        return None

    files, paths, diagnostics = _parse_files(root)
    if not files and not diagnostics:
        return None
    project = expand_project(files, diagnostics)
    if diagnostics:
        raise CrestSpecError(diagnostics)
    return CrestSpec(
        root=root.resolve(),
        files=[p.resolve() for p in paths],
        project=project,
        relationships=build_relationships(project),
    )
