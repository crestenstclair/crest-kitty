"""Integration tests for the deterministic process runner (spawns real subprocesses)."""

from __future__ import annotations

import dataclasses
import sys

import pytest

from specify_cli.acceptance.deterministic.process_runner import (
    MAX_ACCEPTANCE_STREAM_BYTES,
    MAX_ACCEPTANCE_TIMEOUT_MS,
    LocalCommandRunner,
    ProcessExecutionRequest,
    ProcessLimits,
)

pytestmark = pytest.mark.integration


def _run(
    argv: list[str],
    cwd: str,
    timeout_ms: int = 15_000,
    stdout_bytes: int = 1 << 20,
    stderr_bytes: int = 1 << 20,
):
    request = ProcessExecutionRequest(
        command=argv,
        working_directory=cwd,
        limits=ProcessLimits(timeout_ms=timeout_ms, stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes),
    )
    return LocalCommandRunner().run(request)


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_constants_match_contract():
    assert MAX_ACCEPTANCE_TIMEOUT_MS == 30 * 60 * 1000
    assert MAX_ACCEPTANCE_STREAM_BYTES == 16 * 1024 * 1024


def test_normal_exit(tmp_path):
    result = _run(_python("import sys; print('hello acceptance'); print('warn', file=sys.stderr)"), str(tmp_path))

    assert result.termination == "exited"
    assert result.exit_code == 0
    assert result.signal is None
    assert result.timed_out is False
    assert result.spawn_error is None
    assert result.output_limit_exceeded == []
    assert "hello acceptance" in result.stdout
    assert "warn" in result.stderr
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False
    assert 0 <= result.duration_ms < 15_000
    assert result.working_directory == str(tmp_path)


def test_nonzero_exit(tmp_path):
    result = _run(_python("import sys; sys.exit(3)"), str(tmp_path))

    assert result.termination == "exited"
    assert result.exit_code == 3
    assert result.signal is None


def test_timeout_kills_process(tmp_path):
    result = _run(_python("import time; time.sleep(60)"), str(tmp_path), timeout_ms=500)

    assert result.termination == "timed_out"
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.signal in ("SIGTERM", "SIGKILL")
    # Well under the sleep duration: the runner enforced the limit.
    assert 400 <= result.duration_ms < 15_000


def test_output_limit_truncates_and_terminates(tmp_path):
    code = "while True:\n    print('x' * 1024, flush=True)"
    result = _run(_python(code), str(tmp_path), stdout_bytes=2048)

    assert result.termination == "output_limit"
    assert result.stdout_truncated is True
    assert result.output_limit_exceeded == ["stdout"]
    assert len(result.stdout.encode("utf-8")) <= 2048
    assert result.timed_out is False
    assert result.exit_code is None  # the runner killed it


def test_stderr_output_limit(tmp_path):
    code = "import sys\nwhile True:\n    print('e' * 1024, file=sys.stderr, flush=True)"
    result = _run(_python(code), str(tmp_path), stderr_bytes=1024)

    assert result.termination == "output_limit"
    assert result.stderr_truncated is True
    assert "stderr" in result.output_limit_exceeded
    assert len(result.stderr.encode("utf-8")) <= 1024


def test_spawn_error_never_raises(tmp_path):
    result = _run(["/definitely/not/a/real/executable-xyz"], str(tmp_path))

    assert result.termination == "spawn_error"
    assert result.spawn_error is not None
    assert result.spawn_error.message
    assert result.spawn_error.code == "ENOENT"
    assert result.exit_code is None
    assert result.signal is None
    assert result.stdout == ""
    assert result.stderr == ""


def test_self_signal_reports_signaled(tmp_path):
    result = _run(_python("import os, signal; os.kill(os.getpid(), signal.SIGTERM)"), str(tmp_path))

    assert result.termination == "signaled"
    assert result.signal == "SIGTERM"
    assert result.exit_code is None
    assert result.timed_out is False


def test_no_environment_leakage(tmp_path, monkeypatch):
    sentinel = "sentinel-value-should-never-appear-a8f3"
    monkeypatch.setenv("ACCEPTANCE_SECRET_SENTINEL", sentinel)

    result = _run(_python("print('ok')"), str(tmp_path))

    assert result.exit_code == 0
    flattened = repr(dataclasses.asdict(result))
    assert sentinel not in flattened
    assert "ACCEPTANCE_SECRET_SENTINEL" not in flattened


def test_duration_is_monotonic_and_sane(tmp_path):
    result = _run(_python("import time; time.sleep(0.2)"), str(tmp_path))

    assert result.termination == "exited"
    assert isinstance(result.duration_ms, int)
    assert 150 <= result.duration_ms < 15_000
