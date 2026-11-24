"""Frank!Gateway (APISIX): its answers, and the outway's routes per app that replace the api-proxy."""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import urlsplit

from podiumd_tests.components import component_for_host
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import LOOPBACK
from podiumd_tests.kube import cluster_service
from podiumd_tests.responses import expect_status
from podiumd_tests.zgw_services import service_roots

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# The outway's path prefix per app: /<prefix>/<register>/... routes to the register, with that app's headers.
APP_PREFIXES = {"zac": "zac", "kiss": "kiss", "openformulieren": "forms", "openinwoner": "oip"}
# The registers each app reaches through its prefix.
APP_REGISTERS = {
    "zac": ("brp", "bag", "kvk"),
    "kiss": ("brp", "kvk"),
    "openformulieren": ("brp", "bag", "kvk", "pdok"),
    "openinwoner": ("brp", "bag", "kvk"),
}
# The ConfigMap keys that hold ZAC's and KISS's register URLs.
REGISTER_SETTINGS = {
    "zac": ("BRP_API_CLIENT_MP_REST_URL", "BAG_API_CLIENT_MP_REST_URL", "KVK_API_CLIENT_MP_REST_URL"),
    "kiss": ("HAAL_CENTRAAL_BASE_URL", "KVK_BASE_URL"),
}
ADMIN_PORT = 9180
API_KEY_HEADER = "x-api-key"
APPLICATION_HEADER = "x-request-application"
# KISS's fixed BRP headers; a header that differs per request has a second "__" and the request kind after it.
KISS_BRP_HEADER = "HAAL_CENTRAAL_CUSTOM_HEADERS__"
# The apps that send no BRP protocollering headers themselves: the outway sets KISS's for them.
WITHOUT_BRP_HEADERS = ("openformulieren", "openinwoner")


def is_no_route(response: requests.Response) -> bool:
    """Return True for APISIX's own 404 about a missing route: the request reached no upstream.

    A 404 from the upstream itself (e.g. an unknown KVK number) is not "no route".
    """
    if response.status_code != HTTPStatus.NOT_FOUND:
        return False
    try:
        body: object = response.json()
    except ValueError:
        return False
    message = cast("dict[str, object]", body).get("error_msg") if isinstance(body, dict) else None
    return isinstance(message, str) and re.search(r"route", message, re.IGNORECASE) is not None


def route_name(app: str, register: str) -> str:
    """Return the outway route of an app's register, e.g. forms-brp."""
    return f"{APP_PREFIXES[app]}-{register}"


def has_app_routes(http: requests.Session, outway_url: str) -> bool:
    """Return True when the outway routes per app, i.e. it has ZAC's BRP route."""
    return not is_no_route(http.get(f"{outway_url}/zac/brp/personen", headers={"Accept": "application/json"}))


def admin_routes(http: requests.Session, admin_url: str, key: str) -> dict[str, JsonObject]:
    """Return the routes of a gateway by name, from its Admin API."""
    response = http.get(f"{admin_url}/apisix/admin/routes", headers={"X-API-KEY": key})
    body = expect_status(response, HTTPStatus.OK).json()
    values = [section(item, "value") for item in entries(body.get("list"))]
    return {str(value.get("name")): value for value in values}


def outway_admin_routes(env: Environment, http: requests.Session, key: str) -> dict[str, JsonObject]:
    """Return the outway's routes by name, through a port-forward to its Admin API."""
    url = env.profile.urls["frankgateway"]
    service = cluster_service(url)
    if service is None:
        msg = f"frankgateway URL {url} is not an in-cluster Service: no Admin API to forward to"
        raise AssertionError(msg)
    name, namespace, _ = service
    with env.kube.port_forward(name, ADMIN_PORT, namespace=namespace) as port:
        return admin_routes(http, f"http://{LOOPBACK}:{port}", key)


