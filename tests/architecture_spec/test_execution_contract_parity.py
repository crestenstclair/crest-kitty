"""Parity: the execution-acceptance contract is embedded verbatim where it
belongs (accept + review prompts) and nowhere near archive surfaces, and the
language-neutral drift-case fixture matrix stays loadable and complete."""

import json
import re
from pathlib import Path

import pytest

from specify_cli.acceptance.execution_contract import (
    ARCHITECTURE_DRIFT_GUARD_IDS,
    EXECUTION_ACCEPTANCE_CONTRACT,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).parents[2]
STEPS = REPO / "src" / "doctrine" / "missions" / "mission-steps" / "software-dev"
SKILLS = REPO / "src" / "doctrine" / "skills"
MARKER_RE = re.compile(
    r"<!-- execution-acceptance-contract:start[^>]*-->\n(.*?)\n<!-- execution-acceptance-contract:end -->",
    re.S,
)


@pytest.mark.parametrize("step", ["accept", "review"])
def test_contract_embedded_verbatim(step: str) -> None:
    text = (STEPS / step / "prompt.md").read_text(encoding="utf-8")
    match = MARKER_RE.search(text)
    assert match, f"{step} prompt lacks the execution-acceptance-contract block"
    assert match.group(1) == EXECUTION_ACCEPTANCE_CONTRACT, (
        f"{step} prompt's embedded contract has drifted from "
        "specify_cli.acceptance.execution_contract; re-embed from the constant"
    )


def test_all_guard_ids_present_in_contract() -> None:
    assert len(ARCHITECTURE_DRIFT_GUARD_IDS) == 9  # golden-count: cardinality-is-contract
    for guard_id in ARCHITECTURE_DRIFT_GUARD_IDS:
        assert f"#### {guard_id}" in EXECUTION_ACCEPTANCE_CONTRACT


def test_archive_surfaces_never_carry_the_contract() -> None:
    archive_skill = (SKILLS / "spk-gate-archive" / "SKILL.md").read_text(encoding="utf-8")
    assert "End-of-execute adversarial acceptance" not in archive_skill
    assert "obligation ledger" not in archive_skill.lower().replace("\n", " ") or "must not" in archive_skill.lower()
    # The archive skill must explicitly forbid re-running acceptance.
    assert "re-run" in archive_skill or "never" in archive_skill.lower()


def test_contract_stays_language_neutral() -> None:
    """Deterministic acceptance must not smuggle in ecosystem heuristics."""
    for term in ("pytest", "cargo ", "npm ", "jest", "junit-only", "AST parser"):
        assert term not in EXECUTION_ACCEPTANCE_CONTRACT


def test_drift_case_fixture_matrix_is_complete() -> None:
    fixture = REPO / "tests" / "fixtures" / "adversarial-review" / "architecture-drift-cases.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["languageNeutral"] is True
    cases = payload["cases"]

    for case in cases:
        assert case["dialect"] in {"neutral-trace-v1", "neutral-sequence-v1"}
        assert case["guard"] in ARCHITECTURE_DRIFT_GUARD_IDS
        assert case["outcome"] in {"blocking", "conforming"}
        assert case["authority"]["classification"] in {"CURRENT_SLICE", "EVERGREEN_INVARIANT"}
        assert case["productionTrace"], f"{case['id']} lacks a production trace"

    # Every pair carries both a blocking and a conforming member.
    by_pair: dict[str, set[str]] = {}
    for case in cases:
        by_pair.setdefault(case["pair"], set()).add(case["outcome"])
    incomplete = {pair for pair, outcomes in by_pair.items() if outcomes != {"blocking", "conforming"}}
    assert not incomplete, f"pairs missing a side: {sorted(incomplete)}"

    # The upstream matrix exercises the four composition/runtime-failure
    # guards as trace pairs; the five later guards (validation integrity and
    # the runtime-lifecycle family) are covered by executable inventory and
    # runtime-session fixtures instead of prose pairs.
    covered = {case["guard"] for case in cases}
    assert covered == {
        "composition-root-and-dependency-direction",
        "negotiation-before-preparation",
        "asynchronous-runtime-failure",
        "end-to-end-failure-observability",
    }
