"""Acceptance-gate behavior of the architecture reconciliation check."""

from pathlib import Path

import pytest

from specify_cli.acceptance import _check_architecture_reconciliation
from specify_cli.acceptance.gates_core import ARCHITECTURE_RECONCILIATION_HEADING

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
    spec = tmp_path / ".kittify" / "architecture"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    return tmp_path, feature_dir


def test_no_spec_is_not_applicable(tmp_path: Path) -> None:
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    issues: list[str] = []
    _check_architecture_reconciliation(tmp_path, feature_dir, issues)
    assert issues == []


def test_spec_without_reconciliation_section_blocks(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (feature_dir / "plan.md").write_text("# Plan\n\nJust vibes.\n", encoding="utf-8")
    issues: list[str] = []
    _check_architecture_reconciliation(repo_root, feature_dir, issues)
    assert len(issues) == 1
    assert "Architecture reconciliation required" in issues[0]


def test_missing_plan_counts_as_missing_reconciliation(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    issues: list[str] = []
    _check_architecture_reconciliation(repo_root, feature_dir, issues)
    assert len(issues) == 1


def test_reconciliation_section_passes(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (feature_dir / "plan.md").write_text(
        f"# Plan\n\n{ARCHITECTURE_RECONCILIATION_HEADING}\n\n- none — conforms\n",
        encoding="utf-8",
    )
    issues: list[str] = []
    _check_architecture_reconciliation(repo_root, feature_dir, issues)
    assert issues == []


def test_invalid_spec_blocks_fail_closed(tmp_path: Path) -> None:
    repo_root, feature_dir = _repo_with_spec(tmp_path)
    (repo_root / ".kittify" / "architecture" / "goals.yaml").write_text(
        "goals:\n  ship:\n    capabilities: [missing]\n", encoding="utf-8"
    )
    (feature_dir / "plan.md").write_text(
        f"{ARCHITECTURE_RECONCILIATION_HEADING}\n", encoding="utf-8"
    )
    issues: list[str] = []
    _check_architecture_reconciliation(repo_root, feature_dir, issues)
    assert len(issues) == 1
    assert "invalid" in issues[0] and "fail-closed" in issues[0]
