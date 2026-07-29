"""Deterministic-acceptance step for ``spec-kitty accept``.

Sibling module keeping ``accept.py`` a thin shell (S3776 discipline). Runs the
ported CrestOpenSpec deterministic engine
(``specify_cli.acceptance.deterministic``) against the mission scope and, when
recording is permitted, writes the versioned report to
``<mission>/deterministic-acceptance.json`` — the artifact archive guard AM-6
later reads. Accept is the ONLY lifecycle step that executes declared
validations; ordinary reads (context, doctor, lint, archive) never do.
"""

from __future__ import annotations

import json
from pathlib import Path

from specify_cli.acceptance.deterministic.model import AcceptanceScope
from specify_cli.acceptance.deterministic.service import AcceptanceReport, AcceptanceService
from specify_cli.acceptance.execution_contract import CREST_SPEC_DRIFT_GUARD_IDS
from specify_cli.cli.console import console
from specify_cli.missions._archive import DETERMINISTIC_ACCEPTANCE_FILE


def run_deterministic_step(
    repo_root: Path,
    mission_slug: str,
    feature_dir: Path | None,
    *,
    record: bool,
    scope_mode: str = "mission",
) -> AcceptanceReport:
    """Run the deterministic engine; record the report when permitted."""
    scope = (
        AcceptanceScope(mode="mission", mission=mission_slug)
        if scope_mode == "mission"
        else AcceptanceScope(mode="project")
    )
    report = AcceptanceService().run(repo_root, scope)
    if record and report.applicable and feature_dir is not None and feature_dir.is_dir():
        (feature_dir / DETERMINISTIC_ACCEPTANCE_FILE).write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
    return report


def print_deterministic_failure(report: AcceptanceReport) -> None:
    """Human-readable summary of a failed deterministic report."""
    console.print("[red]Deterministic acceptance failed:[/red]")
    for gate_name, gate in report.gates.items():
        status = gate.get("status")
        if status == "failed":
            console.print(f"  [red]gate {gate_name}: failed[/red]")
            for diagnostic in gate.get("diagnostics", [])[:10]:
                console.print(f"    • {diagnostic.get('code')}: {diagnostic.get('message')}")
    for check in report.checks:
        if not check.get("passed"):
            console.print(f"  [red]check {check.get('id')}: failed[/red]")
            for diagnostic in check.get("diagnostics", [])[:5]:
                console.print(f"    • {diagnostic.get('code')}: {diagnostic.get('message')}")


def print_deterministic_success(report: AcceptanceReport) -> None:
    gate = report.gates.get("validations", {})
    console.print(
        f"[green]Deterministic acceptance passed[/green] "
        f"({gate.get('executed', 0)} checks: {gate.get('declaredProjectChecks', 0)} project, "
        f"{gate.get('applicableAttachedTests', 0)} attached tests, "
        f"{gate.get('applicableAttachedRuntimeSessions', 0)} runtime sessions)"
    )
    console.print(
        "[yellow]Semantic layer still required:[/yellow] apply the execution-acceptance "
        f"contract in the accept prompt ({len(CREST_SPEC_DRIFT_GUARD_IDS)} crest-spec drift "
        "guards) before reporting acceptance complete."
    )
