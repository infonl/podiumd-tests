"""The zgw_consumers Services of the Django apps: their credentials, and the config fields that reference them."""

from __future__ import annotations

from dataclasses import dataclass
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
# Gateways in the environment to registers outside it: judged as those registers, by their answer alone.
GATEWAYS = ("api-proxy", "frankgateway")


@dataclass(frozen=True)
class ServiceReference:
    """A config field that must reference a Service in every row of its model; an FK, so the Service exists.

    An empty field means the rows are Services themselves, selected by where.
    """

    model: str
    field: str = ""
    where: tuple[tuple[str, str], ...] = ()

    def __str__(self) -> str:
        return (
            f"{self.model}.{self.field}"
            if self.field
            else f"{self.model} " + " ".join(f"{k}={v}" for k, v in self.where)
        )


NOTIFICATIONS = ServiceReference("notifications_api_common.NotificationsConfig", "notifications_api_service")
OF_ZGW_GROUP = "zgw_apis.ZGWApiGroupConfig"
OI_ZGW_GROUP = "openzaak.ZGWApiGroupConfig"

# Per app, the Service references PodiumD configures.
SERVICE_REFERENCES: dict[str, tuple[ServiceReference, ...]] = {
    "openzaak": (NOTIFICATIONS, ServiceReference("selectielijst.ReferentieLijstConfig", "service")),
    "openklant": (NOTIFICATIONS,),
    "openformulieren": (
        ServiceReference("objects_api.ObjectsAPIGroupConfig", "objects_service"),
        ServiceReference("objects_api.ObjectsAPIGroupConfig", "objecttypes_service"),
        ServiceReference(OF_ZGW_GROUP, "zrc_service"),
        ServiceReference(OF_ZGW_GROUP, "drc_service"),
        ServiceReference(OF_ZGW_GROUP, "ztc_service"),
    ),
    "openinwoner": (
        ServiceReference(OI_ZGW_GROUP, "zrc_service"),
        ServiceReference(OI_ZGW_GROUP, "drc_service"),
        ServiceReference(OI_ZGW_GROUP, "ztc_service"),
    ),
    "openarchiefbeheer": (ServiceReference("config.APIConfig", "selectielijst_api_service"),),
    "objecten": (NOTIFICATIONS,),
    "opennotificaties": (
        NOTIFICATIONS,
        ServiceReference("authorizations.AuthorizationsConfig", "authorizations_api_service"),
    ),
    "openbeheer": (
        ServiceReference("config.APIConfig", "selectielijst_api_service"),
        ServiceReference("config.APIConfig", "objecttypen_api_service"),
        # Open Beheer offers every Catalogi API Service.
        ServiceReference("zgw_consumers.Service", where=(("api_type", "ztc"),)),
    ),
}


def list_path(api_root: str) -> str | None:
    """The LIST_PATHS endpoint of the API at api_root, or None for an API not in it."""
    url = urlsplit(api_root)
    before_api, has_api, _ = url.path.partition("/api/")
    name = before_api.strip("/") if has_api else ""
    return LIST_PATHS.get(name or component_for_host(url.hostname or "") or "")


def _services(env: Environment, component: str, probes: dict[str, str]) -> list[dict[str, object]]:
    used = [dict(r.where) for r in SERVICE_REFERENCES.get(component, ()) if not r.field]
    found = run_snippet(env.kube, env.deployment_for(component), "zgw_services", {"probes": probes, "used": used})
    return cast("list[dict[str, object]]", found)


def service_problem(service: Mapping[str, object], path: str | None) -> str | None:
    """Why the probed Service fails, or None.

    An API in LIST_PATHS must list with the Service's credentials. An API outside the environment and
    LIST_PATHS (a public register, or one behind GATEWAYS) only has to answer its api_root without a server error.
    """
    status, api_root = service["status"], str(service["api_root"])
    described = f"{service['name']} {api_root}{path or ''} ({service['auth_type']}): {status}"
    if path is not None:
        ok = isinstance(status, int) and HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES
        return None if ok else f"{described}, expected 2xx with its credentials"
    if component_for_host(urlsplit(api_root).hostname or "") not in (None, *GATEWAYS):
        return f"{described}: no list endpoint for this API in LIST_PATHS"
    ok = isinstance(status, int) and status < HTTPStatus.INTERNAL_SERVER_ERROR
    return None if ok else f"{described}, expected an answer below 500"


def service_problems(env: Environment, component: str) -> list[str]:
    """Why the component's referenced Services fail service_problem; [] when all pass.

    A Service that no config field references is never called, so its credentials are not asserted.
    """
    paths = {str(s["uuid"]): list_path(str(s["api_root"])) for s in _services(env, component, {}) if s["referenced"]}
    probed = _services(env, component, {uuid: path or "" for uuid, path in paths.items()})
    return [p for s in probed if str(s["uuid"]) in paths and (p := service_problem(s, paths[str(s["uuid"])]))]


def reference_problems(env: Environment, component: str) -> list[str]:
    """The component's SERVICE_REFERENCES without rows or with an unset field; [] when all are set."""
    references = SERVICE_REFERENCES[component]
    params: dict[str, object] = {
        "references": [{"model": r.model, "field": r.field, "where": dict(r.where)} for r in references]
    }
    found = cast(
        "list[list[str | None]]",
        run_snippet(env.kube, env.deployment_for(component), "zgw_service_references", params),
    )
    problems: list[str] = []
    for reference, rows in zip(references, found, strict=True):
        if not rows:
            problems.append(f"{reference}: no rows")
        elif None in rows:
            problems.append(f"{reference}: unset in {rows.count(None)} of {len(rows)} rows")
    return problems
