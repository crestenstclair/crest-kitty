"""YAML parsing for the architecture spec.

Standard parsers silently keep the last of two duplicate mapping keys; in a
spec where map position IS identity that would silently drop a resource, so
duplicate keys are a hard error here.
"""

from __future__ import annotations

from typing import Any

import yaml


class DuplicateKeyError(ValueError):
    def __init__(self, key: object, mark: object):
        self.key = key
        super().__init__(f"duplicate mapping key {key!r} at {mark}")


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise DuplicateKeyError(key, key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_yaml_strict(text: str) -> Any:
    """Parse YAML rejecting duplicate mapping keys. Raises yaml.YAMLError or
    DuplicateKeyError."""
    return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 — SafeLoader subclass
