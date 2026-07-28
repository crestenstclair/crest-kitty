"""Owned-process-tree observation and bounded termination (port of process-tree.ts).

Ownership is established exclusively by pid/pgid descent from the spawned
parent: the enumeration walks parent->child links (via psutil instead of the
upstream ``ps`` parsing) plus, on POSIX, membership in the parent's process
group. Processes are NEVER selected by executable name, so an unrelated
process that happens to share a basename with a fixture is untouchable.

Termination escalates SIGTERM -> SIGKILL against the owned group and each
owned pid within a bounded grace budget, recording every action as a JSON-safe
dict ``{elapsedMs, action, target, succeeded, detail?}``.

Deviations from the TS reference:
- Enumeration uses psutil rather than spawning ``ps``/PowerShell.
- Zombie processes count as terminated. Node auto-reaps its children, so the
  TS supervisor never observes its own zombies; Python only reaps on
  ``poll``/``wait``, so a killed-but-unreaped direct child would otherwise be
  reported resident forever.
- On non-POSIX hosts there is no process group; the group id is ``None`` and
  termination degrades to per-pid signalling (psutil-portable), matching the
  upstream win32 fallback shape without ``taskkill``.
"""

from __future__ import annotations

import contextlib
import os
import signal as signal_module
import time
from typing import Any

import psutil

_WAIT_SLICE_S = 0.025


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _is_alive(pid: int) -> bool:
    """Liveness by pid identity; a zombie counts as terminated (see module doc)."""
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True  # e.g. AccessDenied: it exists, mirror the TS EPERM-is-alive rule


class OwnedProcessTree:
    """Tracks every process owned by one spawned parent, by descent only."""

    def __init__(self, parent_pid: int, started_at_epoch_ms: int) -> None:
        self.parent_pid = parent_pid
        self._started_at_epoch_ms = started_at_epoch_ms
        self.process_group_id: int | None = parent_pid if os.name == "posix" else None
        self._observed: set[int] = {parent_pid}
        self._descendants: set[int] = set()
        self._errors: list[str] = []
        self._parent_exited_at_ms: int | None = None

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def record_parent_exit(self) -> None:
        if self._parent_exited_at_ms is None:
            self._parent_exited_at_ms = _epoch_ms() - self._started_at_epoch_ms

    def _record_error(self, cause: Exception) -> None:
        message = str(cause) or type(cause).__name__
        if message not in self._errors:
            self._errors.append(message)

    def _enumerate(self) -> list[tuple[int, int, int]]:
        """Returns (pid, ppid, status-is-zombie) triples for every visible process."""
        rows: list[tuple[int, int, int]] = []
        for proc in psutil.process_iter(attrs=["pid", "ppid", "status"]):
            info = proc.info
            pid, ppid = info.get("pid"), info.get("ppid")
            if isinstance(pid, int) and isinstance(ppid, int):
                rows.append((pid, ppid, 1 if info.get("status") == psutil.STATUS_ZOMBIE else 0))
        return rows

    def snapshot(self) -> list[int]:
        """Re-derive the owned set (descent + group membership) and return live owned pids."""
        try:
            rows = self._enumerate()
        except Exception as cause:  # enumeration failure degrades to direct liveness checks
            self._record_error(cause)
            return sorted(pid for pid in self._observed if _is_alive(pid))

        by_parent: dict[int, list[int]] = {}
        for pid, ppid, _ in rows:
            by_parent.setdefault(ppid, []).append(pid)
        owned: set[int] = set()
        queue = list(self._observed)
        while queue:
            pid = queue.pop(0)
            if pid in owned:
                continue
            owned.add(pid)
            queue.extend(by_parent.get(pid, []))
        if self.process_group_id is not None:
            for pid, _, _ in rows:
                if pid in owned:
                    continue
                with contextlib.suppress(OSError):
                    if os.getpgid(pid) == self.process_group_id:
                        owned.add(pid)
        for pid in owned:
            self._observed.add(pid)
            if pid != self.parent_pid:
                self._descendants.add(pid)
        live = {pid for pid, _, zombie in rows if not zombie}
        enumerated = {pid for pid, _, _ in rows}
        return sorted(pid for pid in self._observed if pid in live or (pid not in enumerated and _is_alive(pid)))

    def _action(self, actions: list[dict[str, Any]], action: str, target: str, operation: Any) -> None:
        record: dict[str, Any] = {"elapsedMs": _epoch_ms() - self._started_at_epoch_ms, "action": action, "target": target}
        try:
            operation()
            record["succeeded"] = True
        except ProcessLookupError as cause:  # already gone: mirrors the TS ESRCH-is-success rule
            record["succeeded"] = True
            record["detail"] = str(cause) or "ESRCH"
        except OSError as cause:
            record["succeeded"] = False
            record["detail"] = str(cause) or type(cause).__name__
        actions.append(record)

    def _signal_stage(self, pids: list[int], signum: int, name: str, actions: list[dict[str, Any]]) -> None:
        group = self.process_group_id
        if group is not None:
            self._action(actions, f"signal:{name}", f"process-group:{group}", lambda: os.killpg(group, signum))
        for pid in pids:
            if pid == self.parent_pid and group is not None:
                continue
            self._action(actions, f"signal:{name}", f"pid:{pid}", lambda pid=pid: os.kill(pid, signum))

    def _wait_for_empty(self, milliseconds: int) -> bool:
        deadline = time.monotonic() + max(0, milliseconds) / 1000
        while True:
            if not self.snapshot():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(_WAIT_SLICE_S, max(0.001, remaining)))
        return not self.snapshot()

    def terminate(self, grace_ms: int, actions: list[dict[str, Any]]) -> list[int]:
        """SIGTERM then SIGKILL the owned tree within ``grace_ms``; returns survivors."""
        before = self.snapshot()
        if not before:
            return []
        soft_budget = max(1, grace_ms // 2)
        hard_budget = max(1, grace_ms - soft_budget)
        self._signal_stage(before, signal_module.SIGTERM, "SIGTERM", actions)
        if self._wait_for_empty(soft_budget):
            return []
        remaining = self.snapshot()
        self._signal_stage(remaining, signal_module.SIGKILL, "SIGKILL", actions)
        self._wait_for_empty(hard_budget)
        return self.snapshot()

    def evidence(self) -> dict[str, Any]:
        remaining = self.snapshot()
        payload: dict[str, Any] = {
            "parentPid": self.parent_pid,
            "processGroupId": self.process_group_id,
            "observedPids": sorted(self._observed),
            "observedDescendantPids": sorted(self._descendants),
            "remainingPids": remaining,
            "noOwnedProcessesRemain": not remaining,
        }
        if self._parent_exited_at_ms is not None:
            payload["parentExitedAtMs"] = self._parent_exited_at_ms
        return payload
