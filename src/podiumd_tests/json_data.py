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
    """The object under key, or an empty one."""
    value = item.get(key)
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def entries(value: object) -> list[JsonObject]:
    """The objects in a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [cast("JsonObject", e) for e in cast("list[object]", value) if isinstance(e, dict)]


def strings(value: object) -> list[str]:
    """The strings in a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [e for e in cast("list[object]", value) if isinstance(e, str)]
