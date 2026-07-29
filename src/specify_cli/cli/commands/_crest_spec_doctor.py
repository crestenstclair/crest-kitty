"""``spec-kitty crest-spec doctor`` — validate the project crest-spec.

Sibling module per the doctor orchestration-shim decomposition (#2059): the
thin ``@app.command`` shells live in ``crest_spec_cmd.py`` (first-class group)
and ``doctor.py`` (diagnostics hub); the logic lives here.

Ordinary read: validates and summarizes the spec, never executes declared
validations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from specify_cli.crest_spec import (
    CrestSpecError,
    load_crest_spec,
    resolve_crest_spec_root,
)

from ._doctor_shared import console


def _summary_payload(project: dict[str, Any], relationships: int) -> dict[str, Any]:
    contexts = project.get("contexts", {})
    resources = sum(
        len(section)
        for context in contexts.values()
        if isinstance(context, dict)
        for key, section in context.items()
        if isinstance(section, dict)
        and key
        in ("valueObjects", "aggregates", "ports", "repositories", "domainServices", "applicationServices")
    )
    completion = project.get("completion", {}) if isinstance(project.get("completion"), dict) else {}
    return {
        "name": project.get("name"),
        "contexts": len(contexts),
        "contextResources": resources,
        "goals": len(project.get("goals", {})),
        "capabilities": len(project.get("capabilities", {})),
        "requirements": len(project.get("requirements", {})),
        "projectValidations": len(project.get("validations", {})),
        "witnesses": len(project.get("witnesses", {})),
        "relationships": relationships,
        "projectChecks": len(completion.get("projectChecks") or []),
    }


def run_crest_spec_doctor(project_root: Path, json_output: bool) -> int:
    """Validate the crest-spec; returns the intended exit code."""
    root = resolve_crest_spec_root(project_root)
    try:
        crest_spec = load_crest_spec(project_root)
    except CrestSpecError as error:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "status": "invalid",
                        "root": str(root),
                        "diagnostics": [
                            {"code": d.code, "message": d.message, "file": d.file}
                            for d in error.diagnostics
                        ],
                    },
                    indent=2,
                )
            )
        else:
            console.print(f"[red]Crest-spec at {root} is invalid:[/red]")
            for diagnostic in error.diagnostics:
                console.print(f"  [red]•[/red] {diagnostic.render()}")
        return 1

    if crest_spec is None:
        if json_output:
            console.print_json(
                json.dumps({"status": "not_applicable", "root": str(root)}, indent=2)
            )
        else:
            console.print(
                f"[yellow]No crest-spec found at {root} — crest-spec-dependent "
                "gates are not applicable.[/yellow]"
            )
        return 0

    payload = _summary_payload(crest_spec.project, len(crest_spec.relationships))
    if json_output:
        console.print_json(
            json.dumps(
                {
                    "status": "ok",
                    "root": str(crest_spec.root),
                    "files": [str(f) for f in crest_spec.files],
                    "summary": payload,
                },
                indent=2,
            )
        )
    else:
        console.print(f"[green]Crest-spec OK[/green] ({crest_spec.root})")
        console.print(
            f"  {payload['contexts']} contexts / {payload['contextResources']} resources, "
            f"{payload['goals']} goals, {payload['capabilities']} capabilities, "
            f"{payload['requirements']} requirements"
        )
        console.print(
            f"  {payload['projectValidations']} project validations "
            f"({payload['projectChecks']} completion checks), "
            f"{payload['witnesses']} witnesses, {payload['relationships']} relationships"
        )
    return 0
