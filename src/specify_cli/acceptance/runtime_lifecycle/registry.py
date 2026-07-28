"""Provider registries for runtime sessions, interactions, and teardown.

Registration is explicit and fail-closed: an unknown provider id resolves to
``None`` and the caller must emit its ``*_provider_unsupported`` diagnostic —
providers are never inferred from the command, framework, or host.
"""

from __future__ import annotations

from typing import Any

from specify_cli.acceptance.runtime_lifecycle.interactions import ProcessJsonInteractionProvider


class _ProviderRegistry:
    """Id-keyed provider registry; duplicate or empty ids are declaration errors."""

    _kind = "provider"

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, provider: Any) -> _ProviderRegistry:
        provider_id = getattr(provider, "id", "")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError(f"{self._kind} id cannot be empty.")
        if provider_id in self._providers:
            raise ValueError(f"{self._kind} '{provider_id}' is already registered.")
        self._providers[provider_id] = provider
        return self

    def get(self, provider_id: str) -> Any | None:
        return self._providers.get(provider_id)


class RuntimeSessionProviderRegistry(_ProviderRegistry):
    _kind = "Runtime-session provider"


class RuntimeInteractionProviderRegistry(_ProviderRegistry):
    _kind = "Runtime interaction provider"


def create_default_runtime_interaction_registry() -> RuntimeInteractionProviderRegistry:
    registry = RuntimeInteractionProviderRegistry()
    registry.register(ProcessJsonInteractionProvider())
    return registry


def create_default_runtime_session_registry() -> RuntimeSessionProviderRegistry:
    """The default registry: process-lifecycle-v1 (which owns owned-process-signal-v1 teardown)."""
    from specify_cli.acceptance.runtime_lifecycle.session import ProcessLifecycleRuntimeProvider

    registry = RuntimeSessionProviderRegistry()
    registry.register(ProcessLifecycleRuntimeProvider())
    return registry
