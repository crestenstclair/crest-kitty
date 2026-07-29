"""Fail-closed behavior of the crest-spec loader."""

from pathlib import Path

import pytest

from specify_cli.crest_spec import (
    CrestSpecError,
    load_crest_spec,
    resolve_crest_spec_root,
)

pytestmark = pytest.mark.unit


def write_spec(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / ".kittify" / "crest-spec" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


MINIMAL_PROJECT = """\
name: demo
mission: prove the loader
nonGoals: {}
meta: {}
layers: [domain]
layerRules: {}
contextMap: []
completion:
  requiredGoals: []
"""

MINIMAL_CONTEXT = """\
context: Core
purpose: hold the demo resources
valueObjects:
  Token:
    description: an opaque identity
    contributesTo:
      parse_input: keeps identity stable
"""

MINIMAL_CAPABILITIES = """\
capabilities:
  parse_input:
    description: parse the input stream
"""


def test_absent_spec_directory_is_not_applicable(tmp_path: Path) -> None:
    assert load_crest_spec(tmp_path) is None


def test_empty_spec_directory_is_not_applicable(tmp_path: Path) -> None:
    (tmp_path / ".kittify" / "crest-spec").mkdir(parents=True)
    assert load_crest_spec(tmp_path) is None


def test_minimal_spec_expands_and_indexes(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "contexts/core.yaml": MINIMAL_CONTEXT,
            "capabilities.yaml": MINIMAL_CAPABILITIES,
        },
    )
    architecture = load_crest_spec(tmp_path)
    assert architecture is not None
    token = architecture.project["contexts"]["Core"]["valueObjects"]["Token"]
    # contributesTo map expands to the canonical list-of-edges form
    assert token["contributesTo"] == [
        {"capability": "capability.parse_input", "contribution": "keeps identity stable"}
    ]
    edges = {(r.from_id, r.relation, r.to_id) for r in architecture.relationships}
    assert ("context.Core", "contains", "valueObject.Core.Token") in edges
    assert ("valueObject.Core.Token", "contributes_to", "capability.parse_input") in edges


def test_duplicate_mapping_key_fails_closed(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "capabilities.yaml": (
                "capabilities:\n"
                "  parse_input: {description: one}\n"
                "  parse_input: {description: two}\n"
            ),
        },
    )
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    assert any(d.code == "crest_spec_duplicate_key" for d in excinfo.value.diagnostics)


def test_unresolved_typed_reference_fails_closed(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "goals.yaml": (
                "goals:\n"
                "  ship_it:\n"
                "    description: ship\n"
                "    capabilities: [does_not_exist]\n"
            ),
        },
    )
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    codes = [d.code for d in excinfo.value.diagnostics]
    assert "crest_spec_unresolved_reference" in codes


def test_ambiguous_suffix_reference_fails_closed(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "contexts/a.yaml": "context: Alpha\nvalueObjects:\n  Token: {description: a}\n",
            "contexts/b.yaml": "context: Beta\nvalueObjects:\n  Token: {description: b}\n",
            "proof/witnesses.yaml": (
                "witnesses:\n"
                "  sees_token:\n"
                "    resources: [Token]\n"
            ),
        },
    )
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    ambiguous = [
        d for d in excinfo.value.diagnostics if d.code == "crest_spec_ambiguous_reference"
    ]
    assert ambiguous and "valueObject.Alpha.Token" in ambiguous[0].message


def test_duplicate_canonical_id_fails_closed(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "contexts/a.yaml": "context: Core\nvalueObjects:\n  Token: {description: a}\n",
            "contexts/b.yaml": "context: Core\nvalueObjects:\n  Token: {description: b}\n",
        },
    )
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    assert any(d.code == "crest_spec_duplicate_id" for d in excinfo.value.diagnostics)


def test_unknown_file_fails_closed(tmp_path: Path) -> None:
    write_spec(
        tmp_path,
        {
            "project.yaml": MINIMAL_PROJECT,
            "extra-notes.yaml": "notes: hello\n",
        },
    )
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    assert any(d.code == "crest_spec_unknown_file" for d in excinfo.value.diagnostics)


def test_configured_root_overrides_default(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere"
    custom.mkdir()
    kittify = tmp_path / ".kittify"
    kittify.mkdir()
    (kittify / "config.yaml").write_text(
        "crest_spec:\n  root: elsewhere\n", encoding="utf-8"
    )
    assert resolve_crest_spec_root(tmp_path) == custom
    (custom / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    architecture = load_crest_spec(tmp_path)
    assert architecture is not None
    assert architecture.project["name"] == "demo"


def test_legacy_root_directory_fails_loud(tmp_path: Path) -> None:
    """Pre-rename ``.kittify/architecture`` is a migration error, never a fallback."""
    legacy = tmp_path / ".kittify" / "architecture"
    legacy.mkdir(parents=True)
    (legacy / "project.yaml").write_text(MINIMAL_PROJECT, encoding="utf-8")
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    codes = [d.code for d in excinfo.value.diagnostics]
    assert codes == ["crest_spec_legacy_root"]
    assert "git mv .kittify/architecture .kittify/crest-spec" in excinfo.value.diagnostics[0].message


def test_legacy_config_key_fails_loud(tmp_path: Path) -> None:
    """The retired ``architecture.root`` config key must be renamed, not honored."""
    kittify = tmp_path / ".kittify"
    kittify.mkdir()
    (kittify / "config.yaml").write_text("architecture:\n  root: elsewhere\n", encoding="utf-8")
    with pytest.raises(CrestSpecError) as excinfo:
        load_crest_spec(tmp_path)
    codes = [d.code for d in excinfo.value.diagnostics]
    assert codes == ["crest_spec_legacy_config"]
    assert "crest_spec.root" in excinfo.value.diagnostics[0].message
