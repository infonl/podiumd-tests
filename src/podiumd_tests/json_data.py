"""Safe reading of parsed JSON (kubectl output, API bodies) without a cast at every step.

Each helper returns an empty value instead of raising when the data has
another shape, so callers read optional fields in one expression.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Mapping

type JsonObject = Mapping[str, object]


def section(item: JsonObject, key: str) -> JsonObject:
    """Return the object under key, or an empty one."""
    value = item.get(key)
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def entries(value: object) -> list[JsonObject]:
    """Return the objects in a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [cast("JsonObject", entry) for entry in cast("list[object]", value) if isinstance(entry, dict)]


def strings(value: object) -> list[str]:
    """Return the strings in a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [entry for entry in cast("list[object]", value) if isinstance(entry, str)]
