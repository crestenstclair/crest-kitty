"""AM-6: recorded deterministic acceptance gates archiving; never re-run."""

import json
from pathlib import Path

import pytest

from specify_cli.missions._archive import (
    evaluate_archive_eligibility,
    resolve_deterministic_acceptance,
)

pytestmark = pytest.mark.unit

MINIMAL_PROJECT = """\
name: demo
mission: prove AM-6
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
  projectChecks: []
"""


def test_not_applicable_never_blocks() -> None:
    verdict = evaluate_archive_eligibility(
        terminal_state="merged",
        invariant_results=[],
        reason="done",
        deterministic_acceptance=None,
    )
    assert verdict.eligible


@pytest.mark.parametrize("recorded", ["missing", "failed", "unreadable", "invalid-spec"])
def test_merged_with_armed_gate_requires_passed(recorded: str) -> None:
    verdict = evaluate_archive_eligibility(
        terminal_state="merged",
        invariant_results=[],
        reason="done",
        deterministic_acceptance=recorded,
    )
    assert not verdict.eligible and verdict.refusal_code == "AM-6"


def test_merged_with_passed_verdict_is_eligible() -> None:
    verdict = evaluate_archive_eligibility(
        terminal_state="merged",
        invariant_results=[],
        reason="done",
        deterministic_acceptance="passed",
    )
    assert verdict.eligible


def test_canceled_mission_exempt_from_am6() -> None:
    verdict = evaluate_archive_eligibility(
        terminal_state="canceled",
        invariant_results=[],
        reason="abandoned",
        deterministic_acceptance="missing",
    )
    assert verdict.eligible


def _project_with_armed_spec(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / ".kittify" / "crest-spec"
    spec.mkdir(parents=True)
    (spec / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    feature_dir = tmp_path / "kitty-specs" / "demo-mission"
    feature_dir.mkdir(parents=True)
    return tmp_path, feature_dir


def test_resolver_no_spec_is_none(tmp_path: Path) -> None:
    feature_dir = tmp_path / "kitty-specs" / "m"
    feature_dir.mkdir(parents=True)
    assert resolve_deterministic_acceptance(tmp_path, feature_dir) is None


def test_resolver_armed_gate_without_report_is_missing(tmp_path: Path) -> None:
    root, feature_dir = _project_with_armed_spec(tmp_path)
    assert resolve_deterministic_acceptance(root, feature_dir) == "missing"


def test_resolver_reads_recorded_verdict(tmp_path: Path) -> None:
    root, feature_dir = _project_with_armed_spec(tmp_path)
    report = feature_dir / "deterministic-acceptance.json"
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert resolve_deterministic_acceptance(root, feature_dir) == "passed"
    report.write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert resolve_deterministic_acceptance(root, feature_dir) == "failed"
    report.write_text("{not json", encoding="utf-8")
    assert resolve_deterministic_acceptance(root, feature_dir) == "unreadable"


def test_resolver_unarmed_spec_is_none(tmp_path: Path) -> None:
    root, feature_dir = _project_with_armed_spec(tmp_path)
    (root / ".kittify" / "crest-spec" / "project.yaml").write_text(
        MINIMAL_PROJECT.replace("  projectChecks: []\n", ""), encoding="utf-8"
    )
    assert resolve_deterministic_acceptance(root, feature_dir) is None


def test_resolver_invalid_spec_fails_closed(tmp_path: Path) -> None:
    root, feature_dir = _project_with_armed_spec(tmp_path)
    (root / ".kittify" / "crest-spec" / "goals.yaml").write_text(
        "goals:\n  ship:\n    capabilities: [missing]\n", encoding="utf-8"
    )
    assert resolve_deterministic_acceptance(root, feature_dir) == "invalid-spec"