def config_data(env: Environment, app: str) -> dict[str, str]:
    """Return the ConfigMap the app's deployment is named after: ZAC's and KISS's settings."""
    data = section(env.kube.get_json("configmap", env.deployment_for(app)), "data")
    return {key: str(value) for key, value in data.items()}


def register_settings(env: Environment, app: str) -> dict[str, str]:
    """Return an app's URLs to judge: ZAC's and KISS's register settings, the Django apps' Services."""
    if app not in REGISTER_SETTINGS:
        return service_roots(env, app)
    config = config_data(env, app)
    return {key: config[key] for key in REGISTER_SETTINGS[app] if config.get(key)}


def set_headers(route: JsonObject) -> dict[str, str]:
    """Return the request headers a route sets (proxy-rewrite)."""
    headers = section(section(section(section(route, "plugins"), "proxy-rewrite"), "headers"), "set")
    return {name: str(value) for name, value in headers.items()}


def kiss_brp_headers(config: Mapping[str, str]) -> dict[str, str]:
    """Return KISS's fixed BRP headers from its ConfigMap."""
    headers: dict[str, str] = {}
    for key, value in config.items():
        name = key.removeprefix(KISS_BRP_HEADER)
        if name != key and "__" not in name:
            headers[name] = value
    return headers


def expected_brp_headers(app: str, kiss_headers: Mapping[str, str]) -> dict[str, str]:
    """Return the fixed BRP headers of an app that sends none itself: KISS's, under the app's own application name."""
    prefix = APP_PREFIXES[app]
    return {
        name: value.replace("kiss", prefix, 1) if name == APPLICATION_HEADER else value
        for name, value in kiss_headers.items()
    }


def brp_header_problems(name: str, route: JsonObject, expected: Mapping[str, str]) -> list[str]:
    """Why a BRP route does not set the API key and the expected headers; [] when it does. Never shows the key."""
    found = set_headers(route)
    problems = [] if found.get(API_KEY_HEADER) else [f"{name}: sets no {API_KEY_HEADER}"]
    problems += [
        f"{name}: {header} is {found.get(header)!r}, expected {value!r}"
        for header, value in expected.items()
        if found.get(header) != value
    ]
    return problems


def brp_routes_problems(routes: Mapping[str, JsonObject], kiss_headers: Mapping[str, str]) -> list[str]:
    """Why the outway's BRP routes do not all set the API key, and KISS's headers for the apps without their own."""
    names = {app: route_name(app, "brp") for app in APP_PREFIXES}
    found = {app: name for app, name in names.items() if name in routes}
    if not found:
        return [f"no BRP route in the outway (looked for {', '.join(names.values())})"]
    problems: list[str] = []
    for app, name in found.items():
        expected = expected_brp_headers(app, kiss_headers) if app in WITHOUT_BRP_HEADERS else {}
        problems += brp_header_problems(name, routes[name], expected)
    return problems


def wiring_problems(app: str, settings: Mapping[str, str], outway_url: str, *, registers_only: bool) -> list[str]:
    """Why an app's register URLs are not on its own outway prefix; [] when they are.

    registers_only: every URL is a register's and must go through the outway; else only URLs on the api-proxy or
    the outway are judged (the app's other services).
    """
    outway = urlsplit(outway_url).netloc
    found = (
        _wiring_problem(APP_PREFIXES[app], url, outway, registers_only=registers_only) for url in settings.values()
    )
    return [
        f"{app} {name} {url}: {problem}"
        for (name, url), problem in zip(settings.items(), found, strict=True)
        if problem
    ]


def _wiring_problem(prefix: str, url: str, outway: str, *, registers_only: bool) -> str | None:
    parts = urlsplit(url)
    if component_for_host(parts.hostname or "") == "api-proxy":
        return "on the api-proxy"
    if parts.netloc != outway:
        return "not through the outway" if registers_only else None
    if parts.path == f"/{prefix}" or parts.path.startswith(f"/{prefix}/"):
        return None
    return f"on the outway, but not under /{prefix}/"
