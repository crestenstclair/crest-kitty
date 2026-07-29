"""Executable derivation gates: everything derives FROM the crest-spec.

The crest-spec is the bedrock — resources declare what exists, ``assets``
declare the files that realize them, ``proof`` declares what must be true.
These gates make that direction enforceable instead of aspirational:

- **Plan gate** (:func:`check_plan_derivation`): a mission that declares
  structural change cannot advance planning while the crest-spec is untouched
  — the mission *begins* by editing the crest-spec.
- **Implement gate** (:func:`check_wp_derivation`): a work package whose
  ``owned_files`` are not covered by a declared asset's file pattern is
  refused with ``crest_spec_underived`` — if the crest-spec does not declare
  it, it does not get built.
- **Accept proof gate** (:func:`check_added_resource_proof`): behavioral
  resources added by the mission with no declared proof (validation, witness,
  or acceptance scenario) block with ``crest_spec_unproven``.
- **Duplicate-artifact guard** (:func:`forbidden_duplicate_artifacts`):
  ``data-model.md`` / ``contracts/`` are forbidden when a crest-spec exists —
  they are hand-copied, immediately-stale forks of ``valueObjects``,
  ``aggregates``, and ``ports``.

Every gate is fail-closed on an invalid crest-spec and not-applicable when no
crest-spec exists. Missions that genuinely change no structure opt out with
``crest_spec_impact: none`` in ``meta.json`` — an explicit declaration, never
a silent default (non-vacuous gate discipline).

Ordinary reads only: nothing here executes declared commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .diagnostics import CrestSpecError
from .loader import CrestSpec, load_crest_spec, resolve_crest_spec_root

# meta.json key declaring how a mission relates to the crest-spec.
CREST_SPEC_IMPACT_KEY = "crest_spec_impact"
IMPACT_STRUCTURAL = "structural"  # this mission edits the crest-spec
IMPACT_PREDECLARED = "predeclared"  # a prior mission already declared this work
IMPACT_NONE = "none"  # no structural change (doc fix, flaky-test repair, ...)
_VALID_IMPACTS = (IMPACT_STRUCTURAL, IMPACT_PREDECLARED, IMPACT_NONE)

# Behavioral resource sections inside a bounded context: these carry commands,
# operations, or contracts, so adding one adds behavior that needs proof.
_BEHAVIORAL_SECTIONS = {
    "aggregates": "aggregate",
    "ports": "port",
    "domainServices": "domainService",
    "applicationServices": "applicationService",
}

_UNDECLARED_IMPACT_ERROR = (
    "crest_spec_impact_undeclared: this project has a crest-spec, so meta.json "
    f"must declare {CREST_SPEC_IMPACT_KEY}: one of {', '.join(_VALID_IMPACTS)}. "
    "'structural' = this mission edits the crest-spec first; 'predeclared' = "
    "the crest-spec already declares this mission's work; 'none' = no system "
    "structure changes (doc fix, test repair)."
)


@dataclass(frozen=True)
class DerivationGateResult:
    """Outcome of a crest-spec derivation gate check."""

    passed: bool
    applicable: bool
    errors: list[str] = field(default_factory=list)


def _pass(applicable: bool = True) -> DerivationGateResult:
    return DerivationGateResult(passed=True, applicable=applicable)


def _fail(errors: list[str]) -> DerivationGateResult:
    return DerivationGateResult(passed=False, applicable=True, errors=errors)


def load_crest_spec_or_error(repo_root: Path) -> tuple[CrestSpec | None, str | None]:
    """Load the crest-spec; an invalid spec is an error string (fail closed)."""
    try:
        return load_crest_spec(repo_root), None
    except CrestSpecError as error:
        detail = "; ".join(d.render() for d in error.diagnostics[:3])
        return None, (
            "crest_spec_invalid: the crest-spec failed to load and every "
            f"derivation gate fails closed: {detail}. Repair it (see "
            "`spec-kitty crest-spec doctor`)."
        )


def read_mission_impact(feature_dir: Path) -> str | None:
    """The mission's declared ``crest_spec_impact``, or ``None`` when absent."""
    from specify_cli.mission_metadata import load_meta

    meta = load_meta(feature_dir)
    if meta is None:
        return None
    impact = meta.get(CREST_SPEC_IMPACT_KEY)
    return impact if isinstance(impact, str) and impact else None


