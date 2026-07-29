"""`spec-kitty crest-spec doctor` behavior across spec states."""

import json
from pathlib import Path

import pytest

from specify_cli.cli.commands._crest_spec_doctor import run_crest_spec_doctor

pytestmark = pytest.mark.unit

MINIMAL_PROJECT = """\
name: demo
mission: prove the doctor
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
  projectChecks: []
"""


def _capture_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_absent_spec_reports_not_applicable_exit_zero(tmp_path: Path, capsys) -> None:
    exit_code = run_crest_spec_doctor(tmp_path, json_output=True)
    assert exit_code == 0
    assert _capture_json(capsys)["status"] == "not_applicable"


def test_valid_spec_reports_summary(tmp_path: Path, capsys) -> None:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    exit_code = run_crest_spec_doctor(tmp_path, json_output=True)
    assert exit_code == 0
    payload = _capture_json(capsys)
    assert payload["status"] == "ok"
    assert payload["summary"]["name"] == "demo"


def test_invalid_spec_reports_diagnostics_exit_one(tmp_path: Path, capsys) -> None:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    (spec / "goals.yaml").write_text(
        "goals:\n  ship:\n    capabilities: [missing_capability]\n", encoding="utf-8"
    )
    exit_code = run_crest_spec_doctor(tmp_path, json_output=True)
    assert exit_code == 1
    payload = _capture_json(capsys)
    assert payload["status"] == "invalid"
    assert any(
        d["code"] == "crest_spec_unresolved_reference" for d in payload["diagnostics"]
    )
