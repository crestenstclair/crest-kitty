"""The process-json-v1 runtime interaction provider (port of runtime-providers.ts).

Runs a project-owned driver argv in the runtime cwd, sends exactly one bounded
JSON request document on stdin, and expects exactly one JSON evidence document
back on stdout: matching sessionId/actionId, ``attempted``, ``reachedSeam``, a
session-relative ``deliveredAtMs``, named assertion results, and JSON-safe
details. Every abnormal outcome (spawn failure, timeout, output overflow,
resident driver descendants, nonzero exit, unparseable or malformed evidence)
raises — the session supervisor converts it into
``runtime_interaction_provider_failed``.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from specify_cli.acceptance.deterministic.process_runner import ProcessLimits

from specify_cli.acceptance.runtime_lifecycle.process_tree import OwnedProcessTree

PROCESS_JSON_INTERACTION_PROVIDER = "process-json-v1"

_POLL_S = 0.01
_TREE_POLL_S = 0.025
_READ_CHUNK_BYTES = 65536


@dataclass(frozen=True)
class RuntimeInteractionProviderRequest:
    """One interaction dispatch: session identity, declared action, cwd, limits, milestones."""

    session_id: str
    session_started_at_epoch_ms: int
    action: dict[str, Any]
    cwd: str
    limits: ProcessLimits
    milestones: list[dict[str, Any]]


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(entry) for entry in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(entry) for key, entry in value.items())
    return False


class _BoundedCapture:
    """Drains one driver pipe on a thread, retaining at most ``cap`` bytes."""

    def __init__(self, raw: Any, cap: int) -> None:
        self._raw = raw
        self._cap = cap
        self._chunks: list[bytes] = []
        self._bytes = 0
        self.exceeded = False
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")

    def _drain(self) -> None:
        fd = self._raw.fileno()
        while True:
            try:
                chunk = os.read(fd, _READ_CHUNK_BYTES)
            except OSError:
                break
            if not chunk:
                break
            remaining = max(0, self._cap - self._bytes)
            if remaining > 0:
                retained = chunk[:remaining]
                self._chunks.append(retained)
                self._bytes += len(retained)
            if len(chunk) > remaining:
                self.exceeded = True
        with contextlib.suppress(Exception):
            self._raw.close()


def _valid_assertion(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and bool(entry["id"].strip())
        and isinstance(entry.get("passed"), bool)
        and ("expected" not in entry or _is_json_value(entry["expected"]))
        and ("observed" not in entry or _is_json_value(entry["observed"]))
    )


def _valid_evidence_shape(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("sessionId"), str)
        and isinstance(value.get("actionId"), str)
        and isinstance(value.get("attempted"), bool)
        and isinstance(value.get("reachedSeam"), bool)
        and isinstance(value.get("deliveredAtMs"), (int, float))
        and not isinstance(value.get("deliveredAtMs"), bool)
        and math.isfinite(value["deliveredAtMs"])
        and value["deliveredAtMs"] >= 0
        and isinstance(value.get("assertions"), list)
        and isinstance(value.get("details"), dict)
    )


def _parse_driver_evidence(value: Any) -> dict[str, Any]:
    if not _valid_evidence_shape(value):
        raise ValueError(
            "Interaction driver evidence requires sessionId, actionId, attempted, reachedSeam, nonnegative deliveredAtMs, "
            "assertions, and object details."
        )
    assertions: list[dict[str, Any]] = []
    for index, entry in enumerate(value["assertions"]):
        if not _valid_assertion(entry):
            raise ValueError(f"Interaction assertion {index} is malformed.")
        normalized: dict[str, Any] = {"id": entry["id"], "passed": entry["passed"]}
        if "expected" in entry:
            normalized["expected"] = entry["expected"]
        if "observed" in entry:
            normalized["observed"] = entry["observed"]
        assertions.append(normalized)
    if not _is_json_value(value["details"]):
        raise ValueError("Interaction driver details are not JSON-safe.")
    return {
        "sessionId": value["sessionId"],
        "actionId": value["actionId"],
        "attempted": value["attempted"],
        "reachedSeam": value["reachedSeam"],
        "deliveredAtMs": value["deliveredAtMs"],
        "assertions": assertions,
        "details": value["details"],
    }


@dataclass
class _DriverRun:
    proc: subprocess.Popen
    tree: OwnedProcessTree
    stdout: _BoundedCapture
    stderr: _BoundedCapture
    timeout_ms: int
    driver_error: str | None = None
    timed_out: bool = False
    cleanup_actions: list[dict[str, Any]] = field(default_factory=list)


class ProcessJsonInteractionProvider:
    """Dispatches one JSON request to a project-owned driver process."""

    id = PROCESS_JSON_INTERACTION_PROVIDER

    def invoke(self, request: RuntimeInteractionProviderRequest) -> dict[str, Any]:
        command = self._validated_command(request.action)
        timeout_ms = self._validated_timeout(request.action, request.limits)
        run = self._launch(command, request, timeout_ms)
        self._send_request(run, request)
        self._supervise(run)
        return self._conclude(run)

    @staticmethod
    def _validated_command(action: dict[str, Any]) -> list[str]:
        command = (action.get("request") or {}).get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) for argument in command)
            or not command[0].strip()
        ):
            raise ValueError("process-json-v1 interaction request requires a non-empty string 'command' argument vector.")
        return list(command)

    @staticmethod
    def _validated_timeout(action: dict[str, Any], limits: ProcessLimits) -> int:
        requested = (action.get("request") or {}).get("timeoutMs")
        timeout_ms = limits.timeout_ms if requested is None else requested
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not (1 <= timeout_ms <= limits.timeout_ms):
            raise ValueError("process-json-v1 interaction timeoutMs must be a positive integer within the validation timeout.")
        return timeout_ms

    @staticmethod
    def _launch(command: list[str], request: RuntimeInteractionProviderRequest, timeout_ms: int) -> _DriverRun:
        proc = subprocess.Popen(
            command,
            cwd=request.cwd,
            shell=False,
            start_new_session=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return _DriverRun(
            proc=proc,
            tree=OwnedProcessTree(proc.pid, int(time.time() * 1000)),
            stdout=_BoundedCapture(proc.stdout, request.limits.stdout_bytes),
            stderr=_BoundedCapture(proc.stderr, request.limits.stderr_bytes),
            timeout_ms=timeout_ms,
        )

    @staticmethod
    def _send_request(run: _DriverRun, request: RuntimeInteractionProviderRequest) -> None:
        payload = {
            "version": "1.0",
            "sessionId": request.session_id,
            "actionId": request.action["id"],
            "sessionStartedAtEpochMs": request.session_started_at_epoch_ms,
            "invokedAtEpochMs": int(time.time() * 1000),
            "request": (request.action.get("request") or {}).get("payload") or {},
            "milestones": request.milestones,
        }
        try:
            run.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            run.proc.stdin.close()
        except OSError as cause:
            run.driver_error = str(cause) or type(cause).__name__

    def _supervise(self, run: _DriverRun) -> None:
        deadline = time.monotonic() + run.timeout_ms / 1000
        last_tree_poll = 0.0
        while run.proc.poll() is None:
            if run.driver_error or run.stdout.exceeded or run.stderr.exceeded:
                break
            now = time.monotonic()
            if now >= deadline:
                run.timed_out = True
                break
            if now - last_tree_poll >= _TREE_POLL_S:
                run.tree.snapshot()
                last_tree_poll = now
            time.sleep(_POLL_S)
        if run.proc.poll() is None:
            run.tree.terminate(min(run.timeout_ms, 1000), run.cleanup_actions)
            with contextlib.suppress(Exception):
                run.proc.wait(timeout=2)
        run.stdout.join()
        run.stderr.join()

    def _conclude(self, run: _DriverRun) -> dict[str, Any]:
        with contextlib.suppress(Exception):
            run.proc.wait(timeout=2)
        if run.driver_error:
            raise RuntimeError(f"Interaction driver failed: {run.driver_error}")
        if run.timed_out:
            raise RuntimeError(f"Interaction driver exceeded its {run.timeout_ms} ms timeout.")
        if run.stdout.exceeded or run.stderr.exceeded:
            raise RuntimeError("Interaction driver exceeded its bounded output limit.")
        remaining = run.tree.snapshot()
        if remaining:
            run.tree.terminate(min(run.timeout_ms, 1000), run.cleanup_actions)
            raise RuntimeError(f"Interaction driver left owned process IDs resident: {', '.join(map(str, remaining))}.")
        if run.tree.errors:
            raise RuntimeError(f"Interaction driver process tree could not be verified: {'; '.join(run.tree.errors)}")
        returncode = run.proc.returncode
        if returncode != 0:
            code_text = "none" if returncode is None or returncode < 0 else str(returncode)
            signal_text = f" (signal {-returncode})" if returncode is not None and returncode < 0 else ""
            stderr_text = run.stderr.text().strip()
            raise RuntimeError(
                f"Interaction driver exited with code {code_text}{signal_text}{f': {stderr_text}' if stderr_text else ''}"
            )
        stdout_text = run.stdout.text().strip()
        try:
            parsed = json.loads(stdout_text)
        except ValueError as cause:
            raise RuntimeError(f"Interaction driver stdout is not one JSON document: {cause}") from cause
        return _parse_driver_evidence(parsed)
