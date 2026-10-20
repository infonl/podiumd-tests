"""The zgw_consumers Services of the Django apps, called with their own credentials."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import urlsplit

from podiumd_tests.components import component_for_host
from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from podiumd_tests.environment import Environment

# A list endpoint per API that answers 2xx only to an authorised client. The API is the path before /api/
# (Open Zaak, Open Klant), else the component of the host. Zaken API: statussen, as its zaken list needs Accept-Crs.
LIST_PATHS = {
    "zaken": "statussen",
    "documenten": "enkelvoudiginformatieobjecten",
    "catalogi": "catalogussen",
    "besluiten": "besluiten",
    "autorisaties": "applicaties",
    "klantinteracties": "partijen",
    "opennotificaties": "kanaal",
    "objecten": "objects",
    "objecttypen": "objecttypes",
}


def list_path(api_root: str) -> str | None:
    """The LIST_PATHS endpoint of the API at api_root, or None for an API not in it."""
    url = urlsplit(api_root)
    before_api, has_api, _ = url.path.partition("/api/")
    name = before_api.strip("/") if has_api else ""
    return LIST_PATHS.get(name or component_for_host(url.hostname or "") or "")


def _services(env: Environment, component: str, probes: dict[str, str]) -> list[dict[str, object]]:
    found = run_snippet(env.kube, env.deployment_for(component), "zgw_services", {"probes": probes})
    return cast("list[dict[str, object]]", found)


def service_problem(service: Mapping[str, object], path: str | None) -> str | None:
    """Why the probed Service fails, or None.

    An API in LIST_PATHS must list with the Service's credentials. An API outside the environment and
    LIST_PATHS (a public register, a gateway) only has to answer its api_root without a server error.
    """
    status, api_root = service["status"], str(service["api_root"])
    described = f"{service['name']} {api_root}{path or ''} ({service['auth_type']}): {status}"
    if path is not None:
        ok = isinstance(status, int) and HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES
        return None if ok else f"{described}, expected 2xx with its credentials"
    if component_for_host(urlsplit(api_root).hostname or "") is not None:
        return f"{described}: no list endpoint for this API in LIST_PATHS"
    ok = isinstance(status, int) and status < HTTPStatus.INTERNAL_SERVER_ERROR
    return None if ok else f"{described}, expected an answer below 500"


def service_problems(env: Environment, component: str) -> list[str]:
    """Why the component's Services fail service_problem; [] when all pass."""
    paths = {str(s["uuid"]): list_path(str(s["api_root"])) for s in _services(env, component, {})}
    probed = _services(env, component, {uuid: path or "" for uuid, path in paths.items()})
    return [p for s in probed if (p := service_problem(s, paths[str(s["uuid"])])) is not None]
