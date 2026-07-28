"""Runtime host capability registry (port of runtime-providers.ts capability half).

The default host capability set is exactly ``{'process', 'stdio:pipe',
'platform:<sys.platform>'}``; the process-lifecycle provider adds
``stdio:pty`` only when a PTY adapter is actually available. Any declared
``requiredCapabilities`` entry outside the available set is a blocking
required-proof gap, never a silent skip.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable


class RuntimeHostCapabilityRegistry:
    """The set of capabilities this host can honestly provide."""

    def __init__(self, capabilities: Iterable[str] = ()) -> None:
        self._available: set[str] = set()
        for capability in capabilities:
            self.add(capability)

    def add(self, capability: str) -> RuntimeHostCapabilityRegistry:
        if not capability.strip():
            raise ValueError("Runtime host capability cannot be empty.")
        self._available.add(capability)
        return self

    def has(self, capability: str) -> bool:
        return capability in self._available

    def missing(self, required: Iterable[str]) -> list[str]:
        return [capability for capability in required if not self.has(capability)]


def create_default_runtime_host_capabilities() -> RuntimeHostCapabilityRegistry:
    """Exactly the TS default: process, stdio:pipe, and the host platform."""
    return RuntimeHostCapabilityRegistry(["process", "stdio:pipe", f"platform:{sys.platform}"])
