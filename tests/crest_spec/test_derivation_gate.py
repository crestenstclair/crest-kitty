"""Acceptance-gate behavior of the crest-spec derivation check."""

from pathlib import Path

import pytest

from specify_cli.acceptance import _check_crest_spec_derivation
from specify_cli.acceptance.gates_core import CREST_SPEC_DERIVATION_HEADING

pytestmark = pytest.mark.unit

MINIMAL_PROJECT = """\
name: demo
mission: prove the gate
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
"""


def _repo_with_spec(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    return tmp_path, feature_dir


def test_no_spec_is_not_applicable(tmp_path: Path) -> None:
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    issues: list[str] = []
    _check_crest_spec_derivation(tmp_path, feature_dir, issues)
    assert issues == []


def test_spec_without_derivation_section_blocks(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (feature_dir / "plan.md").write_text("# Plan\n\nJust vibes.\n", encoding="utf-8")
    issues: list[str] = []
    _check_crest_spec_derivation(repo_root, feature_dir, issues)
    assert len(issues) == 1
    assert "Crest-spec derivation required" in issues[0]


def test_missing_plan_counts_as_missing_derivation(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    issues: list[str] = []
    _check_crest_spec_derivation(repo_root, feature_dir, issues)
    assert len(issues) == 1


def test_derivation_section_passes(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (feature_dir / "plan.md").write_text(
        f"# Plan\n\n{CREST_SPEC_DERIVATION_HEADING}\n\n- none — conforms\n",
        encoding="utf-8",
    )
    issues: list[str] = []
    _check_crest_spec_derivation(repo_root, feature_dir, issues)
    assert issues == []


def test_invalid_spec_blocks_fail_closed(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (repo_root / ".kittify" / "crest-spec" / "goals.yaml").write_text(
        "goals:\n  ship:\n    capabilities: [missing]\n", encoding="utf-8"
    )
    (feature_dir / "plan.md").write_text(
        f"{CREST_SPEC_DERIVATION_HEADING}\n", encoding="utf-8"
    )
    issues: list[str] = []
    _check_crest_spec_derivation(repo_root, feature_dir, issues)
    assert len(issues) == 1
    assert "invalid" in issues[0] and "fail-closed" in issues[0]


def test_duplicate_planning_artifacts_block(tmp_path: Path) -> None:
    """data-model.md / contracts/ fork the crest-spec and are rejected."""
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (feature_dir / "plan.md").write_text(
        f"# Plan\n\n{CREST_SPEC_DERIVATION_HEADING}\n\n- none — conforms\n",
        encoding="utf-8",
    )
    (feature_dir / "data-model.md").write_text("# dm\n", encoding="utf-8")
    contracts = feature_dir / "contracts"
    contracts.mkdir()
    (contracts / "api.md").write_text("# api\n", encoding="utf-8")
    issues: list[str] = []
    _check_crest_spec_derivation(repo_root, feature_dir, issues)
    assert len(issues) == 1
    assert "crest_spec_duplicate_artifacts" in issues[0]
    assert "data-model.md" in issues[0] and "contracts/" in issues[0]
