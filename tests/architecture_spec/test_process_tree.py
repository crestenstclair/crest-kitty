"""Owned-process-tree observation and bounded termination (port of process-tree.ts semantics)."""

import subprocess
import sys
import time

import pytest

from specify_cli.acceptance.runtime_lifecycle.process_tree import OwnedProcessTree

pytestmark = pytest.mark.integration

PY = sys.executable

PARENT_WITH_CHILD = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(1)'])\n"
    "while True: time.sleep(1)\n"
)


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen(
        [PY, "-c", code],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_snapshot_observes_descendants_and_terminate_kills_only_owned_tree() -> None:
    parent = _spawn(PARENT_WITH_CHILD)
    decoy = _spawn("import time\nwhile True: time.sleep(1)")
    try:
        tree = OwnedProcessTree(parent.pid, int(time.time() * 1000))
        assert _wait_for(lambda: len(tree.snapshot()) >= 2), "descendant was never observed"
        evidence = tree.evidence()
        assert parent.pid in evidence["observedPids"]
        assert evidence["observedDescendantPids"], "expected at least one owned descendant"
        assert decoy.pid not in evidence["observedPids"]

        actions: list[dict] = []
        remaining = tree.terminate(1500, actions)
        assert remaining == []
        assert actions, "termination must record every signalling action"
        for action in actions:
            assert set(action) >= {"elapsedMs", "action", "target", "succeeded"}
            assert action["action"].startswith("signal:")
        assert decoy.poll() is None, "cleanup must never touch a process outside the owned tree"
        final = tree.evidence()
        assert final["noOwnedProcessesRemain"] is True
    finally:
        parent.kill()
        parent.wait()
        decoy.kill()
        decoy.wait()


def test_terminate_on_empty_tree_is_a_noop() -> None:
    proc = _spawn("pass")
    proc.wait()
    tree = OwnedProcessTree(proc.pid, int(time.time() * 1000))
    actions: list[dict] = []
    assert tree.terminate(200, actions) == []
    assert actions == []


def test_evidence_records_parent_exit() -> None:
    proc = _spawn("import time; time.sleep(0.05)")
    tree = OwnedProcessTree(proc.pid, int(time.time() * 1000))
    proc.wait()
    tree.record_parent_exit()
    evidence = tree.evidence()
    assert evidence["parentPid"] == proc.pid
    assert evidence["processGroupId"] == proc.pid
    assert "parentExitedAtMs" in evidence
    assert evidence["noOwnedProcessesRemain"] is True
