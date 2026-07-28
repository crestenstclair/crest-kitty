"""Runtime lifecycle acceptance engine (port of CrestOpenSpec's runtime-session stack).

Executes declared runtime-session proofs: bounded and persistent process
lifecycles under six timeout budgets, owned-process-tree cleanup by pid/pgid
descent only, pipe/PTY stdio fidelity, window-bound interactions, and host
capability gating. Every outcome is a JSON-safe dict with the upstream
diagnostic codes.
"""

from __future__ import annotations

from specify_cli.acceptance.runtime_lifecycle.capabilities import (
    RuntimeHostCapabilityRegistry,
    create_default_runtime_host_capabilities,
)
from specify_cli.acceptance.runtime_lifecycle.interactions import (
    PROCESS_JSON_INTERACTION_PROVIDER,
    ProcessJsonInteractionProvider,
    RuntimeInteractionProviderRequest,
)
from specify_cli.acceptance.runtime_lifecycle.launcher import (
    RuntimeLaunchRequest,
    ScriptRuntimeProcessLauncher,
)
from specify_cli.acceptance.runtime_lifecycle.process_tree import OwnedProcessTree
from specify_cli.acceptance.runtime_lifecycle.registry import (
    RuntimeInteractionProviderRegistry,
    RuntimeSessionProviderRegistry,
    create_default_runtime_interaction_registry,
    create_default_runtime_session_registry,
)
from specify_cli.acceptance.runtime_lifecycle.session import (
    OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER,
    PROCESS_LIFECYCLE_RUNTIME_PROVIDER,
    ProcessLifecycleRuntimeProvider,
    RuntimeSessionProviderResult,
)

__all__ = [
    "OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER",
    "PROCESS_JSON_INTERACTION_PROVIDER",
    "PROCESS_LIFECYCLE_RUNTIME_PROVIDER",
    "OwnedProcessTree",
    "ProcessJsonInteractionProvider",
    "ProcessLifecycleRuntimeProvider",
    "RuntimeHostCapabilityRegistry",
    "RuntimeInteractionProviderRegistry",
    "RuntimeInteractionProviderRequest",
    "RuntimeLaunchRequest",
    "RuntimeSessionProviderRegistry",
    "RuntimeSessionProviderResult",
    "ScriptRuntimeProcessLauncher",
    "create_default_runtime_host_capabilities",
    "create_default_runtime_interaction_registry",
    "create_default_runtime_session_registry",
]
