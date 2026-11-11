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


def differences(wanted: object, found: object, path: str = "") -> list[str]:
    """Return the paths where found lacks wanted: objects compare by wanted's keys, a wanted list item needs a match."""
    if isinstance(wanted, dict):
        if not isinstance(found, dict):
            return [path]
        have = cast("dict[str, object]", found)
        prefix = f"{path}." if path else ""
        return [
            difference
            for key, value in cast("dict[str, object]", wanted).items()
            for difference in differences(value, have.get(key), prefix + key)
        ]
    if isinstance(wanted, list):
        candidates = cast("list[object]", found) if isinstance(found, list) else []
        return [
            f"{path}[{index}]"
            for index, item in enumerate(cast("list[object]", wanted))
            if all(differences(item, candidate) for candidate in candidates)
        ]
    return [] if wanted == found else [path]
