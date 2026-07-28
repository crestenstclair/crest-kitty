#!/usr/bin/env python3
"""Argv-driven runtime-session scenario fixture (port of runtime-session-fixture.mjs).

Usage: ``python session_fixture.py <mode> [--delay MS] [--parent-delay MS]
[--seam PATH] [--seam-timeout MS] [--started PATH]``.

Marker vocabulary: CHECKPOINT (progress), FINAL_STATE + FINAL_SUMMARY
(bounded completion), READY/STOPPED (persistent), WINDOW_OPEN/WINDOW_CLOSE
(interaction window).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _option(args: list[str], name: str, fallback: str) -> str:
    return args[args.index(name) + 1] if name in args else fallback


def _line(value: str) -> None:
    print(value, flush=True)


def _complete() -> None:
    _line("FINAL_STATE")
    _line("FINAL_SUMMARY")


def _sleep_ms(milliseconds: float) -> None:
    time.sleep(milliseconds / 1000)


def _spawn_lingering_child() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time\nwhile True: time.sleep(1)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_interaction(args: list[str]) -> int:
    seam = _option(args, "--seam", "")
    _line("WINDOW_OPEN")
    deadline = time.monotonic() + int(_option(args, "--seam-timeout", "2000")) / 1000
    while not os.path.exists(seam) and time.monotonic() < deadline:
        _sleep_ms(10)
    if not os.path.exists(seam):
        print("interaction seam was not reached", file=sys.stderr, flush=True)
        return 9
    payload = json.loads(Path(seam).read_text(encoding="utf-8"))
    _line(f"ACTION:{payload['action']}")
    _line("WINDOW_CLOSE")
    _line("FINAL_SUMMARY")
    return 0


def _run_persistent() -> int:
    def _stop(signum, frame):  # noqa: ARG001
        _line("STOPPED")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    _line("CHECKPOINT")
    _line("READY")
    while True:
        time.sleep(0.05)


def main() -> int:  # noqa: C901 — flat scenario dispatch, one branch per fixture mode
    argv = sys.argv[1:]
    mode = argv[0] if argv else "clean"
    args = argv[1:]
    started_path = _option(args, "--started", "")
    if started_path:
        Path(started_path).write_text(str(os.getpid()), encoding="utf-8")

    if mode == "clean":
        _line("CHECKPOINT")
        _sleep_ms(int(_option(args, "--delay", "20")))
        _complete()
        return 0
    if mode == "success-hang":
        _line("CHECKPOINT")
        _complete()
        while True:
            time.sleep(1)
    if mode == "silent":
        _line("CHECKPOINT")
        while True:
            time.sleep(1)
    if mode == "early-exit":
        _line("CHECKPOINT")
        return 0
    if mode == "wrong-exit":
        _line("CHECKPOINT")
        _complete()
        return 3
    if mode == "out-of-order":
        _line("CHECKPOINT")
        _line("FINAL_SUMMARY")
        _line("FINAL_STATE")
        return 0
    if mode == "duplicate":
        _line("CHECKPOINT")
        _line("FINAL_STATE")
        _line("FINAL_STATE")
        _line("FINAL_SUMMARY")
        return 0
    if mode == "child-resident":
        _line("CHECKPOINT")
        child = _spawn_lingering_child()
        _line(f"CHILD_PID:{child.pid}")
        _sleep_ms(int(_option(args, "--parent-delay", "200")))
        _complete()
        return 0
    if mode == "persistent":
        return _run_persistent()
    if mode == "interaction":
        return _run_interaction(args)
    print(f"unknown runtime fixture mode: {mode}", file=sys.stderr, flush=True)
    return 64


if __name__ == "__main__":
    sys.exit(main())
