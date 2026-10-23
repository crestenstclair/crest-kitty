"""Migration: install the vendored code-quality skills for existing projects.

``adversarial-review`` and ``writing-clean-code`` are vendored into the doctrine
layer from an external repository (see each skill's ``VENDORED.md``). They are
invoked by ``spec-kitty-mission-review`` Step 8.75 and by the crest-spec
authoring phase respectively.

Neither name starts with ``spk-``, so
:class:`~specify_cli.upgrade.migrations.m_3_2_0rc35_spk_skill_pack.SpkSkillPackMigration`
does not detect them: its ``detect()`` filters the registry to ``spk-*`` and
reports "nothing missing" once the public pack is present. Its migration ID is
also already stamped in every upgraded project, and the runner skips applied
IDs. A project upgraded past 3.2.0rc35 would therefore never receive these two
skills without this migration.

``apply()`` delegates to ``install_all_skills``, which installs the *entire*
canonical registry — not just the two vendored skills. That is deliberate: the
installer prunes user-global skill directories that are absent from the list it
is handed (``_remove_retired_skill_dirs``), so handing it a subset would delete
every other installed skill.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from specify_cli.skills.retired import RETIRED_CANONICAL_SKILL_NAMES

from ..registry import MigrationRegistry
from .base import BaseMigration, MigrationResult
from kernel.paths import to_posix

if TYPE_CHECKING:
    from specify_cli.skills.registry import CanonicalSkill, SkillRegistry

#: The vendored skills this migration exists to deliver. Names are upstream and
#: deliberately not ``spk-*`` — see each skill's ``VENDORED.md``.
VENDORED_SKILL_NAMES: tuple[str, ...] = ("adversarial-review", "writing-clean-code")

_TARGET_VERSION = "3.2.6"


def _discover_registry() -> SkillRegistry | None:
    """Resolve canonical skills from the installed package or local checkout."""
    from specify_cli.skills.registry import SkillRegistry
    from specify_cli.template import get_local_repo_root

    try:
        registry = SkillRegistry.from_package()
        if registry.discover_skills():
            return registry
    except Exception:
        pass

    local_repo = get_local_repo_root()
    if local_repo is not None:
        registry = SkillRegistry.from_local_repo(local_repo)
        if registry.discover_skills():
            return registry

    return None


def _installable_agents(project_path: Path) -> list[str]:
    """Return configured agents that accept skill files."""
    from specify_cli.core.agent_config import load_agent_config
    from specify_cli.core.config import AGENT_SKILL_CONFIG, SKILL_CLASS_WRAPPER

    installable: list[str] = []
    for agent_key in load_agent_config(project_path).available:
        config = AGENT_SKILL_CONFIG.get(agent_key)
        if config is None or config["class"] == SKILL_CLASS_WRAPPER:
            continue
        installable.append(agent_key)
    return installable


def _vendored_skills(registry: SkillRegistry) -> list[CanonicalSkill]:
    return [
        skill
        for skill in registry.discover_skills()
        if skill.name in VENDORED_SKILL_NAMES
    ]


def _skill_files_present(
    project_path: Path,
    agent_key: str,
    skills: list[CanonicalSkill],
) -> bool:
    """True when every file of every *skill* is already projected for *agent_key*.

    Checks each file rather than the skill directory: ``adversarial-review``
    ships an ``agents/`` subtree that a project upgraded before that subtree was
    installable would be missing even though its ``SKILL.md`` is present.
    """
    from specify_cli.skills.paths import get_primary_project_skill_root

    root = get_primary_project_skill_root(agent_key)
    if root is None:
        return True

    for skill in skills:
        target_skill_dir = project_path / root / skill.name
        for source_file in skill.all_files:
            rel = source_file.relative_to(skill.skill_dir)
            if not (target_skill_dir / rel).exists():
                return False
    return True


@MigrationRegistry.register
class VendoredReviewSkillsMigration(BaseMigration):
    """Install the vendored code-quality skills for already-initialized projects."""

    migration_id = "3.2.6_vendored_review_skills"
    description = (
        "Install the vendored adversarial-review and writing-clean-code skills"
    )
    target_version = _TARGET_VERSION

    def detect(self, project_path: Path) -> bool:
        if not (project_path / ".kittify").is_dir():
            return False

        registry = _discover_registry()
        if registry is None:
            return False

        skills = _vendored_skills(registry)
        if not skills:
            return False

        agents = _installable_agents(project_path)
        if not agents:
            return False

        return any(
            not _skill_files_present(project_path, agent_key, skills)
            for agent_key in agents
        )

    def can_apply(self, project_path: Path) -> tuple[bool, str]:
        if not (project_path / ".kittify").is_dir():
            return False, ".kittify/ directory does not exist (not initialized)"
        return True, ""

    def apply(self, project_path: Path, dry_run: bool = False) -> MigrationResult:
        from specify_cli.skills.installer import install_all_skills
        from specify_cli.skills.manifest import load_manifest, save_manifest

        changes: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        registry = _discover_registry()
        if registry is None:
            errors.append(
                "No canonical skills discovered for vendored review-skill install"
            )
            return MigrationResult(success=False, changes_made=changes, errors=errors)

        vendored = _vendored_skills(registry)
        if not vendored:
            errors.append(
                "Vendored skills not found in the doctrine layer: "
                + ", ".join(VENDORED_SKILL_NAMES)
            )
            return MigrationResult(success=False, changes_made=changes, errors=errors)

        agents = _installable_agents(project_path)
        if not agents:
            warnings.append(
                "No skill-installing agents configured; skipping vendored skills"
            )
            return MigrationResult(
                success=True, changes_made=changes, warnings=warnings
            )

        if dry_run:
            changes.append(
                f"Would install {len(vendored)} vendored skill(s) "
                f"for {len(agents)} agent(s)"
            )
            return MigrationResult(success=True, changes_made=changes)

        archived_paths: list[Path] = []
        manifest = install_all_skills(
            project_path, agents, registry, archived_paths=archived_paths
        )

        existing = load_manifest(project_path)
        preserved: list[Any] = []
        if existing is not None:
            canonical_names = {skill.name for skill in registry.discover_skills()}
            preserved = [
                entry
                for entry in existing.entries
                if entry.skill_name not in RETIRED_CANONICAL_SKILL_NAMES
                and (
                    entry.skill_name not in canonical_names
                    or entry.agent_key not in agents
                )
            ]
            manifest.entries.extend(preserved)

        if not manifest.entries and not preserved:
            errors.append(
                "No managed skill files were installed for any configured agent"
            )
            return MigrationResult(success=False, changes_made=changes, errors=errors)

        manifest.spec_kitty_version = _TARGET_VERSION
        save_manifest(manifest, project_path)

        preserved_paths = sorted(
            to_posix(path.relative_to(project_path)) for path in archived_paths
        )

        changes.append(
            f"Installed {len(vendored)} vendored skill(s) for {len(agents)} agent(s) "
            f"({len(manifest.entries)} managed files)"
        )
        changes.append("Updated .kittify/skills-manifest.json with vendored entries")
        changes.extend(
            f"Archived customized skill file for manual review: {path}"
            for path in preserved_paths
        )
        return MigrationResult(
            success=True,
            changes_made=changes,
            warnings=warnings,
            manual_review_required=bool(preserved_paths),
            preserved_paths=preserved_paths,
        )
