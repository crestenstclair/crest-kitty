"""Bounded subprocess execution for the deterministic acceptance engine.

Port of ``research/crestopenspec-port/reference-process-runner.ts``. Runs one
argv-list command (``shell=False``, never a shell string) under three hard
bounds — a wall-clock timeout and per-stream byte caps — and reduces every
outcome, including spawn failure, to a plain :class:`ProcessResult` value.
``run`` never raises for process-level failures.

Termination precedence mirrors the TypeScript reference exactly:
``timed_out`` > ``output_limit`` > ``spawn_error`` > ``signaled`` > ``exited``.
Environment variable values never appear anywhere in the result.
"""

from __future__ import annotations

import contextlib
import errno
import os
import signal as signal_module
import subprocess
import threading
import time
from dataclasses import dataclass, field

# Runtime enforcement ceilings. Declaration-level validation of requested
# limits happens elsewhere; the runner clamps whatever it is handed to these.
MAX_ACCEPTANCE_TIMEOUT_MS = 30 * 60 * 1000
MAX_ACCEPTANCE_STREAM_BYTES = 16 * 1024 * 1024

_FORCE_KILL_DELAY_MS = 250
_READ_CHUNK_BYTES = 65536


@dataclass(frozen=True)
class ProcessLimits:
    """Declared execution bounds for one command run."""

    timeout_ms: int
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class ProcessSpawnError:
    """Why the process could not be spawned (mirrors the TS ProcessSpawnError)."""

    message: str
    code: str | None = None


@dataclass(frozen=True)
class ProcessExecutionRequest:
    """One command to run: argv list, working directory, and limits."""

    command: list[str]
    working_directory: str
    limits: ProcessLimits


@dataclass(frozen=True)
class ProcessResult:
    """Complete, environment-free record of one bounded process execution.

    ``termination`` is one of ``'exited'``, ``'signaled'``, ``'timed_out'``,
    ``'output_limit'``, ``'spawn_error'``.
    """

    command: list[str]
    working_directory: str
    limits: ProcessLimits
    duration_ms: int
    termination: str
    exit_code: int | None
    signal: str | None
    timed_out: bool
    output_limit_exceeded: list[str] = field(default_factory=list)
    spawn_error: ProcessSpawnError | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class _StreamCapture:
    """Drains one pipe on a thread, retaining at most ``cap`` bytes.

    Once the cap is exceeded the capture keeps draining (so the child never
    blocks on a full pipe) but stops retaining, and asks the supervisor to
    terminate the process.
    """

    def __init__(self, name: str, raw, cap: int, on_overflow) -> None:
        self.name = name
        self._raw = raw
        self._cap = cap
        self._on_overflow = on_overflow
        self._chunks: list[bytes] = []
        self._bytes = 0
        self.truncated = False
        self._thread = threading.Thread(target=self._drain, name=f"acceptance-{name}-capture", daemon=True)

    def start(self) -> None:
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
            self._capture(chunk)
        self._raw.close()

    def _capture(self, chunk: bytes) -> None:
        remaining = max(0, self._cap - self._bytes)
        if remaining > 0:
            retained = chunk[:remaining]
            self._chunks.append(retained)
            self._bytes += len(retained)
        if len(chunk) > remaining:
            self.truncated = True
            self._on_overflow(self.name)


def _signal_process_group(proc: subprocess.Popen, signum: int) -> None:
    # start_new_session=True makes the child its own process-group leader, so
    # the group id equals the child pid; killing the group reaps grandchildren.
    try:
        os.killpg(proc.pid, signum)
    except OSError:
        with contextlib.suppress(OSError):
            proc.send_signal(signum)


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole group, escalate to SIGKILL after a short grace."""
    _signal_process_group(proc, signal_module.SIGTERM)
    try:
        proc.wait(timeout=_FORCE_KILL_DELAY_MS / 1000)
    except subprocess.TimeoutExpired:
        _signal_process_group(proc, signal_module.SIGKILL)


def _signal_name(signum: int) -> str:
    try:
        return signal_module.Signals(signum).name
    except ValueError:
        return f"SIG{signum}"


def _termination_for(timed_out: bool, output_limit_exceeded: list[str], spawn_error: ProcessSpawnError | None, signal_name: str | None) -> str:
    if timed_out:
        return "timed_out"
    if output_limit_exceeded:
        return "output_limit"
    if spawn_error is not None:
        return "spawn_error"
    if signal_name is not None:
        return "signaled"
    return "exited"


def _spawn_error_from(error: BaseException) -> ProcessSpawnError:
    code: str | None = None
    if isinstance(error, OSError) and error.errno is not None:
        code = errno.errorcode.get(error.errno)
    return ProcessSpawnError(message=str(error) or type(error).__name__, code=code)


class LocalCommandRunner:
    """Runs argv-list commands with bounded capture; the Python NodeCommandRunner."""

    def run(self, request: ProcessExecutionRequest) -> ProcessResult:
        """Execute the request and always return a ProcessResult, never raise."""
        command = list(request.command)
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                command,
                cwd=request.working_directory,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as error:  # spawn failure is data, not an exception
            return ProcessResult(
                command=command,
                working_directory=request.working_directory,
                limits=request.limits,
                duration_ms=_elapsed_ms(started),
                termination="spawn_error",
                exit_code=None,
                signal=None,
                timed_out=False,
                spawn_error=_spawn_error_from(error),
            )
        return self._supervise(request, command, proc, started)

    def _supervise(self, request: ProcessExecutionRequest, command: list[str], proc: subprocess.Popen, started: float) -> ProcessResult:
        overflowed: list[str] = []
        termination_requested = threading.Event()

        def on_overflow(stream_name: str) -> None:
            if stream_name not in overflowed:
                overflowed.append(stream_name)
            if not termination_requested.is_set():
                termination_requested.set()
                _terminate_process_group(proc)

        stdout_cap = _StreamCapture("stdout", proc.stdout, min(request.limits.stdout_bytes, MAX_ACCEPTANCE_STREAM_BYTES), on_overflow)
        stderr_cap = _StreamCapture("stderr", proc.stderr, min(request.limits.stderr_bytes, MAX_ACCEPTANCE_STREAM_BYTES), on_overflow)
        stdout_cap.start()
        stderr_cap.start()

        timed_out = False
        try:
            proc.wait(timeout=min(request.limits.timeout_ms, MAX_ACCEPTANCE_TIMEOUT_MS) / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_requested.set()
            _terminate_process_group(proc)
            proc.wait()
        stdout_cap.join()
        stderr_cap.join()

        returncode = proc.returncode
        signal_name = _signal_name(-returncode) if returncode is not None and returncode < 0 else None
        exit_code = returncode if returncode is not None and returncode >= 0 else None
        exceeded = [stream for stream in ("stdout", "stderr") if stream in overflowed]

        return ProcessResult(
            command=command,
            working_directory=request.working_directory,
            limits=request.limits,
            duration_ms=_elapsed_ms(started),
            termination=_termination_for(timed_out, exceeded, None, signal_name),
            exit_code=exit_code,
            signal=signal_name,
            timed_out=timed_out,
            output_limit_exceeded=exceeded,
            spawn_error=None,
            stdout=stdout_cap.text(),
            stderr=stderr_cap.text(),
            stdout_truncated=stdout_cap.truncated,
            stderr_truncated=stderr_cap.truncated,
        )


def _elapsed_ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))
