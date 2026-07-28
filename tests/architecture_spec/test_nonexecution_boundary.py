"""Explicit-execution boundary: ordinary reads never run declared validations.

Only ``spec-kitty accept`` (and the future explicit verify) may execute
declared acceptance commands. Loading/rendering the spec, doctor validation,
the reconciliation gate, and the AM-6 archive resolver are ordinary reads.
Each declared command here drops a sentinel file if it ever runs — the tests
assert the sentinel never appears.
"""

import json
import sys
from pathlib import Path

import pytest

from specify_cli.acceptance.deterministic.model import AcceptanceScope
from specify_cli.acceptance.deterministic.service import AcceptanceService
from specify_cli.acceptance import _check_architecture_reconciliation
from specify_cli.architecture import load_architecture, render_architecture_context
from specify_cli.cli.commands._architecture_doctor import run_architecture_doctor
from specify_cli.missions._archive import resolve_deterministic_acceptance

pytestmark = pytest.mark.integration

PY = sys.executable


@pytest.fixture()
def armed_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A project whose single declared check writes a sentinel when executed."""
    sentinel = tmp_path / "EXECUTED"
    command = json.dumps([PY, "-c", f"open({str(sentinel)!r}, 'w').write('ran')"])
    spec = tmp_path / ".kittify" / "architecture"
    (spec / "proof").mkdir(parents=True)
    (spec / "project.yaml").write_text(
        "name: demo\nmission: boundary\nnonGoals: {}\nmeta: {}\nlayers: [domain]\n"
        "layerRules: {}\ncontextMap: []\ncompletion:\n  requiredGoals: []\n"
        "  projectChecks: [validation.sentinel]\n",
        encoding="utf-8",
    )
    (spec / "proof" / "validations.yaml").write_text(
        f"""\
projectValidations:
  sentinel:
    scope: project
    command: {command}
    workingDirectory: .
    limits: {{timeoutMs: 10000, stdoutBytes: 4096, stderrBytes: 4096}}
attachedValidations: {{}}
""",
        encoding="utf-8",
    )
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    (feature_dir / "plan.md").write_text("## Architecture Reconciliation\n- none\n", encoding="utf-8")
    return tmp_path, feature_dir, sentinel


def test_ordinary_reads_execute_nothing(armed_project: tuple[Path, Path, Path]) -> None:
    root, feature_dir, sentinel = armed_project

    architecture = load_architecture(root)
    assert architecture is not None
    render_architecture_context(architecture)

    assert run_architecture_doctor(root, json_output=True) == 0

    issues: list[str] = []
    _check_architecture_reconciliation(root, feature_dir, issues)
    assert issues == []

    assert resolve_deterministic_acceptance(root, feature_dir) == "missing"

    assert not sentinel.exists(), "an ordinary read executed a declared validation"


def test_explicit_acceptance_does_execute(armed_project: tuple[Path, Path, Path]) -> None:
    root, _feature_dir, sentinel = armed_project
    report = AcceptanceService().run(root, AcceptanceScope(mode="project"))
    assert report.passed is True
    assert sentinel.exists(), "explicit acceptance must actually run declared checks"