def _impact_gate(feature_dir: Path) -> tuple[str | None, list[str]]:
    """Resolve the declared impact; absent or invalid is an explicit error."""
    impact = read_mission_impact(feature_dir)
    if impact is None:
        return None, [_UNDECLARED_IMPACT_ERROR]
    if impact not in _VALID_IMPACTS:
        return None, [
            f"crest_spec_impact_undeclared: {CREST_SPEC_IMPACT_KEY} is "
            f"{impact!r}; expected one of {', '.join(_VALID_IMPACTS)}."
        ]
    return impact, []


def asset_file_patterns(project: dict[str, Any]) -> list[str]:
    """File patterns of every asset kind that has at least one declared asset.

    An asset's produced files are identified by its kind's ``filePattern`` —
    the declared generation universe work packages must trace into.
    """
    kinds = project.get("assetKinds", {})
    assets = project.get("assets", {})
    declared_kinds = {
        asset.get("kind")
        for asset in assets.values()
        if isinstance(asset, dict) and asset.get("kind")
    }
    patterns = []
    for kind_name, kind in kinds.items():
        if kind_name not in declared_kinds or not isinstance(kind, dict):
            continue
        pattern = kind.get("filePattern")
        if isinstance(pattern, str) and pattern:
            patterns.append(pattern)
    return sorted(set(patterns))


def _is_exempt_owned_file(path: str, spec_root_rel: str) -> bool:
    """Mission bookkeeping and crest-spec edits are never gated by assets."""
    return path.startswith(("kitty-specs/", f"{spec_root_rel.rstrip('/')}/"))


def uncovered_owned_files(
    project: dict[str, Any], owned_files: list[str], *, spec_root_rel: str
) -> list[str]:
    """Owned files no declared asset covers (order-preserving, deduplicated)."""
    patterns = asset_file_patterns(project)
    uncovered: list[str] = []
    for raw in dict.fromkeys(owned_files):
        path = raw.strip()
        while path.startswith("./"):
            path = path[2:]
        if not path or _is_exempt_owned_file(path, spec_root_rel):
            continue
        if not any(fnmatchcase(path, pattern) for pattern in patterns):
            uncovered.append(path)
    return uncovered


def _wp_owned_files(wp_file: Path) -> list[str]:
    from specify_cli.frontmatter import read_frontmatter

    frontmatter, _body = read_frontmatter(wp_file)
    owned = frontmatter.get("owned_files")
    if not isinstance(owned, list):
        return []
    return [item for item in owned if isinstance(item, str)]


def _spec_root_rel(repo_root: Path) -> str:
    root = resolve_crest_spec_root(repo_root)
    try:
        return root.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return root.as_posix()


def check_wp_derivation(
    repo_root: Path, feature_dir: Path, wp_file: Path
) -> DerivationGateResult:
    """Implement gate: refuse a WP whose owned files no asset declares.

    ``crest_spec_underived`` means the crest-spec does not declare the files
    this work package intends to produce. The remedy is to declare the asset
    (and, if needed, its asset kind's ``filePattern``) in the crest-spec —
    never to hand-author the intent into the WP prompt.
    """
    spec, error = load_crest_spec_or_error(repo_root)
    if error is not None:
        return _fail([error])
    if spec is None:
        return _pass(applicable=False)

    impact, impact_errors = _impact_gate(feature_dir)
    if impact_errors:
        return _fail(impact_errors)
    if impact == IMPACT_NONE:
        return _pass()

    uncovered = uncovered_owned_files(
        spec.project, _wp_owned_files(wp_file), spec_root_rel=_spec_root_rel(repo_root)
    )
    if uncovered:
        return _fail(
            [
                "crest_spec_underived: no declared crest-spec asset covers "
                f"{', '.join(uncovered)}. Work packages are derived from "
                "assets[] — declare an asset (and assetKind filePattern) for "
                "these files in the crest-spec, or set "
                f"{CREST_SPEC_IMPACT_KEY}: none if this mission changes no "
                "structure."
            ]
        )
    return _pass()


