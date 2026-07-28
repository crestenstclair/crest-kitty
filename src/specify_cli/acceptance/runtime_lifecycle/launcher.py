"""Runtime process launching in declared pipe or PTY mode (port of runtime-process-launcher.ts).

Pipe mode spawns the argv directly (``shell=False``, own session/process
group, stdin closed, stdout/stderr piped). PTY mode wraps the argv in the
platform ``script`` utility (``/usr/bin/script`` or ``/bin/script`` on
darwin/linux only) so the child sees a real terminal; when ``script`` is
unavailable the launcher reports ``pty_available == False`` and ``launch``
raises — the provider must fail the check as a required-proof gap and must
NEVER silently downgrade to pipe.

Deviations from the TS reference wrapper:
- The intermediate wrapper is Python (``sys.executable -c``) and uses
  ``os.execvp`` to replace itself with the target argv, so exit codes and
  signals propagate to ``script`` directly instead of via Node's spawn/relay.
- On darwin, BSD ``script`` accepts an argv directly and propagates the child
  exit status; on linux, ``util-linux script -qefc`` takes a shell string, so
  the wrapper argv is shell-quoted exactly like the upstream launcher.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

_SCRIPT_CANDIDATES = ("/usr/bin/script", "/bin/script")

# Decodes the base64url argv handed as its only argument and replaces itself with it.
_PTY_WRAPPER = (
    "import base64,json,os,sys;"
    "argv=json.loads(base64.urlsafe_b64decode(sys.argv[1].encode('ascii')).decode('utf-8'));"
    "os.execvp(argv[0], argv)"
)


def _find_script_executable() -> str | None:
    if sys.platform not in ("darwin", "linux"):
        return None
    for candidate in _SCRIPT_CANDIDATES:
        with contextlib.suppress(OSError):
            if os.path.isfile(candidate):
                return candidate
    return None


@dataclass(frozen=True)
class RuntimeLaunchRequest:
    argv: list[str]
    cwd: str
    stdio_mode: str  # "pipe" | "pty"


class ScriptRuntimeProcessLauncher:
    """Launches runtime sessions; PTY fidelity comes from POSIX ``script``."""

    def __init__(self) -> None:
        self._script_executable = _find_script_executable()

    @property
    def pty_available(self) -> bool:
        return self._script_executable is not None

    def launch(self, request: RuntimeLaunchRequest) -> subprocess.Popen:
        if request.stdio_mode == "pipe":
            return self._spawn(list(request.argv), request.cwd)
        if self._script_executable is None:
            raise RuntimeError(f"PTY transport is unavailable on platform '{sys.platform}'.")
        encoded = base64.urlsafe_b64encode(json.dumps(list(request.argv)).encode("utf-8")).decode("ascii")
        wrapper_argv = [sys.executable, "-c", _PTY_WRAPPER, encoded]
        if sys.platform == "darwin":
            script_arguments = ["-q", "/dev/null", *wrapper_argv]
        else:
            script_arguments = ["-qefc", " ".join(shlex.quote(argument) for argument in wrapper_argv), "/dev/null"]
        return self._spawn([self._script_executable, *script_arguments], request.cwd)

    @staticmethod
    def _spawn(argv: list[str], cwd: str) -> subprocess.Popen:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            shell=False,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
