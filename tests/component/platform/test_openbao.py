"""OpenBao hardening: its Prometheus metrics must not be readable without a token on the API listener.

OpenBao's /v1/sys/metrics exposes mount paths, token and lease counts and seal/HA state. On a listener with
unauthenticated_metrics_access the public host would serve them to anyone; this asserts a token is required.
Skips where the profile has no OpenBao URL.

With podiumd's observability on (openbao.serverTelemetry.serviceMonitor.enabled, helm-charts #625), OpenBao has a
second, metrics-only listener (Service port "metrics", 9101) that Prometheus scrapes without a token. That listener
must serve the metrics and nothing else; it is reached through a port-forward and skipped where no Service has it.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import describe

if TYPE_CHECKING:
    from collections.abc import Generator

    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("openbao")]

REFUSED = {HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED}
METRICS_PORT_NAME = "metrics"


@pytest.mark.parametrize("query", ["", "?format=prometheus"])
def test_metrics_need_a_token(http: requests.Session, urls: dict[str, str], query: str) -> None:
    """Without a token the metrics endpoint is refused, not 200 with metrics."""
    response = http.get(f"{urls['openbao']}/v1/sys/metrics{query}")
    assert response.status_code in REFUSED, describe(response)


def metrics_listener(services: list[dict[str, object]]) -> tuple[str, int] | None:
    """The OpenBao Service with a "metrics" port, and that port; the plain Service before -active, -standby etc."""
    found = [
        (metadata_name(s), int(str(p.get("port"))))
        for s in services
        if "openbao" in metadata_name(s)
        for p in section(s, "spec").get("ports") or []
        if isinstance(p, dict) and p.get("name") == METRICS_PORT_NAME
    ]
    return min(found, key=lambda f: len(f[0])) if found else None


@pytest.fixture(scope="module", name="metrics_url")
def fixture_metrics_url(podiumd_env: Environment) -> Generator[str]:
    """http://127.0.0.1:<port> forwarded to OpenBao's metrics-only listener."""
    listener = metrics_listener(podiumd_env.items("services", [podiumd_env.profile.kube.namespace]))
    if listener is None:
        pytest.skip("no OpenBao Service with a metrics port (openbao.serverTelemetry.serviceMonitor off)")
    service, port = listener
    with podiumd_env.kube.port_forward(service, port, namespace=podiumd_env.profile.kube.namespace) as local:
        yield f"http://127.0.0.1:{local}"


@pytest.mark.cluster
@pytest.mark.requires("cluster")
def test_metrics_listener_serves_prometheus_metrics_without_a_token(http: requests.Session, metrics_url: str) -> None:
    """The metrics-only listener answers /v1/sys/metrics?format=prometheus with metrics, no token needed."""
    response = http.get(f"{metrics_url}/v1/sys/metrics?format=prometheus")
    assert response.status_code == HTTPStatus.OK, describe(response)
    assert "# TYPE " in response.text, f"no Prometheus metrics: {response.text[:200]!r}"


@pytest.mark.cluster
@pytest.mark.requires("cluster")
@pytest.mark.parametrize("path", ["/v1/sys/seal-status", "/v1/sys/mounts", "/v1/secret/data/x", "/ui/"])
def test_metrics_listener_serves_nothing_else(http: requests.Session, metrics_url: str, path: str) -> None:
    """metrics_only: every other path on the metrics listener is refused or not found, never 200."""
    response = http.get(f"{metrics_url}{path}", allow_redirects=False)
    assert response.status_code != HTTPStatus.OK, describe(response)
    assert response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR, describe(response)
