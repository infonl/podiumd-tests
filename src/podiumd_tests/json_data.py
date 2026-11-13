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


def unexpanded(item: JsonObject, path: str) -> list[str]:
    """Return the paths below item whose _expand lacks the objects item names, or that name none.

    path: an expand path of a ZGW API, e.g. "rollen.roltype"; a field holds a URL or a list of URLs.
    """
    head, _, rest = path.partition(".")
    urls = strings(_listed(item.get(head)))
    inlined = entries(_listed(section(item, "_expand").get(head)))
    inlined_urls = sorted(str(found.get("url")) for found in inlined)
    if not urls or inlined_urls != sorted(urls):
        return [path]
    if not rest:
        return []
    return [f"{head}.{missing}" for found in inlined for missing in unexpanded(found, rest)]


def _listed(value: object) -> list[object]:
    """Return a JSON list as it is, any other value but null as a list of it."""
    if isinstance(value, list):
        return cast("list[object]", value)
    return [] if value is None else [value]