def crest_spec_diff_paths(repo_root: Path, base_ref: str) -> list[str]:
    """Crest-spec paths changed vs *base_ref*, committed or in the worktree."""
    from specify_cli.core.vcs.git import merge_base_changed_files
    from specify_cli.task_utils import run_git

    spec_rel = _spec_root_rel(repo_root)
    changed = {
        line.strip()
        for line in merge_base_changed_files(repo_root, base_ref, pathspec=spec_rel)
        if line.strip()
    }
    status = run_git(
        ["status", "--porcelain", "--", spec_rel], cwd=repo_root, check=False
    )
    if status.returncode == 0:
        for line in status.stdout.splitlines():
            path = line[3:].strip()
            if path:
                changed.add(path)
    return sorted(changed)


def check_plan_derivation(
    repo_root: Path, feature_dir: Path, base_ref: str | None
) -> DerivationGateResult:
    """Plan gate: structural missions must have touched the crest-spec.

    The mission begins by changing the crest-spec; planning derives from it.
    A structural mission whose diff (against *base_ref*, plus the working
    tree) contains no crest-spec change has skipped its bedrock step.
    """
    spec, error = load_crest_spec_or_error(repo_root)
    if error is not None:
        return _fail([error])
    if spec is None:
        return _pass(applicable=False)

    impact, impact_errors = _impact_gate(feature_dir)
    if impact_errors:
        return _fail(impact_errors)
    if impact in (IMPACT_NONE, IMPACT_PREDECLARED):
        return _pass()

    if base_ref and not crest_spec_diff_paths(repo_root, base_ref):
        return _fail(
            [
                "crest_spec_unchanged: this mission declares "
                f"{CREST_SPEC_IMPACT_KEY}: structural but the crest-spec is "
                "untouched. Author the crest-spec first — the mission begins "
                "there (add/change/retire the resources, assets, and proof), "
                "then derive the plan. If the crest-spec already declares "
                f"this work, set {CREST_SPEC_IMPACT_KEY}: predeclared."
            ]
        )
    return _pass()


def _resource_ids(project: dict[str, Any]) -> set[str]:
    """Canonical IDs of behavioral resources + capabilities in a model."""
    ids: set[str] = set()
    for name in project.get("capabilities", {}):
        ids.add(f"capability.{name}")
    for context_name, context in project.get("contexts", {}).items():
        if not isinstance(context, dict):
            continue
        for section, kind in _BEHAVIORAL_SECTIONS.items():
            entries = context.get(section)
            if isinstance(entries, dict):
                ids.update(f"{kind}.{context_name}.{name}" for name in entries)
    return ids


def _proof_covered_ids(project: dict[str, Any]) -> set[str]:
    """Every canonical ID referenced by any declared proof surface."""
    covered: set[str] = set()
    for validation in project.get("validations", {}).values():
        if isinstance(validation, dict):
            covered.update(validation.get("resources") or [])
            covered.update(validation.get("capabilities") or [])
    for witness in project.get("witnesses", {}).values():
        if isinstance(witness, dict):
            covered.update(witness.get("resources") or [])
            capability = witness.get("capability")
            if isinstance(capability, str):
                covered.add(capability)
    for name, capability in project.get("capabilities", {}).items():
        if isinstance(capability, dict) and capability.get("acceptance"):
            covered.add(f"capability.{name}")
    for context_name, context in project.get("contexts", {}).items():
        if not isinstance(context, dict):
            continue
        covered.update(_attached_validation_ids(context_name, context))
    return covered


