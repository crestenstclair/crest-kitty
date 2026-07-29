"""``spec-kitty crest-spec`` — the first-class surface for the crest-spec.

The crest-spec is the bedrock declaration of what the system is (intent,
bounded contexts, resources, assets, proof). This group owns its operator
surface:

- ``spec-kitty crest-spec context`` renders the interpretation contract,
  source files, relationship index, and the resolved project value for agent
  grounding.
- ``spec-kitty crest-spec doctor`` validates the crest-spec fail-closed and
  summarizes the resolved model.

Both are ordinary reads: nothing here executes declared validations.
"""

from __future__ import annotations

import json

import typer

from specify_cli.cli.console import console
from specify_cli.core.paths import locate_project_root

app = typer.Typer(
    help=(
        "The crest-spec: the project's bedrock DDD declaration. Planning, "
        "tasks, code, and proof derive from it."
    )
)


@app.command(name="context")
def context_command(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Render the crest-spec for agent context.

    Prints the interpretation contract, source files, relationship index, and
    the resolved project value from the crest-spec root (default
    .kittify/crest-spec). Agents run this at the start of crest-spec
    authoring, planning, and implementation to ground work in the declared
    model. Ordinary read: never executes declared validations.
    """
    from specify_cli.crest_spec import (
        CrestSpecError,
        load_crest_spec,
        render_crest_spec_context,
        resolve_crest_spec_root,
    )

    try:
        repo_root = locate_project_root()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(2) from e

    try:
        crest_spec = load_crest_spec(repo_root)
    except CrestSpecError as error:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "invalid",
                        "diagnostics": [
                            {"code": d.code, "message": d.message, "file": d.file}
                            for d in error.diagnostics
                        ],
                    },
                    indent=2,
                )
            )
        else:
            console.print("[red]Crest-spec is invalid:[/red]")
            for diagnostic in error.diagnostics:
                console.print(f"  [red]•[/red] {diagnostic.render()}")
        raise typer.Exit(1) from error

    if crest_spec is None:
        root = resolve_crest_spec_root(repo_root)
        if json_output:
            print(json.dumps({"status": "not_applicable", "root": str(root)}, indent=2))
        else:
            console.print(
                f"[yellow]No crest-spec at {root} — nothing to render.[/yellow]"
            )
        return

    if json_output:
        from specify_cli.crest_spec import CREST_SPEC_INTERPRETATION_CONTRACT

        print(
            json.dumps(
                {
                    "status": "ok",
                    "kind": "spec-kitty-crest-spec",
                    "root": str(crest_spec.root),
                    "files": [str(f) for f in crest_spec.files],
                    "interpretation": CREST_SPEC_INTERPRETATION_CONTRACT,
                    "project": crest_spec.project,
                    "relationships": [
                        {
                            "from": r.from_id,
                            "relation": r.relation,
                            "to": r.to_id,
                            **({"detail": r.detail} if r.detail else {}),
                        }
                        for r in crest_spec.relationships
                    ],
                },
                indent=2,
            )
        )
    else:
        print(render_crest_spec_context(crest_spec))


@app.command(name="doctor")
def doctor_command(
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
) -> None:
    """Validate the crest-spec (.kittify/crest-spec) fail-closed.

    Loads and expands the terse YAML crest-spec, reporting every diagnostic,
    and summarizes the resolved model. An absent crest-spec is reported as
    not-applicable, not an error. Never executes declared validations.

    Examples:
        spec-kitty crest-spec doctor
        spec-kitty crest-spec doctor --json
    """
    from ._crest_spec_doctor import run_crest_spec_doctor

    try:
        project_path = locate_project_root()
    except Exception as exc:
        message = "Not inside a spec-kitty project (no .kittify/ directory found)"
        if json_output:
            print(json.dumps({"status": "error", "error": message}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {message}")
        raise typer.Exit(2) from exc
    exit_code = run_crest_spec_doctor(project_path, json_output)
    if exit_code:
        raise typer.Exit(exit_code)


__all__ = ["app"]
