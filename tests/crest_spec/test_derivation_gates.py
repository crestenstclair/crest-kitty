"""Executable derivation gates: the crest-spec is the bedrock.

Covers the three gate surfaces (implement / plan / accept-proof), the
duplicate-artifact guard, and the pure coverage helpers.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from specify_cli.crest_spec.derivation import (
    CREST_SPEC_IMPACT_KEY,
    asset_file_patterns,
    check_added_resource_proof,
    check_plan_derivation,
    check_wp_derivation,
    forbidden_duplicate_artifacts,
    uncovered_owned_files,
)

pytestmark = [pytest.mark.integration, pytest.mark.git_repo]

PROJECT_YAML = """\
name: demo
mission: prove the derivation gates
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
"""

CAPABILITIES_YAML = """\
capabilities:
  parse_input:
    description: parse the input stream
"""

CONTEXT_YAML = """\
context: Core
purpose: hold the demo resources
valueObjects:
  Token:
    description: an opaque identity
    contributesTo:
      parse_input: keeps identity stable
"""

ASSETS_YAML = """\
assetKinds:
  python-module:
    description: a python module
    filePattern: src/demo/*.py
  module-tests:
    description: module tests
    filePattern: tests/demo/*.py
assets:
  DemoModule:
    kind: python-module
    description: the demo module
    prompts:
    - Build the demo module.
"""


def _write_spec(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / ".kittify" / "crest-spec" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_mission(root: Path, impact: str | None) -> Path:
    feature_dir = root / "kitty-specs" / "001-demo"
    feature_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"mission_type": "software-dev"}
    if impact is not None:
        meta[CREST_SPEC_IMPACT_KEY] = impact
    (feature_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return feature_dir


def _write_wp(feature_dir: Path, owned_files: list[str]) -> Path:
    tasks = feature_dir / "tasks"
    tasks.mkdir(exist_ok=True)
    wp = tasks / "WP01.md"
    owned = "".join(f"- {path}\n" for path in owned_files)
    wp.write_text(
        f"---\nwork_package_id: WP01\nowned_files:\n{owned}---\n\n# WP01\n",
        encoding="utf-8",
    )
    return wp


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(root),
        },
    )


DEMO_SPEC = {
    "project.yaml": PROJECT_YAML,
    "capabilities.yaml": CAPABILITIES_YAML,
    "contexts/core.yaml": CONTEXT_YAML,
    "assets.yaml": ASSETS_YAML,
}


# --- pure helpers -----------------------------------------------------------


def test_asset_file_patterns_only_kinds_with_assets() -> None:
    project = {
        "assetKinds": {
            "used": {"filePattern": "src/*.py"},
            "unused": {"filePattern": "docs/*.md"},
        },
        "assets": {"A": {"kind": "used"}},
    }
    assert asset_file_patterns(project) == ["src/*.py"]


def test_uncovered_owned_files_exempts_mission_and_spec_paths() -> None:
    project = {
        "assetKinds": {"k": {"filePattern": "src/demo/*.py"}},
        "assets": {"A": {"kind": "k"}},
    }
    uncovered = uncovered_owned_files(
        project,
        [
            "src/demo/mod.py",  # covered
            "kitty-specs/001-demo/tasks/WP01.md",  # exempt: mission bookkeeping
            ".kittify/crest-spec/assets.yaml",  # exempt: the crest-spec itself
            "src/other/stray.py",  # uncovered
        ],
        spec_root_rel=".kittify/crest-spec",
    )
    assert uncovered == ["src/other/stray.py"]


# --- implement gate ---------------------------------------------------------


def test_wp_gate_not_applicable_without_crest_spec(tmp_path: Path) -> None:
    feature_dir = _write_mission(tmp_path, impact=None)
    wp = _write_wp(feature_dir, ["src/demo/mod.py"])
    result = check_wp_derivation(tmp_path, feature_dir, wp)
    assert result.passed and not result.applicable


def test_wp_gate_fails_closed_on_invalid_spec(tmp_path: Path) -> None:
    _write_spec(tmp_path, {"project.yaml": "name: [unclosed"})
    feature_dir = _write_mission(tmp_path, impact="structural")
    wp = _write_wp(feature_dir, ["src/demo/mod.py"])
    result = check_wp_derivation(tmp_path, feature_dir, wp)
    assert not result.passed
    assert "crest_spec_invalid" in result.errors[0]


def test_wp_gate_requires_impact_declaration(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact=None)
    wp = _write_wp(feature_dir, ["src/demo/mod.py"])
    result = check_wp_derivation(tmp_path, feature_dir, wp)
    assert not result.passed
    assert "crest_spec_impact_undeclared" in result.errors[0]


def test_wp_gate_impact_none_skips_coverage(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="none")
    wp = _write_wp(feature_dir, ["docs/anything.md"])
    assert check_wp_derivation(tmp_path, feature_dir, wp).passed


def test_wp_gate_blocks_uncovered_owned_files(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="structural")
    wp = _write_wp(feature_dir, ["src/demo/mod.py", "src/undeclared/new.py"])
    result = check_wp_derivation(tmp_path, feature_dir, wp)
    assert not result.passed
    assert "crest_spec_underived" in result.errors[0]
    assert "src/undeclared/new.py" in result.errors[0]
    assert "src/demo/mod.py" not in result.errors[0]


def test_wp_gate_passes_covered_owned_files(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="predeclared")
    wp = _write_wp(feature_dir, ["src/demo/mod.py", "kitty-specs/001-demo/plan.md"])
    assert check_wp_derivation(tmp_path, feature_dir, wp).passed


# --- plan gate ---------------------------------------------------------------


def test_plan_gate_structural_requires_spec_diff(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="structural")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "mission")

    result = check_plan_derivation(tmp_path, feature_dir, "main")
    assert not result.passed
    assert "crest_spec_unchanged" in result.errors[0]

    # Touching the crest-spec (even uncommitted) satisfies the gate.
    (tmp_path / ".kittify" / "crest-spec" / "goals.yaml").write_text(
        "goals:\n  demo_goal:\n    description: a goal\n", encoding="utf-8"
    )
    assert check_plan_derivation(tmp_path, feature_dir, "main").passed


def test_plan_gate_predeclared_needs_no_diff(tmp_path: Path) -> None:
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="predeclared")
    assert check_plan_derivation(tmp_path, feature_dir, None).passed


# --- accept proof gate --------------------------------------------------------


def _committed_base(tmp_path: Path, spec: dict[str, str]) -> None:
    _write_spec(tmp_path, spec)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "mission")


AGGREGATE_CONTEXT = """\
context: Core
purpose: hold the demo resources
aggregates:
  Ledger:
    purpose: track entries
    state: entries
    commands:
      record: append an entry
    contributesTo:
      parse_input: records parsed entries
"""

VALIDATIONS_YAML = """\
projectValidations:
  gate:
    description: run the suite
    command: pytest -q
    resources:
    - Core.Ledger
attachedValidations: {}
"""


def test_proof_gate_blocks_unproven_added_behavior(tmp_path: Path) -> None:
    _committed_base(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="structural")
    _write_spec(tmp_path, {"contexts/core.yaml": AGGREGATE_CONTEXT})

    result = check_added_resource_proof(tmp_path, feature_dir, "main")
    assert not result.passed
    assert "crest_spec_unproven" in result.errors[0]
    assert "aggregate.Core.Ledger" in result.errors[0]


def test_proof_gate_passes_when_validation_covers_added_behavior(tmp_path: Path) -> None:
    _committed_base(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="structural")
    _write_spec(
        tmp_path,
        {
            "contexts/core.yaml": AGGREGATE_CONTEXT,
            "proof/validations.yaml": VALIDATIONS_YAML,
        },
    )
    assert check_added_resource_proof(tmp_path, feature_dir, "main").passed


def test_proof_gate_skips_without_base_spec(tmp_path: Path) -> None:
    # Adoption mission: no crest-spec at base — governed by the deterministic
    # arming rules, not incremental proof comparison.
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _write_spec(tmp_path, DEMO_SPEC)
    feature_dir = _write_mission(tmp_path, impact="structural")
    assert check_added_resource_proof(tmp_path, feature_dir, "main").passed


# --- duplicate artifacts -------------------------------------------------------


def test_forbidden_duplicate_artifacts(tmp_path: Path) -> None:
    feature_dir = tmp_path / "kitty-specs" / "001-demo"
    (feature_dir / "contracts").mkdir(parents=True)
    assert forbidden_duplicate_artifacts(feature_dir) == []  # empty contracts/ ok
    (feature_dir / "data-model.md").write_text("# dm\n", encoding="utf-8")
    (feature_dir / "contracts" / "api.md").write_text("# api\n", encoding="utf-8")
    assert forbidden_duplicate_artifacts(feature_dir) == ["data-model.md", "contracts/"]
