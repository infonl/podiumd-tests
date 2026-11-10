"""CustomResourceDefinitions judged from `kubectl get customresourcedefinitions -o json` items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import condition_true
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence

    from podiumd_tests.json_data import JsonObject


@dataclass(frozen=True)
class Marker:
    """A field of a CRD's storage schema that tells its version: present from `since` on, or absent if not `present`."""

    crd: str
    since: tuple[int, ...]
    path: str  # dotted from the schema root; "b[]" is an item of array b
    present: bool = True


def is_established(crd: JsonObject) -> bool:
    """Whether the CRD has condition Established=True."""
    return condition_true(crd, "Established")


def storage_schema(crd: JsonObject) -> JsonObject:
    """Return the openAPIV3Schema of the CRD's storage version; empty when it has none."""
    for version in entries(section(crd, "spec").get("versions")):
        if version.get("storage") is True:
            return section(section(version, "schema"), "openAPIV3Schema")
    return {}


def has_field(schema: JsonObject, path: str) -> bool:
    """Whether the schema has the field at `path`, e.g. "spec.realm.identityProviders[].organizationLinks"."""
    node = schema
    for part in path.split("."):
        name = part.removesuffix("[]")
        properties = section(node, "properties")
        if name not in properties:
            return False
        node = section(properties, name)
        if part != name:
            node = section(node, "items")
    return True


def wrong_markers(crds: Iterable[JsonObject], markers: Sequence[Marker], version: tuple[int, ...]) -> list[str]:
    """Return the markers up to `version` the CRDs break, as "<crd>: lacks|has <path>" or "<crd>: not installed"."""
    schemas = {metadata_name(crd): storage_schema(crd) for crd in crds}
    wrong = (_marker_problem(schemas, marker) for marker in markers if marker.since <= version)
    return list(dict.fromkeys(problem for problem in wrong if problem))


def _marker_problem(schemas: dict[str, JsonObject], marker: Marker) -> str | None:
    schema = schemas.get(marker.crd)
    if schema is None:
        return f"{marker.crd}: not installed"
    if has_field(schema, marker.path) != marker.present:
        return f"{marker.crd}: {'lacks' if marker.present else 'has'} {marker.path}"
    return None