def _attached_validation_ids(context_name: str, context: dict[str, Any]) -> set[str]:
    """IDs of context resources carrying their own attached ``validations``."""
    covered: set[str] = set()
    for section, kind in _BEHAVIORAL_SECTIONS.items():
        entries = context.get(section)
        if not isinstance(entries, dict):
            continue
        for name, resource in entries.items():
            if isinstance(resource, dict) and resource.get("validations"):
                covered.add(f"{kind}.{context_name}.{name}")
    return covered


def _base_project(repo_root: Path, base_ref: str) -> dict[str, Any] | None:
    """Expand the crest-spec as committed at *base_ref*; ``None`` if absent/bad.

    A missing or unloadable base model means "no incremental comparison is
    possible" — adoption missions are governed by the deterministic
    acceptance arming rules instead, so the proof gate skips rather than
    demanding proof for the entire model at once.
    """
    from specify_cli.task_utils import run_git

    from .expansion import expand_project
    from .yaml_io import load_yaml_strict

    spec_rel = _spec_root_rel(repo_root)
    listing = run_git(
        ["ls-tree", "-r", "--name-only", base_ref, "--", spec_rel],
        cwd=repo_root,
        check=False,
    )
    if listing.returncode != 0:
        return None
    paths = [p for p in listing.stdout.splitlines() if p.strip().endswith(".yaml")]
    if not paths:
        return None

    files: dict[str, Any] = {}
    for path in paths:
        blob = run_git(["show", f"{base_ref}:{path}"], cwd=repo_root, check=False)
        if blob.returncode != 0:
            return None
        rel = path[len(spec_rel) + 1 :] if path.startswith(f"{spec_rel}/") else path
        try:
            files[rel] = load_yaml_strict(blob.stdout)
        except Exception:  # noqa: BLE001 — any defect: base model unusable, skip
            return None
    diagnostics: list[Any] = []
    project = expand_project(files, diagnostics)
    return None if diagnostics else project


def check_added_resource_proof(
    repo_root: Path, feature_dir: Path, base_ref: str | None
) -> DerivationGateResult:
    """Accept gate: behavior added by this mission must carry declared proof.

    Compares the crest-spec's behavioral resources + capabilities at
    *base_ref* against the working tree; every added ID must be covered by a
    validation, a witness, an attached validation, or (for capabilities) an
    acceptance scenario. Otherwise ``crest_spec_unproven``.
    """
    spec, error = load_crest_spec_or_error(repo_root)
    if error is not None:
        return _fail([error])
    if spec is None or not base_ref:
        return _pass(applicable=spec is not None)

    impact = read_mission_impact(feature_dir)
    if impact == IMPACT_NONE:
        return _pass()

    base = _base_project(repo_root, base_ref)
    if base is None:
        return _pass()

    added = _resource_ids(spec.project) - _resource_ids(base)
    unproven = sorted(added - _proof_covered_ids(spec.project))
    if unproven:
        return _fail(
            [
                "crest_spec_unproven: this mission adds behavior with no "
                f"declared proof: {', '.join(unproven)}. Declare a validation "
                "or witness covering each (or an acceptance scenario for a "
                "capability) in the crest-spec's proof model — proof is "
                "declared where the behavior is declared, not improvised at "
                "review."
            ]
        )
    return _pass()


def forbidden_duplicate_artifacts(feature_dir: Path) -> list[str]:
    """Planning artifacts that fork the crest-spec (forbidden when it exists).

    ``data-model.md`` duplicates ``valueObjects``/``aggregates``;
    ``contracts/`` duplicates ``ports[].contract`` and the proof model. When a
    crest-spec exists the plan points at canonical resources instead.
    """
    found: list[str] = []
    if (feature_dir / "data-model.md").is_file():
        found.append("data-model.md")
    contracts = feature_dir / "contracts"
    if contracts.is_dir() and any(contracts.iterdir()):
        found.append("contracts/")
    return found


# __all__ lists only the gate entry points src/ consumers import (symbol-level
# dead-code gate, FR-303); the result dataclass, impact constants, and pure
# helpers stay importable for tests without being declared public surface.
__all__ = [
    "check_added_resource_proof",
    "check_plan_derivation",
    "check_wp_derivation",
    "forbidden_duplicate_artifacts",
]
