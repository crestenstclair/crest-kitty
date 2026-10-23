"""Tests for the vendored review-skill install migration.

The migration exists because ``SpkSkillPackMigration`` filters the registry to
``spk-*`` names and is already stamped in every upgraded project, so a project
past 3.2.0rc35 would never receive ``adversarial-review`` or
``writing-clean-code``. These tests pin that gap closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from specify_cli.skills.registry import SkillRegistry
from specify_cli.upgrade.migrations.m_3_2_0rc35_spk_skill_pack import (
    SpkSkillPackMigration,
)
from specify_cli.upgrade.migrations.m_3_2_6_vendored_review_skills import (
    VENDORED_SKILL_NAMES,
    VendoredReviewSkillsMigration,
)

pytestmark = pytest.mark.fast

_MODULE = "specify_cli.upgrade.migrations.m_3_2_6_vendored_review_skills"
_SPK_MODULE = "specify_cli.upgrade.migrations.m_3_2_0rc35_spk_skill_pack"


def _setup_project(tmp_path: Path, agents: list[str]) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    kittify = project / ".kittify"
    kittify.mkdir()
    available = "\n".join(f"    - {agent}" for agent in agents)
    (kittify / "config.yaml").write_text(
        f"agents:\n  available:\n{available}\n",
        encoding="utf-8",
    )
    return project


def _write_skill(
    skills_root: Path,
    name: str,
    *,
    references: list[str] | None = None,
    agents: list[str] | None = None,
) -> None:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n# {name}\n",
        encoding="utf-8",
    )
    for sub, files in (("references", references), ("agents", agents)):
        if not files:
            continue
        sub_dir = skill_dir / sub
        sub_dir.mkdir()
        for fname in files:
            (sub_dir / fname).write_text(f"# {fname}\n", encoding="utf-8")


def _setup_skills(tmp_path: Path) -> Path:
    """A registry holding the public pack plus both vendored skills."""
    skills_root = tmp_path / "doctrine_skills"
    _write_skill(skills_root, "spk-start-here", references=["guide.md"])
    _write_skill(
        skills_root,
        "adversarial-review",
        references=["smells-bloaters.md"],
        agents=["bloater-hunter.md", "finding-skeptic.md"],
    )
    _write_skill(skills_root, "writing-clean-code", references=["solid.md"])
    return skills_root


def _patch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def test_detects_missing_vendored_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        assert VendoredReviewSkillsMigration().detect(project) is True


def test_spk_pack_alone_leaves_vendored_skills_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this migration exists for.

    ``SpkSkillPackMigration`` runs first and reports success, but its ``spk-*``
    detect filter means a project that already has the public pack never gets
    the vendored skills from it. This migration must still fire afterwards.
    """
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    spk_only = tmp_path / "spk_only"
    _write_skill(spk_only, "spk-start-here", references=["guide.md"])

    # Simulate a project upgraded on a release that shipped only the spk pack.
    with patch(f"{_SPK_MODULE}._discover_registry", return_value=SkillRegistry(spk_only)):
        assert SpkSkillPackMigration().apply(project).success is True
        assert SpkSkillPackMigration().detect(project) is False

    skills_dir = project / ".claude" / "skills"
    assert (skills_dir / "spk-start-here" / "SKILL.md").exists()
    for name in VENDORED_SKILL_NAMES:
        assert not (skills_dir / name).exists()

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        assert VendoredReviewSkillsMigration().detect(project) is True


def test_apply_installs_both_vendored_skills_with_agents_subtree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        result = VendoredReviewSkillsMigration().apply(project)

    assert result.success is True
    skills_dir = project / ".claude" / "skills"
    assert (skills_dir / "writing-clean-code" / "references" / "solid.md").exists()
    # The agents/ subtree is the payload that silently degrades the pipeline
    # when absent, so it is asserted explicitly rather than via SKILL.md alone.
    assert (skills_dir / "adversarial-review" / "agents" / "bloater-hunter.md").exists()
    assert (skills_dir / "adversarial-review" / "agents" / "finding-skeptic.md").exists()

    manifest = json.loads((project / ".kittify" / "skills-manifest.json").read_text())
    assert manifest["spec_kitty_version"] == "3.2.6"
    names = {entry["skill_name"] for entry in manifest["entries"]}
    assert set(VENDORED_SKILL_NAMES) <= names


def test_apply_preserves_the_rest_of_the_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``install_all_skills`` prunes global dirs absent from the list it gets.

    Handing it only the two vendored skills would delete every other installed
    skill, so ``apply()`` passes the whole registry. This pins that.
    """
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        assert VendoredReviewSkillsMigration().apply(project).success is True

    assert (project / ".claude" / "skills" / "spk-start-here" / "SKILL.md").exists()
    assert (Path.home() / ".claude" / "skills" / "spk-start-here" / "SKILL.md").exists()


def test_detect_false_after_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        migration = VendoredReviewSkillsMigration()
        assert migration.apply(project).success is True
        assert migration.detect(project) is False


def test_detect_true_when_only_agents_subtree_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project installed before ``agents/`` was collectable has a stale skill.

    ``SKILL.md`` is present, so a directory-level check would call it installed
    while the seven role prompts the pipeline spawns are absent.
    """
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        migration = VendoredReviewSkillsMigration()
        assert migration.apply(project).success is True

        agents_dir = project / ".claude" / "skills" / "adversarial-review" / "agents"
        (agents_dir / "finding-skeptic.md").unlink()

        assert migration.detect(project) is True


def test_skips_wrapper_only_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, agents=["q"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        assert VendoredReviewSkillsMigration().detect(project) is False


def test_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, agents=["claude"])
    skills_root = _setup_skills(tmp_path)
    _patch_home(tmp_path, monkeypatch)

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(skills_root)):
        result = VendoredReviewSkillsMigration().apply(project, dry_run=True)

    assert result.success is True
    assert not (project / ".claude").exists()
    assert not (project / ".kittify" / "skills-manifest.json").exists()


def test_apply_fails_when_vendored_skills_absent_from_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registry without the vendored skills must not stamp the migration.

    Reporting success would mark the migration applied and permanently skip the
    install for this project.
    """
    project = _setup_project(tmp_path, agents=["claude"])
    _patch_home(tmp_path, monkeypatch)

    spk_only = tmp_path / "spk_only"
    _write_skill(spk_only, "spk-start-here")

    with patch(f"{_MODULE}._discover_registry", return_value=SkillRegistry(spk_only)):
        result = VendoredReviewSkillsMigration().apply(project)

    assert result.success is False
    assert any("adversarial-review" in err for err in result.errors)


def test_uninitialized_project_is_not_detected(tmp_path: Path) -> None:
    project = tmp_path / "bare"
    project.mkdir()

    migration = VendoredReviewSkillsMigration()
    assert migration.detect(project) is False
    ok, reason = migration.can_apply(project)
    assert ok is False
    assert ".kittify/" in reason
