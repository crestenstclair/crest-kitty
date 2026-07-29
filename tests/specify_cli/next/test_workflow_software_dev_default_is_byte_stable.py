"""C-008 (superseded 2026-07-28): software-dev-default is byte-stable to the pinned sequence.

ATDD anchor
-----------
* ``test_default_workflow_produces_byte_stable_pairs``
  covers: FR-014, C-008 — expected GREEN at: WP11 final commit

History
-------
C-008 originally pinned the pre-Slice-F hardcoded sequence
``specify -> plan -> tasks -> implement -> review -> merge``. The
crest-spec-bedrock change (port/crest-spec-bedrock, operator-ordered)
deliberately re-pins it with a ``crest-spec`` authoring phase between
``specify`` and ``plan``: the crest-spec is the single source of
implementation intent, so a mission that changes system structure authors it
BEFORE planning derives from it. This test remains the byte-stability lock —
any further sequence change must edit this pin knowingly.
"""
from __future__ import annotations


import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# The pinned sequence (crest-spec bedrock, 2026-07-28):
_HARDCODED_SEQUENCE: list[tuple[str, str | None]] = [
    ("specify", "crest-spec"),
    ("crest-spec", "plan"),
    ("plan", "tasks"),
    ("tasks", "implement"),
    ("implement", "review"),
    ("review", "merge"),
    ("merge", None),
]


def test_default_workflow_produces_byte_stable_pairs() -> None:
    """For every (current, next) pair the pinned sequence declares,
    the loaded software-dev-default workflow MUST produce the same pair."""
    from runtime.next._internal_runtime.workflow_registry import get_workflow

    wf = get_workflow("software-dev-default")
    by_name = {a.action_name: a for a in wf.actions}
    for current, expected_next in _HARDCODED_SEQUENCE:
        action = by_name[current]
        actual_next = action.next[0] if action.next else None
        assert actual_next == expected_next, (
            f"byte-stability violation: from {current!r} expected next={expected_next!r}, "
            f"got {actual_next!r}"
        )
