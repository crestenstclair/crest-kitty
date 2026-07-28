"""Golden test: the YAML loader's expansion is deep-equal to the CUE bridge.

``tests/fixtures/architecture/crest-synth-spec`` is the crest-synth
architecture spec converted losslessly from CUE to the terse YAML format;
``crest-synth-project.json`` is the concrete ``project`` value the CrestOpenSpec
CUE bridge evaluated from the original ``spec/*.cue``. Expansion must
reproduce it exactly — this pins the canonical data model every downstream
consumer (context injection, relationships, acceptance inventory) is written
against.
"""

import json
from pathlib import Path

import pytest

from specify_cli.architecture import load_architecture

FIXTURES = Path(__file__).parents[1] / "fixtures" / "architecture"

pytestmark = pytest.mark.integration


@pytest.fixture()
def crest_synth_project_root(tmp_path: Path) -> Path:
    kittify = tmp_path / ".kittify"
    kittify.mkdir()
    (kittify / "config.yaml").write_text(
        f"architecture:\n  root: {FIXTURES / 'crest-synth-spec'}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_expansion_matches_cue_bridge_golden(crest_synth_project_root: Path) -> None:
    architecture = load_architecture(crest_synth_project_root)
    assert architecture is not None

    expected = json.loads(
        (FIXTURES / "crest-synth-project.json").read_text(encoding="utf-8")
    )
    assert architecture.project == expected


def test_relationships_are_deterministic_and_populated(
    crest_synth_project_root: Path,
) -> None:
    first = load_architecture(crest_synth_project_root)
    second = load_architecture(crest_synth_project_root)
    assert first is not None and second is not None
    assert first.relationships == second.relationships
    # crest-synth declares 413 resources; the index must be substantial.
    assert len(first.relationships) > 1000
    relations = {r.relation for r in first.relationships}
    assert {"contains", "contributes_to", "validated_by", "completion_checks"} <= relations
